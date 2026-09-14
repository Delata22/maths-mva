"""Objectif du jour, série, XP, niveaux et jalons.

Le principe : ce qui compte, c'est d'avoir travaillé, pas d'avoir passé du
temps devant l'écran. L'objectif quotidien est donc exprimé en « briques » —
une séance de QCM, une révision terminée, une démonstration soumise ou
réussie — et il est atteint dès la première.

La série tolère deux jours manqués par mois : une série fragile fait
abandonner, alors qu'elle est censée soutenir.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import settings, store

FREEZES_PER_MONTH = 2

# Ce qui vaut une brique, et ce que ça rapporte.
XP = {
    "question": 4,            # + 3 par niveau de difficulté au-dessus de 1
    "question_wrong": 1,      # chercher compte, même quand on se trompe
    "exercice_bonus": 1.5,    # facteur, pour les questions de type exercice
    "review_done": 15,
    "proof_review": 8,
    "proof_solved": 40,
    "course_mastered": 150,
    "goal_met": 25,
    "challenge_perfect": 30,
    "daily_quiz": 20,
    "refresher": 12,
}


def today() -> str:
    return dt.date.today().isoformat()


def day_of(ts: float) -> str:
    return dt.date.fromtimestamp(ts).isoformat()


# ----------------------------------------------------------------- journal
def _touch(day: str) -> None:
    store.conn().execute("INSERT OR IGNORE INTO day_log (day) VALUES (?)", (day,))


def log(kind: str, *, questions: int = 0, correct: int = 0, proofs: int = 0,
        reviews: int = 0, seconds: float = 0.0, brick: bool = False,
        xp: int = 0, domain: Optional[str] = None,
        day: Optional[str] = None) -> None:
    """Enregistre une unité de travail et l'XP correspondante."""
    day = day or today()
    c = store.conn()
    _touch(day)
    c.execute(
        "UPDATE day_log SET questions=questions+?, correct=correct+?, "
        "proofs=proofs+?, reviews=reviews+?, seconds=seconds+?, "
        "bricks=bricks+?, xp=xp+? WHERE day=?",
        (questions, correct, proofs, reviews, seconds, 1 if brick else 0, xp, day))
    if xp:
        c.execute("INSERT INTO xp_event (day, domain, kind, amount, at) VALUES (?,?,?,?,?)",
                  (day, domain, kind, xp, time.time()))
    c.commit()


def question_xp(difficulty: int, ok: bool, kind: str = "direct") -> int:
    if not ok:
        return XP["question_wrong"]
    amount = XP["question"] + 3 * (max(1, min(5, int(difficulty))) - 1)
    if kind == "exercice":
        amount = int(round(amount * XP["exercice_bonus"]))
    return amount


def day_row(day: Optional[str] = None) -> dict:
    day = day or today()
    row = store.conn().execute("SELECT * FROM day_log WHERE day=?", (day,)).fetchone()
    if row is None:
        return {"day": day, "bricks": 0, "questions": 0, "correct": 0, "proofs": 0,
                "reviews": 0, "seconds": 0.0, "xp": 0, "frozen": 0}
    return dict(row)


def days_between(first: str, last: str) -> List[str]:
    a = dt.date.fromisoformat(first)
    b = dt.date.fromisoformat(last)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def history(days: int = 120) -> Dict[str, dict]:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    return {r["day"]: dict(r) for r in store.conn().execute(
        "SELECT * FROM day_log WHERE day >= ? ORDER BY day", (since,))}


# -------------------------------------------------------------- objectif
def goal_target() -> int:
    return max(1, int(settings.get("goal/bricks") or 1))


@dataclass
class Goal:
    done: int = 0
    target: int = 1
    questions: int = 0
    correct: int = 0
    reviews: int = 0
    proofs: int = 0
    xp: int = 0

    @property
    def met(self) -> bool:
        return self.done >= self.target

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / max(1, self.target))


def goal_state(day: Optional[str] = None) -> Goal:
    row = day_row(day)
    return Goal(done=row["bricks"], target=goal_target(), questions=row["questions"],
                correct=row["correct"], reviews=row["reviews"], proofs=row["proofs"],
                xp=row["xp"])


# ----------------------------------------------------------------- serie
@dataclass
class Streak:
    current: int = 0
    best: int = 0
    freezes_left: int = FREEZES_PER_MONTH
    today_done: bool = False
    days: Dict[str, dict] = field(default_factory=dict)


def _freezes_used(month: str) -> int:
    row = store.conn().execute(
        "SELECT COUNT(*) n FROM day_log WHERE frozen=1 AND day LIKE ?",
        (month + "-%",)).fetchone()
    return int(row["n"]) if row else 0


def refresh_streak() -> Streak:
    """Calcule la série, en consommant un gel pour un jour manqué isolé.

    Le gel est persiste : une fois pose, il ne bouge plus, sinon la serie
    changerait selon le moment ou on la regarde.
    """
    c = store.conn()
    rows = {r["day"]: dict(r) for r in c.execute("SELECT * FROM day_log ORDER BY day")}
    now = dt.date.today()
    month = now.strftime("%Y-%m")
    freezes_left = max(0, FREEZES_PER_MONTH - _freezes_used(month))

    def worked(day: str) -> bool:
        row = rows.get(day)
        return bool(row and (row["bricks"] > 0 or row["frozen"]))

    # serie courante : on remonte depuis aujourd'hui (ou hier si rien fait)
    current = 0
    cursor = now
    if not worked(now.isoformat()):
        cursor = now - dt.timedelta(days=1)
    consumed = 0
    while True:
        day = cursor.isoformat()
        if worked(day):
            current += 1
            cursor -= dt.timedelta(days=1)
            continue
        # Un gel couvre un oubli des deux derniers jours, pas un trou ancien :
        # il protege une serie qu'on entretient, il ne fabrique pas un passe.
        recent = (now - cursor).days <= 2
        if day != now.isoformat() and freezes_left - consumed > 0 and current > 0 \
                and recent and day.startswith(month):
            c.execute("INSERT OR IGNORE INTO day_log (day) VALUES (?)", (day,))
            c.execute("UPDATE day_log SET frozen=1 WHERE day=?", (day,))
            rows.setdefault(day, {"bricks": 0, "frozen": 1})["frozen"] = 1
            consumed += 1
            current += 1
            cursor -= dt.timedelta(days=1)
            continue
        break
    if consumed:
        c.commit()

    # meilleure serie, sur tout l'historique
    best, run, previous = 0, 0, None
    for day in sorted(rows):
        if not worked(day):
            continue
        if previous is not None and (dt.date.fromisoformat(day)
                                     - dt.date.fromisoformat(previous)).days == 1:
            run += 1
        else:
            run = 1
        previous = day
        best = max(best, run)

    return Streak(current=current, best=max(best, current),
                  freezes_left=max(0, freezes_left - consumed),
                  today_done=worked(now.isoformat()),
                  days=rows)


# ------------------------------------------------------------ XP et niveaux
def level_of(xp: int) -> tuple:
    """(niveau, XP dans le niveau, XP nécessaire pour le suivant)."""
    level, need, spent = 1, 100, 0
    while xp - spent >= need:
        spent += need
        level += 1
        need = 100 + 70 * (level - 1)
    return level, xp - spent, need


def xp_total() -> int:
    row = store.conn().execute("SELECT COALESCE(SUM(amount),0) n FROM xp_event").fetchone()
    return int(row["n"])


def xp_by_domain() -> Dict[str, int]:
    return {r["domain"]: int(r["n"]) for r in store.conn().execute(
        "SELECT domain, SUM(amount) n FROM xp_event WHERE domain IS NOT NULL "
        "GROUP BY domain")}


def xp_last_days(days: int = 7) -> int:
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    row = store.conn().execute(
        "SELECT COALESCE(SUM(amount),0) n FROM xp_event WHERE day >= ?", (since,)).fetchone()
    return int(row["n"])


# ------------------------------------------------------------------ jalons
@dataclass
class Milestone:
    id: str
    label: str
    detail: str
    reach: Callable[[dict], bool]
    progress: Optional[Callable[[dict], tuple]] = None


def _count_mastered(ctx: dict) -> int:
    return sum(1 for s in ctx["statuses"].values() if s.mastered)


def _complete_domains(ctx: dict) -> int:
    syl = ctx["syl"]
    n = 0
    for did in syl.domain_order:
        ids = [c.id for c in syl.by_domain(did)]
        if ids and all(ctx["statuses"][c].mastered for c in ids):
            n += 1
    return n


def _best_track_fraction(ctx: dict) -> float:
    syl = ctx["syl"]
    best = 0.0
    for tid in syl.tracks:
        path = syl.track_path(tid)
        if not path:
            continue
        done = sum(1 for c in path if ctx["statuses"][c].mastered)
        best = max(best, done / len(path))
    return best


MILESTONES: List[Milestone] = [
    Milestone("course-1", "Premier cours maîtrisé",
              "Un cours dont le QCM dépasse le seuil.",
              lambda c: _count_mastered(c) >= 1,
              lambda c: (_count_mastered(c), 1)),
    Milestone("course-5", "Cinq cours maîtrisés", "",
              lambda c: _count_mastered(c) >= 5,
              lambda c: (_count_mastered(c), 5)),
    Milestone("course-10", "Dix cours maîtrisés", "",
              lambda c: _count_mastered(c) >= 10,
              lambda c: (_count_mastered(c), 10)),
    Milestone("course-25", "Vingt-cinq cours maîtrisés", "",
              lambda c: _count_mastered(c) >= 25,
              lambda c: (_count_mastered(c), 25)),
    Milestone("course-50", "Cinquante cours maîtrisés", "",
              lambda c: _count_mastered(c) >= 50,
              lambda c: (_count_mastered(c), 50)),
    Milestone("domain-1", "Un domaine complet",
              "Tous les cours d'un domaine maîtrisés.",
              lambda c: _complete_domains(c) >= 1,
              lambda c: (_complete_domains(c), 1)),
    Milestone("domain-3", "Trois domaines complets", "",
              lambda c: _complete_domains(c) >= 3,
              lambda c: (_complete_domains(c), 3)),
    Milestone("track-half", "Un parcours à moitié",
              "La moitié des cours d'un parcours MVA.",
              lambda c: _best_track_fraction(c) >= 0.5,
              lambda c: (int(round(100 * _best_track_fraction(c))), 50)),
    Milestone("track-done", "Un parcours entier",
              "Tous les cours d'un parcours, du début à la fin.",
              lambda c: _best_track_fraction(c) >= 1.0,
              lambda c: (int(round(100 * _best_track_fraction(c))), 100)),
    Milestone("proof-1", "Première démonstration réussie", "",
              lambda c: c["proofs_done"] >= 1,
              lambda c: (c["proofs_done"], 1)),
    Milestone("proof-10", "Dix démonstrations réussies", "",
              lambda c: c["proofs_done"] >= 10,
              lambda c: (c["proofs_done"], 10)),
    Milestone("proof-25", "Vingt-cinq démonstrations réussies", "",
              lambda c: c["proofs_done"] >= 25,
              lambda c: (c["proofs_done"], 25)),
    Milestone("q-100", "Cent questions justes", "",
              lambda c: c["correct_total"] >= 100,
              lambda c: (c["correct_total"], 100)),
    Milestone("q-500", "Cinq cents questions justes", "",
              lambda c: c["correct_total"] >= 500,
              lambda c: (c["correct_total"], 500)),
    Milestone("q-2000", "Deux mille questions justes", "",
              lambda c: c["correct_total"] >= 2000,
              lambda c: (c["correct_total"], 2000)),
    Milestone("perfect", "Une série sans faute",
              "Toutes les questions d'une série justes.",
              lambda c: c["perfect_sets"] >= 1,
              lambda c: (c["perfect_sets"], 1)),
    Milestone("streak-3", "Trois jours d'affilée", "",
              lambda c: c["streak"].best >= 3,
              lambda c: (c["streak"].best, 3)),
    Milestone("streak-7", "Une semaine d'affilée", "",
              lambda c: c["streak"].best >= 7,
              lambda c: (c["streak"].best, 7)),
    Milestone("streak-30", "Un mois d'affilée", "",
              lambda c: c["streak"].best >= 30,
              lambda c: (c["streak"].best, 30)),
    Milestone("review-100", "Cent révisions", "",
              lambda c: c["reviews_total"] >= 100,
              lambda c: (c["reviews_total"], 100)),
    Milestone("level-5", "Niveau 5", "",
              lambda c: c["level"] >= 5, lambda c: (c["level"], 5)),
    Milestone("level-10", "Niveau 10", "",
              lambda c: c["level"] >= 10, lambda c: (c["level"], 10)),
    Milestone("exercice-10", "Dix exercices résolus",
              "Dix questions de type exercice réussies.",
              lambda c: c["exercices_done"] >= 10,
              lambda c: (c["exercices_done"], 10)),
    Milestone("sheet-5", "Cinq fiches de révision", "",
              lambda c: c["sheets"] >= 5, lambda c: (c["sheets"], 5)),
]


def build_context(syl, statuses) -> dict:
    from . import content
    c = store.conn()
    correct_total = int(c.execute(
        "SELECT COALESCE(SUM(ok_count),0) n FROM question_result").fetchone()["n"])
    reviews_total = int(c.execute(
        "SELECT COALESCE(SUM(reviews),0) n FROM day_log").fetchone()["n"])
    proofs_done = int(c.execute(
        "SELECT COUNT(*) n FROM proof_state WHERE status='done'").fetchone()["n"])

    perfect = 0
    exercices_done = 0
    sheets = 0
    for course in syl.all():
        st = statuses[course.id]
        if content.has_sheet(course.id):
            sheets += 1
        if not st.has_exercises:
            continue
        history = store.question_history(course.id)
        for item in content.quiz_sets(course.id):
            marks = history.get(item["id"], {})
            ids = [q["id"] for q in item["qcm"]]
            if ids and all(marks.get(q, {}).get("ok") for q in ids):
                perfect += 1
            for q in item["qcm"]:
                if q.get("kind") == "exercice" and marks.get(q["id"], {}).get("ok"):
                    exercices_done += 1

    total_xp = xp_total()
    level, _into, _need = level_of(total_xp)
    return {
        "syl": syl, "statuses": statuses,
        "correct_total": correct_total, "reviews_total": reviews_total,
        "proofs_done": proofs_done, "perfect_sets": perfect,
        "exercices_done": exercices_done, "sheets": sheets,
        "streak": refresh_streak(), "level": level, "xp": total_xp,
    }


def reached_ids() -> Dict[str, float]:
    return {r["id"]: r["reached_at"] for r in store.conn().execute(
        "SELECT id, reached_at FROM milestone")}


def check_milestones(ctx: dict) -> List[Milestone]:
    """Marque les jalons atteints et retourne les nouveaux."""
    already = reached_ids()
    fresh: List[Milestone] = []
    c = store.conn()
    now = time.time()
    for milestone in MILESTONES:
        if milestone.id in already:
            continue
        try:
            if milestone.reach(ctx):
                c.execute("INSERT OR IGNORE INTO milestone (id, reached_at) VALUES (?,?)",
                          (milestone.id, now))
                fresh.append(milestone)
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    if fresh:
        c.commit()
    return fresh


# ------------------------------------------------------------- rattrapage
def award_course_mastery(syl, statuses) -> List[str]:
    """Accorde l'XP des cours maîtrisés qui ne l'ont pas encore reçue."""
    c = store.conn()
    already = {r["kind"].split(":", 1)[1] for r in c.execute(
        "SELECT kind FROM xp_event WHERE kind LIKE 'course_mastered:%'")}
    fresh = []
    for course in syl.all():
        if not statuses[course.id].mastered or course.id in already:
            continue
        log("course_mastered:%s" % course.id, xp=XP["course_mastered"],
            domain=course.domain)
        fresh.append(course.id)
    return fresh


def backfill(syl) -> dict:
    """Reconstruit journal et XP a partir du travail deja enregistre.

    Sans cela, on demarrerait a zero XP et sans serie alors que le travail a
    bien eu lieu : demotivant et faux.
    """
    import json as _json
    c = store.conn()
    if c.execute("SELECT COUNT(*) n FROM xp_event").fetchone()["n"]:
        return {"skipped": True}

    by_course = {course.id: course for course in syl.all()}
    added_days, added_xp = set(), 0

    for row in c.execute("SELECT course_id, finished_at, detail FROM quiz_attempt "
                         "ORDER BY finished_at"):
        try:
            detail = _json.loads(row["detail"] or "{}")
        except _json.JSONDecodeError:
            continue
        answers = [a for a in (detail.get("answers") or []) if isinstance(a, dict)]
        if not answers:
            continue
        day = day_of(row["finished_at"])
        course = by_course.get(row["course_id"])
        gained = sum(question_xp(a.get("difficulty", 1), bool(a.get("ok")),
                                 a.get("kind", "direct")) for a in answers)
        log("quiz", questions=len(answers),
            correct=sum(1 for a in answers if a.get("ok")),
            brick=True, xp=gained,
            domain=course.domain if course else None, day=day)
        added_days.add(day)
        added_xp += gained

    for row in c.execute("SELECT course_id, updated_at FROM proof_state WHERE status='done'"):
        course = by_course.get(row["course_id"])
        log("proof_solved", proofs=1, brick=True, xp=XP["proof_solved"],
            domain=course.domain if course else None, day=day_of(row["updated_at"]))
        added_days.add(day_of(row["updated_at"]))
        added_xp += XP["proof_solved"]

    return {"skipped": False, "days": len(added_days), "xp": added_xp}


# -------------------------------------------------------------- semaine
def week_bounds(offset: int = 0) -> tuple:
    """(lundi, dimanche) de la semaine courante, ou d'une semaine precedente."""
    today_date = dt.date.today()
    monday = today_date - dt.timedelta(days=today_date.weekday() + 7 * offset)
    return monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()


def week_totals(offset: int = 0) -> dict:
    first, last = week_bounds(offset)
    row = store.conn().execute(
        "SELECT COALESCE(SUM(questions),0) questions, COALESCE(SUM(correct),0) correct, "
        "COALESCE(SUM(bricks),0) bricks, COALESCE(SUM(reviews),0) reviews, "
        "COALESCE(SUM(proofs),0) proofs, COALESCE(SUM(xp),0) xp, "
        "COALESCE(SUM(seconds),0) seconds, "
        "COUNT(CASE WHEN bricks > 0 THEN 1 END) days "
        "FROM day_log WHERE day BETWEEN ? AND ?", (first, last)).fetchone()
    out = dict(row)
    out["first"], out["last"] = first, last
    out["score"] = (int(round(100.0 * out["correct"] / out["questions"]))
                    if out["questions"] else None)
    return out


def week_domains(offset: int = 0) -> Dict[str, int]:
    first, last = week_bounds(offset)
    return {r["domain"]: int(r["n"]) for r in store.conn().execute(
        "SELECT domain, SUM(amount) n FROM xp_event "
        "WHERE domain IS NOT NULL AND day BETWEEN ? AND ? GROUP BY domain",
        (first, last))}
