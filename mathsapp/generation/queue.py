"""File d'attente de generation, executee en arriere-plan."""
from __future__ import annotations

import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .. import settings
from ..syllabus import load as load_syllabus
from . import pipeline
from .claude_cli import Cancelled, ClaudeError, connectivity_hint

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"

KIND_LABEL = {
    "course": "Cours + exercices",
    "regenerate": "Régénération complète",
    "exercises": "Exercices seuls",
    "sheet": "Fiche de révision",
    "quiz": "Série de QCM",
    "daily": "Quiz du jour",
    "td": "Correction de TD",
    "refresher": "Rappel ciblé",
    "import": "Import de cours",
    "training": "TD d'entraînement",
    "brouillon": "Brouillons des démonstrations",
    "gaps": "Fiches de lacunes",
}


def kind_label(kind: str) -> str:
    """Libellé d'un type de travail. « training:2 » : régénération du TD 2."""
    base, _, arg = (kind or "").partition(":")
    label = KIND_LABEL.get(base, kind)
    if base == "training" and arg:
        label += " (TD %s, régénération)" % arg
    if base == "brouillon" and arg:
        label = "Brouillon d'une démonstration"
    return label


# Au-dela de ce silence, on considere que l'appel ne repond plus. Le chien de
# garde du CLI l'interrompra de son cote ; ici on le signale a l'utilisateur.
SLOW_AFTER = 75.0
SILENT_AFTER = 180.0

# Annonce d'une nouvelle tentative par claude_cli.run, reprise dans le libelle
_RETRY = re.compile(r"(?:— )?([^—]*?), nouvelle tentative dans (\d+) s")

# Travaux termines ou annules encore signales a l'assistant pendant ce delai
RECENT_AFTER = 3600.0


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
    queued_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    last_activity: float = 0.0
    finished_at: float = 0.0
    retry_until: float = 0.0     # pause avant une nouvelle tentative de l'appel
    retry_reason: str = ""       # « limite de débit de l'API », « erreur réseau »…
    last_notice: str = ""        # dernier message d'erreur transitoire

    def note_progress(self, label: str, now: Optional[float] = None) -> None:
        """Repere dans un libelle d'avancement l'annonce d'une nouvelle tentative."""
        now = time.time() if now is None else now
        m = _RETRY.search(label or "")
        if m:
            self.retry_reason = m.group(1).strip()
            self.retry_until = now + int(m.group(2))
            detail = label.split(" · ", 1)
            self.last_notice = detail[1].strip() if len(detail) > 1 else label

    @property
    def active(self) -> bool:
        return self.state in (QUEUED, RUNNING)

    @property
    def silent_for(self) -> float:
        """Secondes ecoulees depuis le dernier signe de vie."""
        if self.state != RUNNING or not self.last_activity:
            return 0.0
        return max(0.0, time.time() - self.last_activity)

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = time.time() if self.active else max(self.last_activity, self.started_at)
        return max(0.0, end - self.started_at)

    @property
    def health(self) -> str:
        """« vivant », « lent » ou « muet » — ce qu'on affiche a l'utilisateur."""
        if self.state != RUNNING:
            return "inactif"
        silence = self.silent_for
        if silence > SILENT_AFTER:
            return "muet"
        if silence > SLOW_AFTER:
            return "lent"
        return "vivant"


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
            self.signals.finished.emit(job.course_id, job.kind, False, "Annulé")
            return
        job.state = RUNNING
        job.started_at = time.time()
        job.last_activity = job.started_at

        def on_progress(label: str, frac: float) -> None:
            job.label = label
            job.progress = max(0.0, min(1.0, frac))
            job.last_activity = time.time()
            job.note_progress(label, job.last_activity)
            self.signals.progress.emit(job.course_id, job.kind, job.progress, label)

        def cancel() -> bool:
            return job.cancel_requested

        try:
            syl = load_syllabus()
            if job.kind == "regenerate":
                from .. import content
                content.delete_course(job.course_id)
                meta = pipeline.generate_course(job.course_id, on_progress, cancel, True, syl)
                msg = "Régénéré en %s (%.2f $)" % (
                    _fmt_duration(meta.get("duration_s", 0)), meta.get("cost_usd", 0))
            elif job.kind == "exercises":
                pipeline.regenerate_exercises(job.course_id, on_progress, cancel, syl)
                msg = "Exercices régénérés"
            elif job.kind == "td":
                result = pipeline.run_td(job.course_id, on_progress, cancel, syl)
                msg = "TD corrigé : %d exercices (%.2f $)" % (result["exercises"], result["cost"])
            elif job.kind == "import":
                result = pipeline.run_course_import(job.course_id, on_progress, cancel, syl)
                msg = "Cours « %s » importé (%.2f $)" % (result["title"], result["cost"])
            elif job.kind == "refresher":
                _day, cost = pipeline.generate_refresher(
                    job.course_id, None, None, on_progress, cancel, syl)
                msg = "Rappel prêt (%.2f $)" % cost
            elif job.kind == "gaps":
                result, cost = pipeline.generate_gaps(None, on_progress, cancel, syl)
                msg = "%d fiche%s proposée%s" % (
                    result["new"], "s" if result["new"] > 1 else "", "s" if result["new"] > 1 else "")
                if result["relapsed"]:
                    msg += ", %d notion%s à revoir" % (
                        len(result["relapsed"]), "s" if len(result["relapsed"]) > 1 else "")
                msg += " (%.2f $)" % cost
            elif job.kind == "daily":
                day, cost = pipeline.generate_daily_quiz(
                    None, None, on_progress, cancel, syl)
                msg = "Quiz du %s prêt (%.2f $)" % (day, cost)
            elif job.kind == "quiz":
                set_id, cost = pipeline.generate_quiz_set(
                    job.course_id, None, on_progress, cancel, syl)
                msg = "Série %s produite (%.2f $)" % (set_id, cost)
            elif job.kind == "sheet":
                cost = pipeline.generate_sheet(job.course_id, None, on_progress, cancel, syl)
                msg = "Fiche produite (%.2f $)" % cost
            elif job.kind.startswith("training"):
                replace = job.kind.partition(":")[2]
                td_id, cost = pipeline.generate_training(
                    job.course_id, int(replace) if replace else None, None,
                    on_progress, cancel, syl)
                msg = "TD d'entraînement %d prêt (%.2f $)" % (td_id, cost)
            elif job.kind.startswith("brouillon"):
                key = job.kind.partition(":")[2]
                count, cost = pipeline.generate_brouillons(
                    job.course_id, [key] if key else None, None, on_progress, cancel, syl)
                msg = ("%d brouillon%s produit%s (%.2f $)"
                       % (count, "s" if count > 1 else "", "s" if count > 1 else "", cost)
                       if count else "Brouillons déjà à jour")
            else:
                meta = pipeline.generate_course(job.course_id, on_progress, cancel, True, syl)
                msg = "Généré en %s (%.2f $)" % (
                    _fmt_duration(meta.get("duration_s", 0)), meta.get("cost_usd", 0))
            self.signals.finished.emit(job.course_id, job.kind, True, msg)
        except Cancelled:
            self.signals.finished.emit(job.course_id, job.kind, False, "Annulé")
        except ClaudeError as exc:
            hint = connectivity_hint(str(exc))
            message = "%s\n%s" % (exc, hint) if hint else str(exc)
            self.signals.finished.emit(job.course_id, job.kind, False, message)
        except Exception as exc:  # noqa: BLE001 - on veut voir toute erreur dans l'UI
            traceback.print_exc()
            self.signals.finished.emit(
                job.course_id, job.kind, False, "%s : %s" % (type(exc).__name__, exc))


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "%ds" % seconds
    return "%dmin %02ds" % (seconds // 60, seconds % 60)


def explain(job: Job, running: int, limit: int, now: Optional[float] = None) -> tuple:
    """(statut, raison) d'un travail, en clair.

    Statuts : en attente, en cours, en pause, erreur, terminé, annulé. La raison
    est vide quand il n'y a rien a expliquer."""
    now = time.time() if now is None else now
    if job.state == DONE:
        return ("terminé", "")
    if job.state == CANCELLED:
        return ("annulé", "arrêt demandé par l'utilisateur")
    if job.state == ERROR:
        first = (job.error or "erreur inconnue").strip().splitlines()
        return ("erreur", first[0] if first else "erreur inconnue")
    if job.cancel_requested:
        return ("en cours" if job.state == RUNNING else "en attente", "annulation demandée")
    if job.state == QUEUED:
        if running >= limit:
            return ("en attente", "limite gen/concurrency atteinte (%d/%d en cours)"
                    % (running, limit))
        return ("en attente", "démarrage imminent")
    if job.retry_until > now:
        return ("en pause", "%s, nouvelle tentative dans %d s"
                % (job.retry_reason or "erreur réseau", job.retry_until - now + 0.5))
    if job.health == "muet":
        return ("en cours", "aucun signe de vie depuis %s" % _fmt_duration(job.silent_for))
    if job.health == "lent":
        return ("en cours", "rien reçu depuis %s" % _fmt_duration(job.silent_for))
    return ("en cours", "")


def pause_reason(jobs, course_id: str) -> str:
    """Raison d'une generation de cours interrompue, d'apres son dernier travail."""
    last = [j for j in jobs if j.course_id == course_id
            and j.kind in ("course", "regenerate") and j.state in (ERROR, CANCELLED)]
    if not last:
        return "interrompu lors d'une session précédente"
    status, reason = explain(last[-1], 0, 1)
    if status == "annulé":
        return "arrêté manuellement"
    return "échec : %s" % reason


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
        # La progression arrive a chaque fragment de texte : sans etranglement,
        # l'interface se reconstruirait plusieurs fois par seconde.
        self._notify = QTimer(self)
        self._notify.setSingleShot(True)
        self._notify.setInterval(400)
        self._notify.timeout.connect(self.changed.emit)
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

    def concurrency(self) -> int:
        return self._pool.maxThreadCount()

    def explain(self, job: Job) -> tuple:
        """(statut, raison) d'un travail de la file, voir `explain`."""
        return explain(job, len(self.running_jobs()), self.concurrency())

    def pause_reason(self, course_id: str) -> str:
        """Pourquoi un cours est interrompu (« Incomplet ») sans travail actif."""
        if self.job_for(course_id) is not None:
            return ""
        return pause_reason(self.jobs, course_id)

    def active_count(self) -> int:
        return sum(1 for j in self.jobs if j.active)

    def running_jobs(self) -> List[Job]:
        return [j for j in self.jobs if j.state == RUNNING]

    def health(self) -> tuple:
        """(etat global, plus longue periode de silence, travail concerne)."""
        running = self.running_jobs()
        if not running:
            return ("inactif", 0.0, None)
        worst = max(running, key=lambda j: j.silent_for)
        return (worst.health, worst.silent_for, worst)

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
                j.label = "Annulation…"
        self.changed.emit()

    def retry(self, course_id: str, kind: str = "course") -> Optional[Job]:
        """Relance un travail termine en echec, sans repartir de zero."""
        job = self._by_key.get((course_id, kind))
        title = job.title if job else course_id
        self._by_key.pop((course_id, kind), None)
        if job is not None and not job.active:
            self.jobs = [j for j in self.jobs if j is not job]
        return self.enqueue(course_id, title, kind)

    def retry_failed(self) -> int:
        failed = [(j.course_id, j.title, j.kind) for j in self.jobs if j.state == ERROR]
        count = 0
        for course_id, title, kind in failed:
            self._by_key.pop((course_id, kind), None)
            self.jobs = [j for j in self.jobs
                         if not (j.course_id == course_id and j.kind == kind and not j.active)]
            if self.enqueue(course_id, title, kind) is not None:
                count += 1
        return count

    def cancel_all(self) -> None:
        for j in self.jobs:
            if j.active:
                j.cancel_requested = True
                j.label = "Annulation…"
        self.changed.emit()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.active]
        self.changed.emit()

    # -------------------------------------------------------------- signaux
    @Slot(str, str, float, str)
    def _on_progress(self, _cid: str, _kind: str, _frac: float, _label: str) -> None:
        if not self._notify.isActive():
            self._notify.start()

    @Slot(str, str, bool, str)
    def _on_finished(self, course_id: str, kind: str, ok: bool, message: str) -> None:
        job = self._by_key.get((course_id, kind))
        if job is not None:
            job.last_activity = time.time()
            job.finished_at = job.last_activity
            job.retry_until = 0.0
            if ok:
                job.state = DONE
                job.progress = 1.0
                job.label = message
            elif message == "Annulé":
                job.state = CANCELLED
                job.label = "Annulé"
            else:
                job.state = ERROR
                job.error = message
                job.label = "Erreur"
        self.changed.emit()
        self.job_done.emit(course_id, kind, ok, message)
