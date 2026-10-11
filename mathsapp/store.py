"""Persistance de la progression (SQLite)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .paths import db_file

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_state (
    course_id     TEXT PRIMARY KEY,
    generated_at  REAL,
    model         TEXT,
    cost_usd      REAL DEFAULT 0,
    duration_s    REAL DEFAULT 0,
    opened_at     REAL,
    open_count    INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quiz_attempt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   TEXT NOT NULL,
    finished_at REAL NOT NULL,
    total       INTEGER NOT NULL,
    correct     INTEGER NOT NULL,
    detail      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attempt_course ON quiz_attempt(course_id);

CREATE TABLE IF NOT EXISTS proof_state (
    course_id   TEXT NOT NULL,
    proof_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, proof_id)
);

CREATE TABLE IF NOT EXISTS question_result (
    course_id   TEXT NOT NULL,
    set_id      TEXT NOT NULL DEFAULT '1',
    question_id TEXT NOT NULL,
    last_ok     INTEGER NOT NULL DEFAULT 0,
    tries       INTEGER NOT NULL DEFAULT 0,
    ok_count    INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, set_id, question_id)
);

-- Journal du jour : une ligne par journee travaillee.
CREATE TABLE IF NOT EXISTS day_log (
    day        TEXT PRIMARY KEY,
    bricks     INTEGER NOT NULL DEFAULT 0,
    questions  INTEGER NOT NULL DEFAULT 0,
    correct    INTEGER NOT NULL DEFAULT 0,
    proofs     INTEGER NOT NULL DEFAULT 0,
    reviews    INTEGER NOT NULL DEFAULT 0,
    seconds    REAL    NOT NULL DEFAULT 0,
    xp         INTEGER NOT NULL DEFAULT 0,
    frozen     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS milestone (
    id         TEXT PRIMARY KEY,
    reached_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS xp_event (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    day    TEXT NOT NULL,
    domain TEXT,
    kind   TEXT NOT NULL,
    amount INTEGER NOT NULL,
    at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_domain ON xp_event(domain);

CREATE TABLE IF NOT EXISTS proof_draft (
    course_id   TEXT NOT NULL,
    proof_id    TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    reviews     INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, proof_id)
);

CREATE TABLE IF NOT EXISTS chat_thread (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   TEXT,
    context_key TEXT,
    session_id  TEXT,
    title       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_message (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON chat_message(thread_id);

-- Assistant : cartes d'action proposees avec un message, et leur etat
-- (proposed, validated, waiting, running, done, failed, ignored). Les cartes
-- sont reconstruites depuis cette table a chaque rendu de la conversation.
CREATE TABLE IF NOT EXISTS chat_action (
    id         TEXT PRIMARY KEY,
    thread_id  INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    data       TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'proposed',
    note       TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_thread ON chat_action(thread_id);

-- Position de lecture : une par cours. Section (ancre et titre) et decalage
-- relatif dans la section, plutot qu'un defilement en pixels qui varie avec la
-- largeur de la fenetre, le rendu des formules ou le zoom.
CREATE TABLE IF NOT EXISTS reading_position (
    course_id     TEXT PRIMARY KEY,
    section_id    TEXT NOT NULL DEFAULT '',
    section_title TEXT NOT NULL DEFAULT '',
    section_index INTEGER NOT NULL DEFAULT 0,
    section_offset REAL NOT NULL DEFAULT 0,
    fraction     REAL NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL
);

-- Tentative de QCM en cours : un etat par serie, ecrit a chaque reponse.
CREATE TABLE IF NOT EXISTS quiz_progress (
    key        TEXT PRIMARY KEY,
    course_id  TEXT NOT NULL DEFAULT '',
    set_id     TEXT NOT NULL DEFAULT '',
    state      TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quiz_progress_course ON quiz_progress(course_id);

-- TD d'entrainement : suivi de chaque exercice (ok, partial, review).
CREATE TABLE IF NOT EXISTS training_state (
    course_id   TEXT NOT NULL,
    td_id       TEXT NOT NULL,
    exercise_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, td_id, exercise_id)
);
"""


def conn() -> sqlite3.Connection:
    """Connexion propre au thread courant (sqlite n'aime pas le partage)."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(db_file()), timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        _migrate(c)
        c.commit()
        _local.conn = c
    return c


def _migrate(c: sqlite3.Connection) -> None:
    """Ajoute les colonnes apparues apres coup, sans toucher aux donnees."""
    existing = {r["name"] for r in c.execute("PRAGMA table_info(question_result)")}
    for name, decl in (("due_at", "REAL"), ("interval_days", "REAL"), ("ease", "REAL")):
        if name not in existing:
            c.execute("ALTER TABLE question_result ADD COLUMN %s %s" % (name, decl))


# --------------------------------------------------------------------- cours
def mark_generated(course_id: str, model: str, cost: float, duration: float) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, generated_at, model, cost_usd, duration_s)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(course_id) DO UPDATE SET
             generated_at=excluded.generated_at, model=excluded.model,
             cost_usd=COALESCE(course_state.cost_usd,0)+excluded.cost_usd,
             duration_s=excluded.duration_s""",
        (course_id, time.time(), model, cost, duration),
    )
    c.commit()


def mark_opened(course_id: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, opened_at, open_count) VALUES (?, ?, 1)
           ON CONFLICT(course_id) DO UPDATE SET
             opened_at=excluded.opened_at, open_count=course_state.open_count+1""",
        (course_id, time.time()),
    )
    c.commit()


def set_notes(course_id: str, notes: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, notes) VALUES (?, ?)
           ON CONFLICT(course_id) DO UPDATE SET notes=excluded.notes""",
        (course_id, notes),
    )
    c.commit()


def get_notes(course_id: str) -> str:
    row = conn().execute(
        "SELECT notes FROM course_state WHERE course_id=?", (course_id,)
    ).fetchone()
    return (row["notes"] if row else "") or ""


# --------------------------------------------------------- position de lecture
# Au-dela de cette part du cours, la lecture est consideree comme terminee.
READING_DONE = 0.95
# En deca, on est encore au tout debut : rien a reprendre.
READING_START = 0.03


def save_reading_position(course_id: str, section_id: str, section_title: str,
                          section_index: int, offset: float, fraction: float) -> None:
    c = conn()
    c.execute(
        """INSERT INTO reading_position
             (course_id, section_id, section_title, section_index, section_offset,
              fraction, updated_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(course_id) DO UPDATE SET
             section_id=excluded.section_id, section_title=excluded.section_title,
             section_index=excluded.section_index, section_offset=excluded.section_offset,
             fraction=excluded.fraction, updated_at=excluded.updated_at""",
        (course_id, section_id or "", section_title or "", int(section_index or 0),
         max(0.0, min(1.0, float(offset or 0))), max(0.0, min(1.0, float(fraction or 0))),
         time.time()),
    )
    c.commit()


def reading_position(course_id: str) -> Optional[dict]:
    row = conn().execute("SELECT * FROM reading_position WHERE course_id=?",
                         (course_id,)).fetchone()
    return dict(row) if row else None


def resumable(position: Optional[dict]) -> bool:
    """Une position vaut un « Reprendre » : ni tout debut, ni fin du cours."""
    if not position or not position.get("section_title"):
        return False
    fraction = float(position.get("fraction") or 0)
    if fraction >= READING_DONE:
        return False
    return fraction >= READING_START or int(position.get("section_index") or 0) > 0


def last_reading() -> Optional[dict]:
    """La position du dernier cours consulte."""
    row = conn().execute(
        "SELECT * FROM reading_position ORDER BY updated_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def clear_reading_position(course_id: str) -> None:
    c = conn()
    c.execute("DELETE FROM reading_position WHERE course_id=?", (course_id,))
    c.commit()


# ---------------------------------------------------------------------- QCM
def record_attempt(course_id: str, total: int, correct: int, detail: dict,
                   set_id: str = "1", partial: bool = False) -> int:
    """Enregistre une tentative, et le resultat de chaque question.

    `partial` signale une session portant sur une selection de questions : elle
    met a jour le suivi par question, mais ne compte pas comme un score du
    cours, sans quoi refaire trois questions ratees ferait chuter la moyenne.
    """
    c = conn()
    now = time.time()
    from . import review as review_mod
    for answer in detail.get("answers") or []:
        if not isinstance(answer, dict) or not answer.get("id"):
            continue
        ok = 1 if answer.get("ok") else 0
        qid = str(answer["id"])
        previous = c.execute(
            "SELECT interval_days, ease FROM question_result "
            "WHERE course_id=? AND set_id=? AND question_id=?",
            (course_id, str(set_id), qid)).fetchone()
        interval, ease, due_at = review_mod.schedule(
            bool(ok),
            previous["interval_days"] if previous else None,
            previous["ease"] if previous else None,
            now)
        c.execute(
            """INSERT INTO question_result
                 (course_id, set_id, question_id, last_ok, tries, ok_count,
                  updated_at, due_at, interval_days, ease)
               VALUES (?,?,?,?,1,?,?,?,?,?)
               ON CONFLICT(course_id, set_id, question_id) DO UPDATE SET
                 last_ok=excluded.last_ok,
                 tries=question_result.tries+1,
                 ok_count=question_result.ok_count+excluded.ok_count,
                 updated_at=excluded.updated_at,
                 due_at=excluded.due_at,
                 interval_days=excluded.interval_days,
                 ease=excluded.ease""",
            (course_id, str(set_id), qid, ok, ok, now, due_at, interval, ease),
        )
    cur = None
    if not partial:
        cur = c.execute(
            "INSERT INTO quiz_attempt (course_id, finished_at, total, correct, detail) "
            "VALUES (?,?,?,?,?)",
            (course_id, now, total, correct, json.dumps(detail, ensure_ascii=False)),
        )
    c.commit()
    return int(cur.lastrowid) if cur is not None else 0


# Tentative en cours : ecrite a chaque reponse validee, effacee a la fin. Les
# reponses ne comptent (maitrise, revisions espacees) qu'une fois, a la fin de
# la tentative, reprise ou non : l'etat enregistre n'est qu'un brouillon.
def course_progress_key(course_id: str, set_id: str) -> str:
    return "course:%s:%s" % (course_id, set_id)


def save_quiz_progress(key: str, state: dict, course_id: str = "", set_id: str = "") -> None:
    c = conn()
    c.execute(
        """INSERT INTO quiz_progress (key, course_id, set_id, state, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET
             course_id=excluded.course_id, set_id=excluded.set_id,
             state=excluded.state, updated_at=excluded.updated_at""",
        (key, course_id or "", str(set_id or ""), json.dumps(state, ensure_ascii=False),
         time.time()),
    )
    c.commit()


def quiz_progress(key: str) -> Optional[dict]:
    row = conn().execute("SELECT state FROM quiz_progress WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    try:
        state = json.loads(row["state"] or "{}")
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def course_quiz_progress(course_id: str) -> Dict[str, dict]:
    """{set_id: etat} des tentatives en cours sur les series d'un cours."""
    out: Dict[str, dict] = {}
    for r in conn().execute(
            "SELECT key, set_id FROM quiz_progress WHERE course_id=? AND key LIKE 'course:%'",
            (course_id,)):
        state = quiz_progress(r["key"])
        if state:
            out[r["set_id"]] = state
    return out


def clear_quiz_progress(key: str) -> None:
    c = conn()
    c.execute("DELETE FROM quiz_progress WHERE key=?", (key,))
    c.commit()


def backfill_question_results() -> int:
    """Reconstruit le suivi par question a partir des tentatives passees.

    Le suivi par question n'existe que depuis peu : sans ce rattrapage, les
    cours deja evalues repartiraient d'un score vide.
    """
    c = conn()
    done = c.execute("SELECT COUNT(*) n FROM question_result").fetchone()["n"]
    already = {r["course_id"] for r in c.execute(
        "SELECT DISTINCT course_id FROM question_result")} if done else set()
    added = 0
    for row in c.execute("SELECT course_id, finished_at, detail FROM quiz_attempt "
                         "ORDER BY finished_at"):
        if row["course_id"] in already:
            continue
        try:
            detail = json.loads(row["detail"] or "{}")
        except json.JSONDecodeError:
            continue
        for answer in detail.get("answers") or []:
            if not isinstance(answer, dict) or not answer.get("id"):
                continue
            ok = 1 if answer.get("ok") else 0
            c.execute(
                """INSERT INTO question_result
                     (course_id, set_id, question_id, last_ok, tries, ok_count, updated_at)
                   VALUES (?,'1',?,?,1,?,?)
                   ON CONFLICT(course_id, set_id, question_id) DO UPDATE SET
                     last_ok=excluded.last_ok,
                     tries=question_result.tries+1,
                     ok_count=question_result.ok_count+excluded.ok_count,
                     updated_at=excluded.updated_at""",
                (row["course_id"], str(answer["id"]), ok, ok, row["finished_at"]),
            )
            added += 1
    # Les lignes reconstruites n'ont pas d'echeance : sans cela, rien ne serait
    # jamais a revoir. On en deduit une a partir du nombre de reussites.
    from . import review as review_mod
    scheduled = 0
    for row in c.execute(
            "SELECT course_id, set_id, question_id, last_ok, ok_count, updated_at "
            "FROM question_result WHERE due_at IS NULL"):
        if row["last_ok"]:
            successes = max(1, int(row["ok_count"]))
            interval = {1: 1.0, 2: 3.0}.get(successes, 7.0)
            ease = review_mod.EASE_START
        else:
            interval, ease = 0.0, review_mod.EASE_START - 0.25
        c.execute("UPDATE question_result SET due_at=?, interval_days=?, ease=? "
                  "WHERE course_id=? AND set_id=? AND question_id=?",
                  (row["updated_at"] + interval * review_mod.DAY, interval, ease,
                   row["course_id"], row["set_id"], row["question_id"]))
        scheduled += 1
    if added or scheduled:
        c.commit()
    return added


def question_history(course_id: str) -> Dict[str, Dict[str, dict]]:
    """{set_id: {question_id: {ok, tries, ok_count}}}"""
    out: Dict[str, Dict[str, dict]] = {}
    for r in conn().execute(
            "SELECT set_id, question_id, last_ok, tries, ok_count "
            "FROM question_result WHERE course_id=?", (course_id,)):
        out.setdefault(r["set_id"], {})[r["question_id"]] = {
            "ok": bool(r["last_ok"]), "tries": r["tries"], "okCount": r["ok_count"]}
    return out


def reset_question_history(course_id: str, set_id: Optional[str] = None) -> None:
    c = conn()
    if set_id is None:
        c.execute("DELETE FROM question_result WHERE course_id=?", (course_id,))
    else:
        c.execute("DELETE FROM question_result WHERE course_id=? AND set_id=?",
                  (course_id, str(set_id)))
    c.commit()


def attempts(course_id: str) -> List[sqlite3.Row]:
    return list(conn().execute(
        "SELECT * FROM quiz_attempt WHERE course_id=? ORDER BY finished_at DESC", (course_id,)
    ))


# -------------------------------------------------------------------- demos
def set_proof_status(course_id: str, proof_id: str, status: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO proof_state (course_id, proof_id, status, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             status=excluded.status, updated_at=excluded.updated_at""",
        (course_id, proof_id, status, time.time()),
    )
    c.commit()


def set_proof_draft(course_id: str, proof_id: str, text: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO proof_draft (course_id, proof_id, text, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             text=excluded.text, updated_at=excluded.updated_at""",
        (course_id, proof_id, text, time.time()),
    )
    c.commit()


def count_review(course_id: str, proof_id: str) -> int:
    """Incremente et retourne le nombre de corrections demandees."""
    c = conn()
    c.execute(
        """INSERT INTO proof_draft (course_id, proof_id, reviews, updated_at)
           VALUES (?,?,1,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             reviews=proof_draft.reviews+1, updated_at=excluded.updated_at""",
        (course_id, proof_id, time.time()),
    )
    c.commit()
    row = c.execute("SELECT reviews FROM proof_draft WHERE course_id=? AND proof_id=?",
                    (course_id, proof_id)).fetchone()
    return int(row["reviews"]) if row else 1


def proof_drafts(course_id: str) -> Dict[str, str]:
    rows = conn().execute(
        "SELECT proof_id, text FROM proof_draft WHERE course_id=?", (course_id,))
    return {r["proof_id"]: r["text"] for r in rows}


def proof_statuses(course_id: str) -> Dict[str, str]:
    rows = conn().execute(
        "SELECT proof_id, status FROM proof_state WHERE course_id=?", (course_id,)
    )
    return {r["proof_id"]: r["status"] for r in rows}


# ------------------------------------------------------- TD d'entrainement
TRAINING_STATUSES = ("ok", "partial", "review")


def set_training_status(course_id: str, td_id: str, exercise_id: str, status: str) -> None:
    """Réussi (ok), partiellement (partial), à revoir (review) ; vide pour effacer.

    Sans effet sur la maîtrise du cours, qui reste fondée sur les QCM."""
    c = conn()
    if status not in TRAINING_STATUSES:
        c.execute("DELETE FROM training_state WHERE course_id=? AND td_id=? AND exercise_id=?",
                  (course_id, str(td_id), exercise_id))
    else:
        c.execute(
            """INSERT INTO training_state (course_id, td_id, exercise_id, status, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(course_id, td_id, exercise_id) DO UPDATE SET
                 status=excluded.status, updated_at=excluded.updated_at""",
            (course_id, str(td_id), exercise_id, status, time.time()))
    c.commit()


def training_statuses(course_id: str) -> Dict[str, str]:
    """{"<td>/<exercice>": statut} pour un cours."""
    rows = conn().execute(
        "SELECT td_id, exercise_id, status FROM training_state WHERE course_id=?", (course_id,))
    return {"%s/%s" % (r["td_id"], r["exercise_id"]): r["status"] for r in rows}


def clear_training_status(course_id: str, td_id: str) -> None:
    c = conn()
    c.execute("DELETE FROM training_state WHERE course_id=? AND td_id=?", (course_id, str(td_id)))
    c.commit()


# ------------------------------------------------------------------- resume
@dataclass
class Progress:
    course_id: str
    generated: bool = False
    opened: bool = False
    attempts: int = 0
    best_pct: Optional[int] = None
    last_pct: Optional[int] = None
    answered: int = 0
    correct: int = 0
    answered_ids: frozenset = frozenset()
    correct_ids: frozenset = frozenset()
    proofs_done: int = 0
    proofs_total: int = 0

    @property
    def current_pct(self) -> Optional[int]:
        """Part des questions actuellement justes parmi celles deja tentees."""
        if not self.answered:
            return None
        return int(round(100.0 * self.correct / self.answered))


def progress_map() -> Dict[str, Progress]:
    c = conn()
    out: Dict[str, Progress] = {}
    for r in c.execute("SELECT * FROM course_state"):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.generated = r["generated_at"] is not None
        p.opened = (r["open_count"] or 0) > 0
    for r in c.execute(
        """SELECT course_id, COUNT(*) n,
                  MAX(CAST(correct AS REAL)/NULLIF(total,0)) best
           FROM quiz_attempt GROUP BY course_id"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.attempts = r["n"]
        p.best_pct = int(round((r["best"] or 0) * 100))
    for r in c.execute(
        """SELECT course_id, correct, total FROM quiz_attempt a
           WHERE finished_at = (SELECT MAX(finished_at) FROM quiz_attempt b
                                WHERE b.course_id = a.course_id)"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        if r["total"]:
            p.last_pct = int(round(100.0 * r["correct"] / r["total"]))
    # Etat courant de chaque question : c'est lui qui donne le score du cours.
    # Le meilleur `quiz_attempt` ne bougeait pas quand on refaisait uniquement
    # les questions ratees, alors que c'est precisement la qu'on progresse.
    answered: Dict[str, set] = {}
    correct: Dict[str, set] = {}
    for r in c.execute(
        "SELECT course_id, question_id, last_ok FROM question_result"
    ):
        answered.setdefault(r["course_id"], set()).add(r["question_id"])
        if r["last_ok"]:
            correct.setdefault(r["course_id"], set()).add(r["question_id"])
    for course_id, ids in answered.items():
        p = out.setdefault(course_id, Progress(course_id))
        p.answered_ids = frozenset(ids)
        p.correct_ids = frozenset(correct.get(course_id, set()))
        p.answered = len(ids)
        p.correct = len(p.correct_ids)

    for r in c.execute(
        """SELECT course_id, SUM(status='done') done, COUNT(*) total
           FROM proof_state GROUP BY course_id"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.proofs_done = r["done"] or 0
        p.proofs_total = r["total"] or 0
    return out


# --------------------------------------------------------------------- chat
def create_thread(course_id: Optional[str], context_key: str, title: str) -> int:
    c = conn()
    now = time.time()
    cur = c.execute(
        "INSERT INTO chat_thread (course_id, context_key, title, created_at, updated_at) VALUES (?,?,?,?,?)",
        (course_id, context_key, title, now, now),
    )
    c.commit()
    return int(cur.lastrowid)


def find_thread(course_id: Optional[str], context_key: str) -> Optional[sqlite3.Row]:
    c = conn()
    if course_id is None:
        return c.execute(
            "SELECT * FROM chat_thread WHERE course_id IS NULL AND context_key=? ORDER BY updated_at DESC LIMIT 1",
            (context_key,),
        ).fetchone()
    return c.execute(
        "SELECT * FROM chat_thread WHERE course_id=? AND context_key=? ORDER BY updated_at DESC LIMIT 1",
        (course_id, context_key),
    ).fetchone()


def set_thread_session(thread_id: int, session_id: str) -> None:
    c = conn()
    c.execute("UPDATE chat_thread SET session_id=?, updated_at=? WHERE id=?",
              (session_id, time.time(), thread_id))
    c.commit()


def add_message(thread_id: int, role: str, content: str) -> int:
    c = conn()
    cur = c.execute("INSERT INTO chat_message (thread_id, role, content, created_at) VALUES (?,?,?,?)",
                    (thread_id, role, content, time.time()))
    c.execute("UPDATE chat_thread SET updated_at=? WHERE id=?", (time.time(), thread_id))
    c.commit()
    return int(cur.lastrowid)


def add_chat_actions(thread_id: int, message_id: int, actions: list) -> None:
    """Enregistre les cartes d'action d'un message, toutes « proposées »."""
    c = conn()
    now = time.time()
    for pos, action in enumerate(actions):
        c.execute("INSERT OR REPLACE INTO chat_action (id, thread_id, message_id, position, "
                  "data, state, note, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (action["id"], thread_id, message_id, pos,
                   json.dumps(action, ensure_ascii=False), "proposed", "", now))
    c.commit()


def set_chat_action_state(action_id: str, state: str, note: str = "") -> None:
    c = conn()
    c.execute("UPDATE chat_action SET state=?, note=?, updated_at=? WHERE id=?",
              (state, note, time.time(), action_id))
    c.commit()


def chat_action(action_id: str) -> Optional[dict]:
    """Une carte : l'action (dict) avec son état (`state`) et sa note (`note`)."""
    r = conn().execute("SELECT * FROM chat_action WHERE id=?", (action_id,)).fetchone()
    if r is None:
        return None
    return dict(json.loads(r["data"]), state=r["state"], note=r["note"])


def chat_actions(thread_id: int) -> Dict[int, list]:
    """Cartes d'un fil, regroupées par message, dans l'ordre de proposition."""
    out: Dict[int, list] = {}
    for r in conn().execute("SELECT * FROM chat_action WHERE thread_id=? "
                            "ORDER BY message_id, position", (thread_id,)):
        try:
            data = json.loads(r["data"])
        except (TypeError, ValueError):
            continue
        out.setdefault(int(r["message_id"]), []).append(
            dict(data, state=r["state"], note=r["note"]))
    return out


def messages(thread_id: int) -> List[sqlite3.Row]:
    return list(conn().execute(
        "SELECT * FROM chat_message WHERE thread_id=? ORDER BY id", (thread_id,)))


def clear_thread(thread_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM chat_message WHERE thread_id=?", (thread_id,))
    c.execute("DELETE FROM chat_action WHERE thread_id=?", (thread_id,))
    c.execute("UPDATE chat_thread SET session_id=NULL WHERE id=?", (thread_id,))
    c.commit()


# ------------------------------------------------------------ questions libres
def question_threads(prefix: str) -> List[sqlite3.Row]:
    """Fils dont la cle commence par `prefix` et qui ont au moins un message."""
    return list(conn().execute(
        "SELECT t.*, COUNT(m.id) AS n FROM chat_thread t "
        "JOIN chat_message m ON m.thread_id = t.id "
        "WHERE t.context_key LIKE ? GROUP BY t.id ORDER BY t.updated_at DESC",
        (prefix + "%",)))


def set_thread_title(thread_id: int, title: str) -> None:
    c = conn()
    c.execute("UPDATE chat_thread SET title=? WHERE id=?", (title, thread_id))
    c.commit()


def delete_thread(thread_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM chat_message WHERE thread_id=?", (thread_id,))
    c.execute("DELETE FROM chat_action WHERE thread_id=?", (thread_id,))
    c.execute("DELETE FROM chat_thread WHERE id=?", (thread_id,))
    c.commit()


def delete_empty_threads(prefix: str, keep: Optional[int] = None) -> None:
    c = conn()
    c.execute("DELETE FROM chat_thread WHERE context_key LIKE ? AND id != ? AND NOT EXISTS "
              "(SELECT 1 FROM chat_message m WHERE m.thread_id = chat_thread.id)",
              (prefix + "%", keep if keep is not None else -1))
    c.commit()
