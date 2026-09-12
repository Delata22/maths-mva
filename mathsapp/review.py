"""Planification des révisions.

Une question juste revient de plus en plus tard ; une question ratée revient
tout de suite. C'est ce qui donne une raison non arbitraire d'ouvrir
l'application chaque jour : il y a ce qu'il faut revoir aujourd'hui, et rien
de plus.

Le calcul est un SM-2 allégé : un intervalle en jours et une facilité propres à
chaque question, tous deux mis à jour à chaque réponse.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DAY = 86400.0

EASE_START = 2.3
EASE_MIN = 1.3
EASE_MAX = 2.8
FIRST_INTERVAL = 1.0        # jours, après une première réussite
SECOND_INTERVAL = 3.0
LAPSE_INTERVAL = 0.0        # une question ratée redevient due immédiatement


def schedule(ok: bool, interval_days: Optional[float], ease: Optional[float],
             now: Optional[float] = None) -> Tuple[float, float, float]:
    """(intervalle, facilité, date de prochaine révision) après une réponse."""
    now = now if now is not None else time.time()
    ease = float(ease) if ease else EASE_START
    interval = float(interval_days) if interval_days else 0.0

    if not ok:
        # on ne repousse pas une question ratée : elle revient dans la journée
        ease = max(EASE_MIN, ease - 0.25)
        interval = LAPSE_INTERVAL
    elif interval <= 0:
        interval = FIRST_INTERVAL
    elif interval < SECOND_INTERVAL:
        interval = SECOND_INTERVAL
        ease = min(EASE_MAX, ease + 0.05)
    else:
        interval = interval * ease
        ease = min(EASE_MAX, ease + 0.05)
    return interval, ease, now + interval * DAY


@dataclass
class DueItem:
    course_id: str
    set_id: str
    question_id: str
    due_at: float
    last_ok: bool
    overdue_days: float


def due_items(now: Optional[float] = None, limit: Optional[int] = None,
              known: Optional[Dict[str, set]] = None) -> List[DueItem]:
    """Questions à revoir, les plus en retard d'abord.

    `known` permet d'ecarter les questions qui n'existent plus (exercices
    regeneres) : {course_id: {question_id}}.
    """
    from . import store
    now = now if now is not None else time.time()
    rows = store.conn().execute(
        "SELECT course_id, set_id, question_id, last_ok, due_at "
        "FROM question_result WHERE due_at IS NOT NULL AND due_at <= ? "
        "ORDER BY due_at", (now,))
    out: List[DueItem] = []
    for r in rows:
        if known is not None:
            ids = known.get(r["course_id"])
            if ids is None or r["question_id"] not in ids:
                continue
        out.append(DueItem(r["course_id"], r["set_id"], r["question_id"],
                           r["due_at"], bool(r["last_ok"]),
                           max(0.0, (now - r["due_at"]) / DAY)))
        if limit is not None and len(out) >= limit:
            break
    return out


def upcoming(days: int = 14, now: Optional[float] = None) -> List[int]:
    """Nombre de questions dues pour chacun des prochains jours."""
    from . import store
    now = now if now is not None else time.time()
    counts = [0] * days
    for r in store.conn().execute(
            "SELECT due_at FROM question_result WHERE due_at IS NOT NULL"):
        offset = int((r["due_at"] - now) // DAY)
        if 0 <= offset < days:
            counts[offset] += 1
        elif r["due_at"] <= now:
            counts[0] += 1
    return counts


def estimate_minutes(count: int) -> int:
    """Une question de révision prend une trentaine de secondes."""
    return max(1, int(round(count * 0.5)))


def due_resolved(limit: Optional[int] = None,
                 now: Optional[float] = None) -> List[tuple]:
    """[(échéance, question)] pour ce qui est dû ET encore existant.

    Le decompte affiche et la seance lancee doivent porter sur la meme liste :
    on resout donc les questions une seule fois, ici.
    """
    from . import content
    index = content.question_index()
    out = []
    for item in due_items(now=now):
        question = index.get((item.course_id, item.set_id, item.question_id))
        if question is None:
            continue
        out.append((item, question))
        if limit is not None and len(out) >= limit:
            break
    return out
