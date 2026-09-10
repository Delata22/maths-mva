"""Statut d'un cours : genere ? debloque ? maitrise ?"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import content, settings, store
from .syllabus import Syllabus

LOCKED = "locked"          # des prerequis ne sont pas maitrises
AVAILABLE = "available"    # prerequis ok, mais cours pas encore genere
PARTIAL = "partial"        # generation commencee puis interrompue
READY = "ready"            # cours genere, pas encore evalue
STARTED = "started"        # QCM tente, pas au niveau
MASTERED = "mastered"      # QCM reussi au-dela du seuil

LABELS = {
    LOCKED: "Verrouillé",
    AVAILABLE: "Disponible",
    PARTIAL: "Incomplet",
    READY: "À étudier",
    STARTED: "En cours",
    MASTERED: "Maîtrisé",
}


@dataclass
class Status:
    course_id: str
    generated: bool = False
    complete: bool = False
    partial: bool = False
    sections_done: int = 0
    sections_total: int = 0
    has_exercises: bool = False
    unlocked: bool = False
    missing: List[str] = field(default_factory=list)
    best_pct: Optional[int] = None
    last_pct: Optional[int] = None
    score_pct: Optional[int] = None
    answered: int = 0
    correct: int = 0
    questions_total: int = 0
    questions_needed: int = 0
    attempts: int = 0
    proofs_done: int = 0
    proofs_total: int = 0
    state: str = LOCKED

    @property
    def mastered(self) -> bool:
        return self.state == MASTERED

    @property
    def enough_answered(self) -> bool:
        """A-t-on repondu a assez de questions pour juger de la maitrise ?"""
        return self.answered >= self.questions_needed > 0

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
        state = content.generation_state(cid)
        st.generated = content.has_course(cid)
        st.complete = state["complete"]
        st.partial = state["partial"]
        st.sections_done = state["sections_done"]
        st.sections_total = state["sections_total"]
        st.has_exercises = state["has_exercises"]
        if p is not None:
            st.best_pct = p.best_pct
            st.last_pct = p.last_pct
            st.attempts = p.attempts
            st.proofs_done = p.proofs_done
            st.proofs_total = p.proofs_total
            if st.has_exercises:
                # on ignore le suivi des questions qui n'existent plus, sinon
                # une regeneration des exercices gonflerait le denominateur
                known = content.question_ids(cid)
                answered = p.answered_ids & known
                st.answered = len(answered)
                st.correct = len(p.correct_ids & answered)
                st.questions_total = len(known)
                largest = content.largest_set_size(cid)
                st.questions_needed = min(st.questions_total,
                                          max(5, math.ceil(0.7 * largest)))
                if st.answered:
                    st.score_pct = int(round(100.0 * st.correct / st.answered))
        out[cid] = st

    # maitrise puis deblocage, en ordre topologique : l'etat d'un prerequis
    # doit etre connu avant celui des cours qui en dependent
    for cid in syl.topo:
        st = out[cid]
        # Le score est l'etat courant des reponses, pas la meilleure seance :
        # refaire une question ratee et la reussir doit faire monter le score.
        mastered = (st.score_pct is not None and st.score_pct >= thr
                    and st.enough_answered)
        st.missing = [p for p in syl.get(cid).prereqs if out[p].state != MASTERED]
        st.unlocked = not st.missing
        if mastered:
            st.state = MASTERED
        elif st.answered > 0 or st.attempts > 0:
            st.state = STARTED
        elif st.partial:
            st.state = PARTIAL
        elif st.complete:
            st.state = READY
        elif st.unlocked:
            st.state = AVAILABLE
        else:
            st.state = LOCKED
    return out


def incomplete(syl: Syllabus, statuses: Dict[str, Status]) -> List[str]:
    """Cours dont la generation a ete interrompue."""
    return [cid for cid in syl.order if statuses[cid].partial]


def next_recommended(syl: Syllabus, statuses: Dict[str, Status], limit: int = 6) -> List[str]:
    """Cours accessibles maintenant, du plus simple au plus avance."""
    candidates = [
        cid for cid in syl.order
        if statuses[cid].state in (AVAILABLE, READY, STARTED) and statuses[cid].unlocked
    ]
    candidates.sort(key=lambda cid: (syl.get(cid).depth, syl.get(cid).level))
    return candidates[:limit]
