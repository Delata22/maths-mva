"""File d'attente de generation, executee en arriere-plan."""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .. import settings
from ..syllabus import load as load_syllabus
from . import pipeline
from .claude_cli import ClaudeError

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"

KIND_LABEL = {"course": "Cours + exercices", "exercises": "Exercices seuls"}


@dataclass
class Job:
    course_id: str
    title: str
    kind: str = "course"
    state: str = QUEUED
    progress: float = 0.0
    label: str = "En attente"
    error: str = ""
    cancel_requested: bool = False

    @property
    def active(self) -> bool:
        return self.state in (QUEUED, RUNNING)


class _Signals(QObject):
    progress = Signal(str, str, float, str)   # course_id, kind, frac, label
    finished = Signal(str, str, bool, str)    # course_id, kind, ok, message


class _Task(QRunnable):
    def __init__(self, job: Job, signals: _Signals):
        super().__init__()
        self.job = job
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        job = self.job
        if job.cancel_requested:
            self.signals.finished.emit(job.course_id, job.kind, False, "Annule")
            return
        job.state = RUNNING

        def on_progress(label: str, frac: float) -> None:
            job.label = label
            job.progress = max(0.0, min(1.0, frac))
            self.signals.progress.emit(job.course_id, job.kind, job.progress, label)

        def cancel() -> bool:
            return job.cancel_requested

        try:
            syl = load_syllabus()
            if job.kind == "exercises":
                pipeline.regenerate_exercises(job.course_id, on_progress, cancel, syl)
                msg = "Exercices regeneres"
            else:
                meta = pipeline.generate_course(job.course_id, on_progress, cancel, True, syl)
                msg = "Genere en %s (%.2f $)" % (
                    _fmt_duration(meta.get("duration_s", 0)), meta.get("cost_usd", 0))
            self.signals.finished.emit(job.course_id, job.kind, True, msg)
        except pipeline.GenerationCancelled:
            self.signals.finished.emit(job.course_id, job.kind, False, "Annule")
        except ClaudeError as exc:
            self.signals.finished.emit(job.course_id, job.kind, False, str(exc))
        except Exception as exc:  # noqa: BLE001 - on veut voir toute erreur dans l'UI
            traceback.print_exc()
            self.signals.finished.emit(
                job.course_id, job.kind, False, "%s : %s" % (type(exc).__name__, exc))


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "%ds" % seconds
    return "%dmin %02ds" % (seconds // 60, seconds % 60)


class GenerationQueue(QObject):
    """Ordonnanceur simple : N generations en parallele, le reste en attente."""

    changed = Signal()
    job_done = Signal(str, str, bool, str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.jobs: List[Job] = []
        self._by_key: Dict[tuple, Job] = {}
        self._signals = _Signals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._pool = QThreadPool(self)
        self.apply_concurrency()

    def apply_concurrency(self) -> None:
        n = max(1, min(4, int(settings.get("gen/concurrency") or 1)))
        self._pool.setMaxThreadCount(n)

    # ------------------------------------------------------------------ API
    def is_active(self, course_id: str) -> bool:
        return any(j.course_id == course_id and j.active for j in self.jobs)

    def job_for(self, course_id: str) -> Optional[Job]:
        for j in self.jobs:
            if j.course_id == course_id and j.active:
                return j
        return None

    def active_count(self) -> int:
        return sum(1 for j in self.jobs if j.active)

    def enqueue(self, course_id: str, title: str, kind: str = "course") -> Optional[Job]:
        key = (course_id, kind)
        existing = self._by_key.get(key)
        if existing is not None and existing.active:
            return None
        job = Job(course_id=course_id, title=title, kind=kind)
        self.jobs.append(job)
        self._by_key[key] = job
        self._pool.start(_Task(job, self._signals))
        self.changed.emit()
        return job

    def enqueue_many(self, items: List[tuple]) -> int:
        added = 0
        for course_id, title in items:
            if self.enqueue(course_id, title) is not None:
                added += 1
        return added

    def cancel(self, course_id: str, kind: Optional[str] = None) -> None:
        for j in self.jobs:
            if j.course_id == course_id and j.active and (kind is None or j.kind == kind):
                j.cancel_requested = True
                j.label = "Annulation..."
        self.changed.emit()

    def cancel_all(self) -> None:
        for j in self.jobs:
            if j.active:
                j.cancel_requested = True
                j.label = "Annulation..."
        self.changed.emit()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.active]
        self.changed.emit()

    # -------------------------------------------------------------- signaux
    @Slot(str, str, float, str)
    def _on_progress(self, _cid: str, _kind: str, _frac: float, _label: str) -> None:
        self.changed.emit()

    @Slot(str, str, bool, str)
    def _on_finished(self, course_id: str, kind: str, ok: bool, message: str) -> None:
        job = self._by_key.get((course_id, kind))
        if job is not None:
            if ok:
                job.state = DONE
                job.progress = 1.0
                job.label = message
            elif message == "Annule":
                job.state = CANCELLED
                job.label = "Annule"
            else:
                job.state = ERROR
                job.error = message
                job.label = "Erreur"
        self.changed.emit()
        self.job_done.emit(course_id, kind, ok, message)
