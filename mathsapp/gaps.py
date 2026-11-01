"""Fiches de lacunes : ce qu'on a dû redemander à l'assistant.

En travaillant un cours, on bute souvent sur une notion de base oubliée
(module d'un complexe, conjugué d'un produit scalaire…). On la redemande, on
avance, et elle repart aussitôt. À la fin d'une séance, l'assistant relit les
échanges et propose une fiche par notion fondamentale oubliée : une question à
choix multiples, à chercher de tête avant d'afficher les propositions.

Une fois validées, les fiches entrent dans les révisions espacées ordinaires
(série « lacunes » de question_result) : ratée, elle revient le jour même ;
réussie, elle revient de plus en plus tard. Une notion redemandée alors qu'elle
a déjà sa fiche ne crée pas de doublon : la fiche redevient due.

Stockage : library/_lacunes/cards.json (les fiches) ; le calendrier est dans
progress.db, comme pour toutes les questions.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time
from typing import Dict, List, Optional

from .paths import library_dir

SET_ID = "lacunes"
JOB_ID = "_lacunes"          # identifiant du travail dans la file de génération
KIND = "rappel"              # question à chercher de tête avant les propositions
PROPOSED, ACTIVE, DISCARDED = "proposed", "active", "discarded"
ACQUIRED_DAYS = 21.0         # intervalle à partir duquel une fiche est acquise
MAX_EXCHANGES = 80
FIRST_SCAN_DAYS = 3          # relecture limitée aux derniers jours


def _path():
    d = library_dir() / "_lacunes"
    d.mkdir(parents=True, exist_ok=True)
    return d / "cards.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("scanned_until", 0.0)
    data.setdefault("cards", [])
    return data


def save(data: dict) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def cards(status: Optional[str] = None) -> List[dict]:
    return [c for c in load()["cards"] if status is None or c.get("status") == status]


# ------------------------------------------------------------- échanges
def _real_course(course_id: str) -> bool:
    return bool(course_id) and not course_id.startswith(("selftest", "_"))


def exchanges(since: float, until: Optional[float] = None) -> List[dict]:
    """Questions posées à l'assistant depuis `since`, chacune avec la réponse
    qui l'a suivie : [{course_id, at, user, assistant}]."""
    from . import store
    until = until if until is not None else time.time()
    rows = store.conn().execute(
        "SELECT m.thread_id, m.role, m.content, m.created_at, t.course_id "
        "FROM chat_message m JOIN chat_thread t ON t.id = m.thread_id "
        "WHERE m.created_at > ? AND m.created_at <= ? ORDER BY m.thread_id, m.created_at",
        (since, until)).fetchall()
    out: List[dict] = []
    pending: Dict[int, dict] = {}
    for r in rows:
        if not _real_course(r["course_id"] or ""):
            continue
        if r["role"] == "user":
            item = {"course_id": r["course_id"], "at": r["created_at"],
                    "user": r["content"], "assistant": ""}
            out.append(item)
            pending[r["thread_id"]] = item
        elif r["role"] == "assistant" and r["thread_id"] in pending:
            pending.pop(r["thread_id"])["assistant"] = r["content"]
    out.sort(key=lambda e: e["at"])
    return out[-MAX_EXCHANGES:]


def needs_scan(before: Optional[float] = None) -> bool:
    """Des échanges pas encore relus (antérieurs à `before` si donné)."""
    data = load()
    return bool(exchanges(data["scanned_until"], before))


# --------------------------------------------------------------- fiches
def _question_fields(raw: dict) -> Optional[dict]:
    choices = [str(c) for c in (raw.get("choices") or []) if str(c).strip()]
    try:
        answer = int(raw.get("answer", 0))
    except (TypeError, ValueError):
        return None
    if len(choices) < 2 or not 0 <= answer < len(choices) or not str(raw.get("question", "")).strip():
        return None
    return {"question": str(raw["question"]), "choices": choices, "answer": answer,
            "explanation": str(raw.get("explanation", ""))}


def propose(raw_cards: List[dict], valid_courses, scanned_until: float,
            now: Optional[float] = None) -> dict:
    """Range le résultat de l'extraction. Les notions déjà en fiche redeviennent
    dues ; les autres sont proposées à la validation. Retourne {new, relapsed}."""
    now = now if now is not None else time.time()
    data = load()
    by_id = {c["id"]: c for c in data["cards"]}
    new, relapsed = 0, []
    for i, raw in enumerate(raw_cards or []):
        same = str(raw.get("same_as") or "")
        if same in by_id and by_id[same].get("status") == ACTIVE:
            relapsed.append(same)
            continue
        main = _question_fields(raw)
        course_id = str(raw.get("course_id") or "")
        if main is None or course_id not in valid_courses:
            continue
        variants = [v for v in (_question_fields(x) for x in raw.get("variants") or []) if v]
        data["cards"].append(dict(
            main, id="g%d-%d" % (int(now), i), course_id=course_id,
            notion=str(raw.get("notion") or "").strip() or "Notion",
            variants=variants, difficulty=max(1, min(5, int(raw.get("difficulty") or 2))),
            status=PROPOSED, created_at=now))
        new += 1
    data["scanned_until"] = max(float(data["scanned_until"]), scanned_until)
    save(data)
    for cid in relapsed:
        relapse(by_id[cid])
    return {"new": new, "relapsed": relapsed}


def _due_now(card: dict, now: float) -> None:
    from . import store
    c = store.conn()
    c.execute(
        """INSERT INTO question_result
             (course_id, set_id, question_id, last_ok, tries, ok_count, updated_at,
              due_at, interval_days, ease)
           VALUES (?,?,?,0,0,0,?,?,0,NULL)
           ON CONFLICT(course_id, set_id, question_id) DO UPDATE SET
             due_at=excluded.due_at, interval_days=0""",
        (card["course_id"], SET_ID, card["id"], now, now))
    c.commit()


def relapse(card: dict, now: Optional[float] = None) -> None:
    """Notion redemandée alors qu'elle a sa fiche : elle revient tout de suite."""
    _due_now(card, now if now is not None else time.time())


def decide(keep: List[str], drop: List[str], edits: Optional[Dict[str, str]] = None,
           now: Optional[float] = None) -> List[dict]:
    """Validation : les fiches gardées deviennent actives et dues ; retourne-les.
    `edits` : {id: nouvel intitulé de notion}."""
    now = now if now is not None else time.time()
    data = load()
    kept = []
    for card in data["cards"]:
        if card.get("status") != PROPOSED:
            continue
        if card["id"] in keep:
            card["status"] = ACTIVE
            if edits and edits.get(card["id"], "").strip():
                card["notion"] = edits[card["id"]].strip()
            kept.append(card)
        elif card["id"] in drop:
            card["status"] = DISCARDED
    save(data)
    for card in kept:
        _due_now(card, now)
    return kept


def as_question(card: dict, day: Optional[str] = None) -> dict:
    """La fiche sous forme de question de QCM. Les variantes tournent d'un jour
    à l'autre : on retient la notion, pas la phrase."""
    versions = [card] + list(card.get("variants") or [])
    day = day or _dt.date.today().isoformat()
    pick = versions[_dt.date.fromisoformat(day).toordinal() % len(versions)]
    return {"id": card["id"], "kind": KIND, "difficulty": card.get("difficulty", 2),
            "question": pick["question"], "choices": pick["choices"],
            "answer": pick["answer"], "explanation": pick.get("explanation", ""),
            "section": card.get("notion", ""), "course_id": card["course_id"]}


def index() -> Dict[tuple, dict]:
    """{(course_id, SET_ID, id): question} des fiches actives (pour question_index)."""
    return {(c["course_id"], SET_ID, c["id"]): as_question(c) for c in cards(ACTIVE)}


def stats(now: Optional[float] = None) -> dict:
    """{active, acquired, learning, due, proposed}."""
    from . import store
    now = now if now is not None else time.time()
    active = {c["id"] for c in cards(ACTIVE)}
    rows = store.conn().execute(
        "SELECT question_id, interval_days, due_at FROM question_result WHERE set_id=?",
        (SET_ID,)).fetchall()
    acquired = due = 0
    for r in rows:
        if r["question_id"] not in active:
            continue
        if (r["interval_days"] or 0) >= ACQUIRED_DAYS:
            acquired += 1
        if r["due_at"] is not None and r["due_at"] <= now:
            due += 1
    return {"active": len(active), "acquired": acquired,
            "learning": len(active) - acquired, "due": due,
            "proposed": len(cards(PROPOSED))}
