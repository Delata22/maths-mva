"""Statut d'un cours : genere ? debloque ? maitrise ?"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import content, settings, store
from .syllabus import Syllabus

LOCKED = "locked"          # des prerequis ne sont pas maitrises
AVAILABLE = "available"    # prerequis ok, mais cours pas encore genere
READY = "ready"            # cours genere, pas encore evalue
STARTED = "started"        # QCM tente, pas au niveau
MASTERED = "mastered"      # QCM reussi au-dela du seuil

LABELS = {
    LOCKED: "Verrouille",
    AVAILABLE: "Disponible",
    READY: "A etudier",
    STARTED: "En cours",
    MASTERED: "Maitrise",
}


@dataclass
class Status:
    course_id: str
    generated: bool = False
    has_exercises: bool = False
    unlocked: bool = False
    missing: List[str] = field(default_factory=list)
    best_pct: Optional[int] = None
    last_pct: Optional[int] = None
    attempts: int = 0
    proofs_done: int = 0
    proofs_total: int = 0
    state: str = LOCKED

    @property
    def mastered(self) -> bool:
        return self.state == MASTERED

    @property
    def label(self) -> str:
        return LABELS[self.state]


def threshold() -> int:
    return int(settings.get("ui/mastery_threshold") or 80)


def compute(syl: Syllabus, progress: Optional[Dict[str, store.Progress]] = None) -> Dict[str, Status]:
    progress = progress if progress is not None else store.progress_map()
    thr = threshold()
    out: Dict[str, Status] = {}

    for cid in syl.order:
        p = progress.get(cid)
        st = Status(course_id=cid)
        st.generated = content.has_course(cid)
        st.has_exercises = content.has_exercises(cid)
        if p is not None:
            st.best_pct = p.best_pct
            st.last_pct = p.last_pct
            st.attempts = p.attempts
            st.proofs_done = p.proofs_done
            st.proofs_total = p.proofs_total
        out[cid] = st

    # maitrise puis deblocage, en ordre topologique : l'etat d'un prerequis
    # doit etre connu avant celui des cours qui en dependent
    for cid in syl.topo:
        st = out[cid]
        mastered = st.best_pct is not None and st.best_pct >= thr
        st.missing = [p for p in syl.get(cid).prereqs if out[p].state != MASTERED]
        st.unlocked = not st.missing
        if mastered:
            st.state = MASTERED
        elif st.attempts > 0:
            st.state = STARTED
        elif st.generated:
            st.state = READY
        elif st.unlocked:
            st.state = AVAILABLE
        else:
            st.state = LOCKED
    return out


def next_recommended(syl: Syllabus, statuses: Dict[str, Status], limit: int = 6) -> List[str]:
    """Cours accessibles maintenant, du plus simple au plus avance."""
    candidates = [
        cid for cid in syl.order
        if statuses[cid].state in (AVAILABLE, READY, STARTED) and statuses[cid].unlocked
    ]
    candidates.sort(key=lambda cid: (syl.get(cid).depth, syl.get(cid).level))
    return candidates[:limit]
