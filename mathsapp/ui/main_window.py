"""Fenetre principale."""
from __future__ import annotations

import pathlib
import time
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDockWidget, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import content, curriculum, gamify, gaps, review as review_mod, settings, status as st_mod, store
from ..generation.claude_cli import ClaudeError, check_available
from ..generation.queue import DONE, ERROR, GenerationQueue
from ..syllabus import Syllabus, load as load_syllabus, reload as reload_syllabus
from . import theme
from .chat_panel import ChatPanel
from .course_page import CoursePage
from .dashboard import Dashboard
from .graph_page import GraphPage
from .library import LibraryPage
from .prefs import PrefsDialog
from .queue_panel import QueuePanel
from .session_page import SessionPage
from .td_page import TdPage
from .questions_page import QuestionsPage
from .curriculum_dialog import CurriculumDialog
from .syllabus_dialog import SyllabusDialog

PAGE_HOME, PAGE_LIBRARY, PAGE_COURSE, PAGE_GRAPH, PAGE_SESSION, PAGE_TD, PAGE_QUESTIONS = range(7)


class NoticeBar(QWidget):
    """Bandeau d'information non bloquant, en haut de la fenetre.

    Une boite de dialogue modale au demarrage bloque l'application (et les
    tests) tant qu'on ne l'a pas fermee : pour une information, un bandeau
    qu'on peut ignorer vaut mieux.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Notice")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 9, 12, 9)
        lay.setSpacing(10)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        lay.addWidget(self.label, 1)
        self.action = QPushButton("")
        self._connected = False
        lay.addWidget(self.action)
        self.dismiss = QPushButton("Ignorer")
        self.dismiss.setProperty("flat", True)
        self.dismiss.clicked.connect(self.hide)
        lay.addWidget(self.dismiss)
        self.hide()

    def show_message(self, text: str, action_text: str, callback) -> None:
        self.label.setText(text)
        self.action.setText(action_text)
        if self._connected:
            self.action.clicked.disconnect()
        self.action.clicked.connect(lambda: (self.hide(), callback()))
        self._connected = True
        self.show()


class ProofHelperWindow(QDialog):
    """Fenetre dediee a l'explication d'une demonstration."""

    def __init__(self, syl: Syllabus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Démonstration pas à pas")
        self.resize(720, 800)
        self.setWindowFlag(Qt.WindowType.Window, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.chat = ChatPanel(syl, self)
        lay.addWidget(self.chat)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.chat.stop()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.syl: Syllabus = load_syllabus()
        # Le suivi par question est recent : on reconstruit celui des cours
        # evalues avant son introduction, sinon leur score repartirait a zero.
        store.backfill_question_results()
        gamify.backfill(self.syl)
        self.queue = GenerationQueue(self)
        self._proof_windows: List[ProofHelperWindow] = []
        self._exporters: List[object] = []

        self.setWindowTitle(curriculum.profile()["title"])
        self.resize(1500, 950)

        self._build_topbar()
        self._build_pages()
        self._build_docks()
        self._wire()
        self._shortcuts()

        self.statusBar().showMessage("Prêt")
        self.liveness = QLabel("")
        self.liveness.setToolTip("État des générations en cours")
        self.statusBar().addPermanentWidget(self.liveness)
        self.status_info = QLabel("")
        self.status_info.setObjectName("Muted")
        self.statusBar().addPermanentWidget(self.status_info)

        # Battement independant : il doit tourner meme quand plus rien n'arrive,
        # sinon on ne peut pas distinguer « lent » de « plante ».
        self._pulse = QTimer(self)
        self._pulse.setInterval(2000)
        self._pulse.timeout.connect(self._update_liveness)
        self._pulse.start()
        self._silence_warned = False

        QTimer.singleShot(300, self._check_cli)
        QTimer.singleShot(900, self._check_interrupted)
        QTimer.singleShot(2500, self._check_gaps)
        self.go_home()

    # ------------------------------------------------------------- barre haute
    def _build_topbar(self) -> None:
        self.topbar = QWidget()
        self.topbar.setObjectName("TopBar")
        lay = QHBoxLayout(self.topbar)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(4)

        self.brand = QLabel(curriculum.profile()["title"])
        self.brand.setObjectName("Brand")
        lay.addWidget(self.brand)

        self.nav_buttons = {}
        for key, label, tip in [
            (PAGE_HOME, "Accueil", "Vue d'ensemble et prochaines étapes"),
            (PAGE_LIBRARY, "Bibliothèque", "Tous les cours, filtrables"),
            (PAGE_COURSE, "Cours", "Le cours ouvert"),
            (PAGE_GRAPH, "Graphe", "Le cursus comme graphe de prérequis"),
            (PAGE_TD, "TD", "Sujets de TD importés et leurs corrections commentées"),
            (PAGE_QUESTIONS, "Questions",
             "Une question libre : la réponse et les cours qui la traitent  (Ctrl+6)"),
        ]:
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            lay.addWidget(btn)
            self.nav_buttons[key] = btn

        lay.addStretch(1)

        self.btn_chat = QToolButton()
        self.btn_chat.setText("Chat")
        self.btn_chat.setToolTip("Poser une question à Claude  (Ctrl+K)")
        self.btn_chat.setCheckable(True)
        self.btn_chat.setAutoRaise(True)
        lay.addWidget(self.btn_chat)

        self.btn_assistant = QToolButton()
        self.btn_assistant.setText("Assistant")
        self.btn_assistant.setToolTip(
            "Demander un changement : générer des cours, régler, modifier l'application  (Ctrl+J)")
        self.btn_assistant.setAutoRaise(True)
        self.btn_assistant.clicked.connect(self.open_assistant)
        lay.addWidget(self.btn_assistant)

        self.btn_queue = QToolButton()
        self.btn_queue.setText("Générations")
        self.btn_queue.setCheckable(True)
        self.btn_queue.setAutoRaise(True)
        self.btn_queue.setToolTip("File de génération  (Ctrl+G)")
        lay.addWidget(self.btn_queue)

        # File masquee : une pastille avec le nombre de generations en cours.
        self._queue_hidden = bool(settings.get("ui/queue_hidden"))
        self._queue_alert = False      # echec survenu pendant que la file etait masquee
        self.queue_badge = QToolButton()
        self.queue_badge.setObjectName("QueueBadge")
        self.queue_badge.setAutoRaise(True)
        self.queue_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.queue_badge.clicked.connect(lambda: self.set_queue_hidden(False))
        self.queue_badge.setVisible(False)
        lay.addWidget(self.queue_badge)

        # « Cursus » : packs et profil, nouveau cursus, ajout de quelques cours
        self.btn_syllabus = QToolButton()
        self.btn_syllabus.setText("Cursus")
        self.btn_syllabus.setToolTip(
            "Packs de cours, nouveau cursus pour un autre domaine, ajout de cours")
        self.btn_syllabus.setAutoRaise(True)
        self.btn_syllabus.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_syllabus)
        menu.addAction("Packs et profil…", lambda: self.open_curriculum_dialog())
        menu.addAction("Nouveau cursus…  (Ctrl+Maj+N)",
                       lambda: self.open_curriculum_dialog(new=True))
        menu.addAction("Ajouter des cours au syllabus…  (Ctrl+N)", self.open_syllabus_dialog)
        self.btn_syllabus.setMenu(menu)
        lay.addWidget(self.btn_syllabus)

        self.btn_theme = QToolButton()
        self.btn_theme.setText("Thème")
        self.btn_theme.setAutoRaise(True)
        self.btn_theme.clicked.connect(self.toggle_theme)
        lay.addWidget(self.btn_theme)

        self.btn_prefs = QToolButton()
        self.btn_prefs.setText("Préférences")
        self.btn_prefs.setAutoRaise(True)
        self.btn_prefs.clicked.connect(self.open_prefs)
        lay.addWidget(self.btn_prefs)

    def _build_pages(self) -> None:
        self.stack = QStackedWidget()
        self.dashboard = Dashboard(self.syl)
        self.library = LibraryPage(self.syl)
        self.course_page = CoursePage(self.syl)
        self.graph = GraphPage(self.syl)
        self.session = SessionPage(self.syl)
        self.td_page = TdPage(self.syl)
        self.questions_page = QuestionsPage(self.syl)
        for page in (self.dashboard, self.library, self.course_page, self.graph,
                     self.session, self.td_page, self.questions_page):
            self.stack.addWidget(page)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.notice = NoticeBar()
        lay.addWidget(self.topbar)
        lay.addWidget(self.notice)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _build_docks(self) -> None:
        self.chat = ChatPanel(self.syl)
        self.chat_dock = QDockWidget("Claude", self)
        self.chat_dock.setObjectName("chatDock")
        self.chat_dock.setWidget(self.chat)
        self.chat_dock.setMinimumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.chat_dock)
        self.chat_dock.setVisible(False)
        self.chat.set_context(None, "general")
        self.chat.state_provider = self._assistant_state
        self.chat.queue_provider = self._assistant_queue_state
        self.chat.action_triggered.connect(self.run_assistant_action)
        self.chat.course_opened.connect(self.open_course_at)

        self.queue_panel = QueuePanel(self.queue)
        self.queue_dock = QDockWidget("File de génération", self)
        self.queue_dock.setObjectName("queueDock")
        self.queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.queue_dock)
        self.queue_dock.setVisible(False)

        self.btn_chat.toggled.connect(self.chat_dock.setVisible)
        self.chat_dock.visibilityChanged.connect(
            lambda v: self.btn_chat.setChecked(v))
        self.btn_queue.toggled.connect(
            lambda on: self.set_queue_hidden(False) if on else self.queue_dock.setVisible(False))
        self.queue_dock.visibilityChanged.connect(
            lambda v: self.btn_queue.setChecked(v))
        self.queue_panel.hide_requested.connect(lambda: self.set_queue_hidden(True))
        self._sync_queue_badge()

    def _wire(self) -> None:
        self.library.set_queue_lookup(self._queue_label)
        self.library.set_pause_lookup(self.queue.pause_reason)
        self.dashboard.set_queue_lookup(self._queue_label)
        self.library.course_opened.connect(self.open_course)
        self.library.generate_requested.connect(self.enqueue)
        self.library.regenerate_requested.connect(self.regenerate)
        self.library.exercises_requested.connect(self.enqueue_exercises)
        self.library.sheets_requested.connect(self.enqueue_sheets)
        self.library.cancel_requested.connect(self.queue.cancel)
        self.library.delete_requested.connect(self.delete_content)

        self.course_page.open_course.connect(self.open_course)
        self.course_page.generate_requested.connect(self.enqueue)
        self.course_page.regenerate_requested.connect(self.regenerate)
        self.course_page.exercises_requested.connect(self.enqueue_exercises)
        self.course_page.sheet_requested.connect(self.enqueue_sheet)
        self.course_page.quiz_set_requested.connect(self.enqueue_quiz_set)
        self.course_page.training_requested.connect(self.enqueue_training)
        self.course_page.brouillon_requested.connect(self.enqueue_brouillon)
        self.course_page.sheet_export_requested.connect(self.export_sheet_pdf)
        self.course_page.progress_made.connect(self._refresh_current)
        self.course_page.cancel_requested.connect(self.queue.cancel)
        self.course_page.ask_requested.connect(self.ask_about)
        self.course_page.proof_help_requested.connect(self.open_proof_helper)
        self.course_page.proof_review_requested.connect(self.open_proof_review)

        self.graph.course_opened.connect(self.open_course)
        self.graph.generate_requested.connect(self.enqueue)

        self.dashboard.course_opened.connect(self.open_course)
        self.dashboard.generate_requested.connect(self.enqueue)
        self.dashboard.show_graph.connect(self.show_track)
        self.dashboard.session_requested.connect(self.start_session)
        self.dashboard.resume_requested.connect(self.resume_course)
        self.dashboard.curriculum_requested.connect(lambda: self.open_curriculum_dialog(new=True))
        self.session.finished.connect(self._on_session_finished)
        self.session.leave.connect(self.go_home)
        self.td_page.course_opened.connect(self.open_course)
        self.td_page.ask_requested.connect(self.ask_about)
        self.td_page.proof_help_requested.connect(self.open_proof_helper)
        self.td_page.correct_requested.connect(self.enqueue_td)
        self.questions_page.course_opened.connect(self.open_course_at)
        self.course_page.open_course_at.connect(self.open_course_at)
        self.library.import_requested.connect(self.import_course)

        self.queue_panel.course_opened.connect(self.open_course)
        self.queue_panel.retried.connect(lambda: self.statusBar().showMessage(
            "Génération relancée — elle reprend où elle s'était arrêtée", 8000))
        self._library_refresh = QTimer(self)
        self._library_refresh.setSingleShot(True)
        self._library_refresh.setInterval(1500)
        self._library_refresh.timeout.connect(self._refresh_current)
        self.queue.changed.connect(self._on_queue_changed)
        self.queue.job_done.connect(self._on_job_done)

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, self.focus_chat)
        QShortcut(QKeySequence("Ctrl+J"), self, self.open_assistant)
        QShortcut(QKeySequence("Ctrl+1"), self, self.go_home)
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.go(PAGE_LIBRARY))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.go(PAGE_COURSE))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.go(PAGE_GRAPH))
        QShortcut(QKeySequence("Ctrl+5"), self, lambda: self.go(PAGE_TD))
        QShortcut(QKeySequence("Ctrl+6"), self, lambda: self.go(PAGE_QUESTIONS))
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_search)
        QShortcut(QKeySequence("Ctrl+N"), self, self.open_syllabus_dialog)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, lambda: self.open_curriculum_dialog(new=True))
        QShortcut(QKeySequence("Ctrl+G"), self, self.toggle_queue)

    # ------------------------------------------------------------- navigation
    def go(self, page: int) -> None:
        if page == PAGE_COURSE and self.course_page.course is None:
            page = PAGE_LIBRARY
        self.stack.setCurrentIndex(page)
        for key, btn in self.nav_buttons.items():
            btn.setChecked(key == page)
        if page == PAGE_HOME:
            self.dashboard.refresh()
        elif page == PAGE_LIBRARY:
            self.library.refresh()
        elif page == PAGE_GRAPH:
            self.graph.rebuild()
        elif page == PAGE_TD:
            self.td_page.refresh()
        elif page == PAGE_QUESTIONS:
            self.questions_page.refresh()

    def go_home(self) -> None:
        self.go(PAGE_HOME)

    def open_course(self, course_id: str) -> None:
        self.course_page.show_course(course_id)
        self.go(PAGE_COURSE)
        job = self.queue.job_for(course_id)
        self.course_page.set_generation_progress(
            job is not None, job.progress if job else 0.0, job.label if job else "")

    def resume_course(self, course_id: str) -> None:
        """Carte « Reprendre » : le cours, à la position de lecture enregistrée."""
        if course_id not in self.syl.courses:
            return
        self.open_course(course_id)
        self.course_page.resume_reading()

    # ------------------------------------------------------------- seances
    def start_session(self, kind: str) -> None:
        if kind.startswith("refresher:"):
            self.start_refresher(kind.split(":", 1)[1])
            return
        if kind == "gaps-scan":
            self.scan_gaps()
            return
        if kind == "gaps-validate":
            self.validate_gaps()
            return
        statuses = st_mod.compute(self.syl)
        if kind == "daily":
            day = gamify.today()
            data = content.read_daily(day)
            if not data or not data.get("qcm"):
                if self.queue.enqueue(day, "Quiz du %s" % day, "daily") is None:
                    self.statusBar().showMessage("Quiz du jour déjà en préparation", 6000)
                else:
                    self._reveal_queue()
                    self.statusBar().showMessage(
                        "Quiz du jour en préparation — deux minutes environ", 10000)
                return
            questions = [dict(q, day=day) for q in data["qcm"]]
            self.session.start("daily", questions)
        elif kind == "review":
            batch = int(settings.get("goal/review_batch") or 20)
            questions = self._saved_session_questions(kind) or [
                dict(q, course_id=q.get("course_id") or item.course_id,
                     set_id=item.set_id)
                for item, q in review_mod.due_resolved(limit=batch)]
            if not questions:
                self.statusBar().showMessage("Rien à revoir pour le moment", 6000)
                return
            self.session.start("review", questions)
        else:
            saved = self._saved_session_questions("challenge")
            if saved:
                # defi laisse en plan : memes questions, meme ordre
                self.session.start("challenge", saved, timed=True)
                self.go(PAGE_SESSION)
                return
            index = content.question_index()
            pool = [(key, q) for key, q in index.items() if key[1] != "daily"]
            history = {}
            for cid in {key[0] for key, _q in pool}:
                for set_id, marks in store.question_history(cid).items():
                    for qid, mark in marks.items():
                        history[(cid, set_id, qid)] = mark
            seen = [(key, q) for key, q in pool if key in history]
            if len(seen) < 5:
                self.statusBar().showMessage(
                    "Il faut avoir déjà répondu à cinq questions pour un défi", 7000)
                return
            import random
            weak = [pair for pair in seen if not history[pair[0]].get("ok")]
            random.shuffle(weak)
            rest = [pair for pair in seen if pair not in weak]
            random.shuffle(rest)
            chosen = (weak + rest)[:5]
            questions = [dict(q, course_id=key[0], set_id=key[1])
                         for key, q in chosen]
            self.session.start("challenge", questions, timed=True)
        self.go(PAGE_SESSION)

    def _saved_session_questions(self, kind: str) -> Optional[List[dict]]:
        """Révisions ou défi laissés en plan : leurs questions, dans l'ordre
        enregistré. Celles qui n'existent plus sont écartées ; None s'il n'en
        reste aucune (la page propose alors de recommencer)."""
        state = store.quiz_progress(SessionPage.progress_key(kind))
        if not state:
            return None
        index = content.question_index()
        out = []
        for ref in state.get("refs") or []:
            if not isinstance(ref, dict):
                continue
            key = (ref.get("courseId") or "", ref.get("setId") or "", str(ref.get("id") or ""))
            question = index.get(key)
            if question is not None:
                out.append(dict(question, course_id=key[0], set_id=key[1]))
        return out or None

    # ------------------------------------------------------- fiches de lacunes
    def scan_gaps(self, quiet: bool = False) -> None:
        """Fin de séance : relire les échanges avec l'assistant pour en tirer des fiches."""
        if not gaps.needs_scan():
            if not quiet:
                self.statusBar().showMessage(
                    "Aucune nouvelle question à l'assistant depuis la dernière relecture", 7000)
            return
        if self.queue.enqueue(gaps.JOB_ID, "Lacunes de la séance", "gaps") is None:
            if not quiet:
                self.statusBar().showMessage("Relecture déjà en cours", 6000)
        elif not quiet:
            self.statusBar().showMessage(
                "Relecture de la séance — les fiches proposées arrivent dans une minute", 10000)

    def validate_gaps(self) -> None:
        from .gaps_dialog import GapsDialog
        proposed = gaps.cards(gaps.PROPOSED)
        if not proposed:
            self.statusBar().showMessage("Aucune fiche à valider", 6000)
            return
        dialog = GapsDialog(proposed, self.syl, self)
        if not dialog.exec():
            return
        kept = gaps.decide(dialog.kept(), dialog.dropped(), dialog.edits())
        if self.stack.currentIndex() == PAGE_HOME:
            self.dashboard.refresh()
        if kept and dialog.quiz_now():
            day = gamify.today()
            self.session.start("gaps", [dict(gaps.as_question(c), set_id=gaps.SET_ID, day=day)
                                        for c in kept])
            self.go(PAGE_SESSION)

    def _check_gaps(self) -> None:
        """Au démarrage : une séance d'un jour précédent jamais relue l'est maintenant,
        et des fiches en attente de validation sont signalées."""
        import datetime as _dt
        midnight = _dt.datetime.combine(_dt.date.today(), _dt.time()).timestamp()
        if gaps.needs_scan(before=midnight):
            self.scan_gaps(quiet=True)
        elif gaps.cards(gaps.PROPOSED):
            n = len(gaps.cards(gaps.PROPOSED))
            self.notice.show_message("%d fiche%s de lacunes à valider" % (n, "s" if n > 1 else ""),
                                     "Valider", self.validate_gaps)

    def start_refresher(self, course_id: str) -> None:
        """Rappel ciblé de cinq questions : le lance s'il est prêt, sinon le prépare."""
        day = gamify.today()
        data = content.read_refresher(day, course_id)
        if not data or not data.get("qcm"):
            title = self.syl.title(course_id)
            if self.queue.enqueue(course_id, "Rappel — %s" % title, "refresher") is None:
                self.statusBar().showMessage("Rappel déjà en préparation", 6000)
            else:
                self._reveal_queue()
                self.statusBar().showMessage(
                    "Rappel sur « %s » en préparation — une minute environ" % title, 10000)
            return
        questions = [dict(q, day=day, course_id=course_id, set_id="rappel")
                     for q in data["qcm"]]
        self._refresher_key = (day, course_id)
        self.session.start("refresher", questions)
        self.session.title.setText("Rappel ciblé — %s" % self.syl.title(course_id))
        self.go(PAGE_SESSION)

    def _on_session_finished(self, kind: str, payload: str) -> None:
        import json as _json
        try:
            data = _json.loads(payload)
        except _json.JSONDecodeError:
            return
        answers = [a for a in (data.get("answers") or []) if isinstance(a, dict)]
        if not answers:
            return

        # une revision melange des series (QCM du cours, quiz du jour, fiches de
        # lacunes) : chaque reponse est rangee dans la serie d'ou vient sa question
        fixed = {"daily": "daily", "refresher": "rappel", "gaps": gaps.SET_ID}.get(kind)
        by_course: dict = {}
        for answer in answers:
            key = (answer.get("courseId") or "", fixed or str(answer.get("setId") or "1"))
            by_course.setdefault(key, []).append(answer)

        xp = 0
        for (cid, set_id), group in by_course.items():
            if not cid or cid not in self.syl.courses:
                continue
            detail = {"answers": group, "session": kind}
            store.record_attempt(cid, len(group),
                                 sum(1 for a in group if a.get("ok")),
                                 detail, set_id=set_id, partial=True)
            course = self.syl.get(cid)
            gained = sum(gamify.question_xp(a.get("difficulty", 1), bool(a.get("ok")),
                                            a.get("kind", "direct")) for a in group)
            gamify.log("session:%s" % kind, questions=len(group),
                       correct=sum(1 for a in group if a.get("ok")),
                       reviews=len(group) if kind in ("review", "gaps") else 0,
                       xp=gained, domain=course.domain)
            xp += gained

        bonus = 0
        if kind == "review":
            bonus = gamify.XP["review_done"]
        elif kind == "daily":
            bonus = gamify.XP["daily_quiz"]
        elif kind == "gaps":
            bonus = gamify.XP["review_done"]
        elif kind == "refresher":
            bonus = gamify.XP["refresher"]
            key = getattr(self, "_refresher_key", None)
            if key:
                content.mark_refresher_done(*key)
                self._refresher_key = None
        elif kind == "challenge" and data.get("correct") == data.get("total"):
            bonus = gamify.XP["challenge_perfect"]
        gamify.log("session_done:%s" % kind, brick=True, xp=bonus,
                   seconds=float(data.get("seconds") or 0))
        xp += bonus

        statuses = st_mod.compute(self.syl)
        gamify.award_course_mastery(self.syl, statuses)
        fresh = gamify.check_milestones(gamify.build_context(self.syl, statuses))
        goal = gamify.goal_state()
        message = "Séance terminée : %d/%d  ·  +%d XP" % (
            data.get("correct", 0), data.get("total", 0), xp)
        if fresh:
            message += "  ·  jalon atteint : %s" % fresh[0].label
        self.statusBar().showMessage(message, 15000)
        if fresh:
            self.notice.show_message(
                "Jalon atteint : %s" % ", ".join(m.label for m in fresh),
                "Voir", self.go_home)
        elif goal.met and goal.done == goal.target:
            self.notice.show_message(
                "Objectif du jour atteint. Série : %d jour%s."
                % (gamify.refresh_streak().current,
                   "s" if gamify.refresh_streak().current > 1 else ""),
                "Voir", self.go_home)

    def show_track(self, track_id: str) -> None:
        for i in range(self.graph.f_scope.count()):
            if self.graph.f_scope.itemData(i) == ("track", track_id):
                self.graph.f_scope.setCurrentIndex(i)
                break
        self.go(PAGE_GRAPH)

    def focus_search(self) -> None:
        self.go(PAGE_LIBRARY)
        self.library.search.setFocus()
        self.library.search.selectAll()

    def focus_chat(self) -> None:
        self.chat_dock.setVisible(True)
        course = self.course_page.course if self.stack.currentIndex() == PAGE_COURSE else None
        self.chat.set_context(course, "course" if course else "general")
        self.chat.composer.setFocus()

    # -------------------------------------------------------------- generation
    def enqueue(self, course_ids: List[str]) -> None:
        if not course_ids:
            return
        items = [(cid, self.syl.title(cid)) for cid in course_ids
                 if cid in self.syl.courses]
        if len(items) > 4:
            per_course, per_cost = content.generation_estimate()
            workers = max(1, min(4, int(settings.get("gen/concurrency") or 1)))
            hours = len(items) * per_course / 3600.0 / workers
            duration = ("environ %d min" % round(hours * 60) if hours < 1.5
                        else "environ %.0f h" % hours)
            answer = QMessageBox.question(
                self, "Générer plusieurs cours",
                "Lancer la génération de %d cours ?\n\n"
                "Estimation d'après vos générations précédentes : %s de calcul "
                "et de l'ordre de %.0f $ au total, à %d génération%s en parallèle.\n\n"
                "La file tourne en arrière-plan et reprend après une coupure ; "
                "vous pouvez l'arrêter à tout moment."
                % (len(items), duration, len(items) * per_cost, workers,
                   "s" if workers > 1 else ""),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        added = self.queue.enqueue_many(items)
        if added:
            self._reveal_queue()
            self.statusBar().showMessage(
                "%d génération%s ajoutée%s à la file"
                % (added, "s" if added > 1 else "", "s" if added > 1 else ""), 5000)
        else:
            # sans ce retour, un second clic ne produisait rien du tout
            self._reveal_queue()
            self.statusBar().showMessage(
                "Déjà dans la file : %s"
                % ", ".join(t for _c, t in items[:3]), 6000)
        self._refresh_current()

    def regenerate(self, course_id: str) -> None:
        answer = QMessageBox.question(
            self, "Régénérer le cours",
            "Refaire entièrement « %s » ?\n\n"
            "Le cours, les figures et les exercices actuels seront remplacés par une "
            "nouvelle version, à partir d'un nouveau plan. Vos scores et vos notes "
            "sont conservés." % self.syl.title(course_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.queue.enqueue(course_id, self.syl.title(course_id), "regenerate")
        self._reveal_queue()

    def resume_all(self) -> None:
        """Reprend toutes les generations interrompues."""
        statuses = st_mod.compute(self.syl)
        ids = st_mod.incomplete(self.syl, statuses)
        if ids:
            self.enqueue(ids)

    def enqueue_exercises(self, course_id: str) -> None:
        self.queue.enqueue(course_id, self.syl.title(course_id), "exercises")
        self._reveal_queue()

    def enqueue_quiz_set(self, course_id: str) -> None:
        if self.queue.enqueue(course_id, self.syl.title(course_id), "quiz") is None:
            self.statusBar().showMessage("Série déjà en production", 5000)
            return
        self._reveal_queue()
        self.statusBar().showMessage(
            "Nouvelle série de questions pour « %s » — environ deux minutes"
            % self.syl.title(course_id), 8000)

    def enqueue_training(self, course_id: str, replace: int = 0) -> None:
        """TD d'entraînement : une nouvelle feuille, ou la feuille `replace` refaite."""
        if not content.is_complete(course_id):
            self.statusBar().showMessage(
                "Le cours doit être entièrement rédigé avant un TD d'entraînement", 6000)
            return
        kind = "training:%d" % replace if replace else "training"
        if self.queue.enqueue(course_id, self.syl.title(course_id), kind) is None:
            self.statusBar().showMessage("Ce TD est déjà en production", 5000)
            return
        self._reveal_queue()
        self.statusBar().showMessage(
            "TD d'entraînement pour « %s » en production" % self.syl.title(course_id), 8000)
        self._on_queue_changed()

    def enqueue_brouillon(self, course_id: str, key: str) -> None:
        """Brouillon d'une démonstration (clé), ou de toutes celles du cours (« * »)."""
        from .. import brouillon
        if key == "*":
            todo = len(brouillon.pending(course_id))
            if not todo:
                self.statusBar().showMessage("Tous les brouillons de ce cours sont à jour", 6000)
                self.course_page.brouillon_failed("*", "")
                return
            if todo > 3:
                answer = QMessageBox.question(
                    self, "Brouillons des démonstrations",
                    "Produire les brouillons de %d démonstrations de « %s » ?\n\n"
                    "Un appel au modèle %s par démonstration, plusieurs en parallèle. "
                    "Chaque brouillon est enregistré dès qu'il est prêt."
                    % (todo, self.syl.title(course_id), settings.get("model/exercises")),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    self.course_page.brouillon_failed("*", "")
                    return
        kind = "brouillon" if key == "*" else "brouillon:%s" % key
        if self.queue.enqueue(course_id, self.syl.title(course_id), kind) is None:
            self.statusBar().showMessage("Ce brouillon est déjà en production", 5000)
            return
        self._reveal_queue()
        self.statusBar().showMessage(
            "Brouillon%s en production pour « %s »"
            % ("s" if key == "*" else "", self.syl.title(course_id)), 6000)
        self._on_queue_changed()

    def enqueue_td(self, td_id: str) -> None:
        """Lire un sujet de TD si besoin, puis corriger ses exercices."""
        from .. import td as td_mod
        state = td_mod.state(td_id)
        remaining = state["total"] - state["corrected"] if state["structured"] else None
        count = remaining if remaining is not None else 20
        if count > 3:
            answer = QMessageBox.question(
                self, "Corriger le TD",
                "%s « %s » ?\n\nEnviron %d min et de l'ordre de %.0f $ avec le modèle %s. "
                "La correction tourne en arrière-plan et reprend après une coupure."
                % ("Lire et corriger" if remaining is None
                   else "Corriger les %d exercices restants de" % remaining,
                   td_mod.title(td_id), max(5, count * 5 // 3), count * 0.7,
                   settings.get("model/course")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self.queue.enqueue(td_id, "TD — %s" % td_mod.title(td_id), "td") is None:
            self.statusBar().showMessage("Correction déjà en cours pour ce TD", 6000)
            return
        self._reveal_queue()
        self.statusBar().showMessage("Correction du TD lancée en arrière-plan", 8000)

    def enqueue_sheet(self, course_id: str) -> None:
        if self.queue.enqueue(course_id, self.syl.title(course_id), "sheet") is None:
            self.statusBar().showMessage("Fiche déjà en cours de production", 5000)
            return
        self._reveal_queue()
        self.statusBar().showMessage(
            "Fiche de « %s » en production" % self.syl.title(course_id), 6000)

    def enqueue_sheets(self, course_ids: List[str]) -> None:
        todo = [c for c in course_ids if content.has_course(c) and not content.has_sheet(c)]
        if not todo:
            self.statusBar().showMessage("Toutes les fiches sont déjà là", 5000)
            return
        if len(todo) > 4:
            answer = QMessageBox.question(
                self, "Générer les fiches",
                "Produire %d fiches de révision ?\n\n"
                "Environ une minute et 0,20 $ par fiche, soit à peu près "
                "%d min et %.0f $." % (len(todo), len(todo) * 100 // 60, len(todo) * 0.2),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        for cid in todo:
            self.queue.enqueue(cid, self.syl.title(cid), "sheet")
        self._reveal_queue()

    def export_sheet_pdf(self, course_id: str) -> None:
        """Enregistre la fiche en PDF a l'endroit choisi par l'utilisateur."""
        from PySide6.QtWidgets import QFileDialog
        from .pdf_export import PdfExporter
        if not content.has_sheet(course_id):
            return
        title = self.syl.title(course_id)
        default = str(pathlib.Path.home() / ("Fiche - %s.pdf" % title.replace("/", "-")))
        path, _filter = QFileDialog.getSaveFileName(
            self, "Enregistrer la fiche", default, "PDF (*.pdf)")
        if not path:
            return
        self.statusBar().showMessage("Export en cours…")
        exporter = PdfExporter(self)
        self._exporters.append(exporter)

        def done(ok: bool, message: str) -> None:
            self._exporters.remove(exporter) if exporter in self._exporters else None
            if ok:
                self.statusBar().showMessage("Fiche enregistrée : %s" % message, 12000)
                self.notice.show_message(
                    "Fiche enregistrée dans %s" % message, "Ouvrir le dossier",
                    lambda p=message: QDesktopServices.openUrl(
                        QUrl.fromLocalFile(str(pathlib.Path(p).parent))))
            else:
                self.statusBar().showMessage("Export impossible : %s" % message, 12000)

        exporter.finished.connect(done)
        exporter.export(course_id, title, pathlib.Path(path))

    def delete_content(self, course_id: str) -> None:
        answer = QMessageBox.question(
            self, "Supprimer le contenu",
            "Supprimer le cours généré et ses exercices pour \"%s\" ?\n\n"
            "Votre progression (scores, notes) est conservée."
            % self.syl.title(course_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            content.delete_course(course_id)
            self.library.refresh()
            if self.course_page.course and self.course_page.course.id == course_id:
                self.course_page.refresh()

    # ------------------------------------------------------- file masquee
    def _reveal_queue(self) -> None:
        """Ouverture automatique de la file, sauf si l'utilisateur l'a masquée."""
        if not self._queue_hidden:
            self.queue_dock.setVisible(True)

    def set_queue_hidden(self, hidden: bool) -> None:
        """Masque la file (pastille seule) ou la rouvre. Rien n'est mis en pause."""
        if hidden == self._queue_hidden and hidden != self.queue_dock.isVisible():
            self._sync_queue_badge()
            return
        self._queue_hidden = hidden
        settings.put("ui/queue_hidden", 1 if hidden else 0)
        if hidden:
            self.queue_dock.setVisible(False)
        else:
            self._queue_alert = False
            self.queue_dock.show()
            self.queue_dock.raise_()
        self._sync_queue_badge()
        if hasattr(self, "liveness"):
            self._update_liveness()

    def toggle_queue(self) -> None:
        """Ctrl+G : masquer la file si elle est affichée, la rouvrir sinon."""
        self.set_queue_hidden(self.queue_dock.isVisible())

    def queue_badge_state(self) -> str:
        """« hidden-off » (file affichée), « empty », « running », « alert » ou « done »."""
        if not self._queue_hidden:
            return "hidden-off"
        if self._queue_alert:
            return "alert"
        if self.queue.active_count():
            return "running"
        if any(j.state == DONE for j in self.queue.jobs):
            return "done"
        return "empty"

    def _sync_queue_badge(self) -> None:
        from .queue_panel import _age
        state = self.queue_badge_state()
        self.btn_queue.setVisible(state == "hidden-off")
        self.queue_badge.setVisible(state != "hidden-off")
        if state == "hidden-off":
            return
        pal = theme.palette()
        active = self.queue.active_count()
        failed = sum(1 for j in self.queue.jobs if j.state == ERROR)
        if state == "alert":
            text, color = ("▲ %d" % active if active else "▲"), pal["err"]
            tip = ("Une génération a échoué pendant que la file était masquée "
                   "(%d échec%s). Cliquer pour ouvrir la file."
                   % (failed, "s" if failed > 1 else "")) if failed else \
                  "Une génération a échoué. Cliquer pour ouvrir la file."
        elif state == "running":
            health, silence, _job = self.queue.health()
            text, color = "● %d" % active, pal["accent"]
            tip = ("%d génération%s en cours ou en attente, dernier signe de vie il y a %s."
                   % (active, "s" if active > 1 else "", _age(silence)))
        elif state == "done":
            text, color = "✓", pal["muted"]
            tip = "Générations terminées."
        else:
            text, color = "○", pal["muted"]
            tip = "File de génération vide."
        self.queue_badge.setText(text)
        self.queue_badge.setStyleSheet(
            "QToolButton#QueueBadge{color:%s;font-weight:600;padding:2px 8px;}" % color)
        self.queue_badge.setToolTip("%s\nFile masquée : cliquer ou Ctrl+G pour l'afficher." % tip)

    def _queue_label(self, course_id: str) -> Optional[str]:
        job = self.queue.job_for(course_id)
        if job is None:
            return None
        status, reason = self.queue.explain(job)
        if status == "en pause" or (status == "en attente" and reason):
            return "%s : %s  %d %%" % (status.capitalize(), reason, int(job.progress * 100))
        short = job.label.split(" — ")[0].split(" · ")[0]
        return "%s  %d %%" % (short, int(job.progress * 100))

    def _update_liveness(self) -> None:
        """Indicateur permanent : ce qui tourne, et depuis quand c'est muet."""
        from .queue_panel import _age
        pal = theme.palette()
        self._sync_queue_badge()
        running = self.queue.running_jobs()
        waiting = self.queue.active_count() - len(running)
        if self._queue_hidden:
            # file masquee : la pastille suffit, ni indicateur ni bandeau
            self.liveness.setText("")
            return
        if not running:
            self.liveness.setText("")
            self._silence_warned = False
            return
        health, silence, job = self.queue.health()
        colors = {"vivant": pal["ok"], "lent": pal["warn"], "muet": pal["err"]}
        word = {"vivant": "actif il y a", "lent": "rien depuis", "muet": "muet depuis"}
        count = "%d génération%s" % (len(running), "s" if len(running) > 1 else "")
        if waiting > 0:
            count += " (+%d en attente)" % waiting
        self.liveness.setText(
            "<span style='color:%s'>●</span> %s · %s %s"
            % (colors.get(health, pal["muted"]), count, word.get(health, ""), _age(silence)))
        self.liveness.setToolTip(
            "%s\nDémarré il y a %s, dernier signe de vie il y a %s."
            % (job.label, _age(job.elapsed), _age(silence)) if job else "")

        if health == "muet" and not self._silence_warned:
            self._silence_warned = True
            self.notice.show_message(
                "« %s » n'a plus donné signe de vie depuis %s. L'appel sera "
                "interrompu et relancé automatiquement s'il reste muet."
                % (job.title, _age(silence)),
                "Ouvrir la file", lambda: self.set_queue_hidden(False))
        elif health != "muet":
            self._silence_warned = False

    def _refresh_current(self) -> None:
        page = self.stack.currentIndex()
        if page == PAGE_LIBRARY:
            self.library.refresh()
        elif page == PAGE_HOME:
            self.dashboard.refresh()

    def _on_queue_changed(self) -> None:
        if (self.stack.currentIndex() in (PAGE_LIBRARY, PAGE_HOME)
                and not self._library_refresh.isActive()):
            self._library_refresh.start()
        course = self.course_page.course
        if course is not None:
            mine = [j for j in self.queue.jobs if j.course_id == course.id and j.active]
            # un TD d'entrainement ou un brouillon en production n'occupe pas le
            # bouton Générer du cours
            job = next((j for j in mine
                        if not j.kind.startswith(("training", "brouillon"))), None)
            self.course_page.set_brouillon_jobs(
                [j.kind.partition(":")[2] or "*" for j in mine
                 if j.kind.startswith("brouillon")])
            self.course_page.set_generation_progress(
                job is not None, job.progress if job else 0.0, job.label if job else "")
            self.course_page.set_training_state(
                any(j.kind in ("course", "regenerate", "exercises") for j in mine),
                next((j for j in mine if j.kind.startswith("training")), None))
        self._update_liveness()

    def _on_job_done(self, course_id: str, _kind: str, ok: bool, message: str) -> None:
        self._library_refresh.stop()
        if _kind == "td" and self.stack.currentIndex() == PAGE_TD:
            self.td_page.refresh()
        if _kind == "import":
            from .. import course_import
            title = course_import.read_import(course_id) or {}
            title = title.get("title") or course_id
            self.reload_syllabus()
            cid = course_import.course_of(course_id)
            if ok and cid and not self._queue_hidden:
                self.notice.show_message("Cours importé : « %s »" % title, "Ouvrir",
                                         lambda c=cid: self.open_course(c))
        if _kind == "gaps" and ok:
            if self.stack.currentIndex() == PAGE_HOME:
                self.dashboard.refresh()
            if gaps.cards(gaps.PROPOSED):
                self.notice.show_message(message, "Valider", self.validate_gaps)
            else:
                self.statusBar().showMessage("Lacunes : %s" % message, 10000)
            return
        if _kind == "refresher" and ok and not self._queue_hidden:
            self.notice.show_message(
                "Rappel prêt : cinq questions sur « %s »" % self.syl.title(course_id),
                "Commencer", lambda c=course_id: self.start_refresher(c))
        if _kind == "td":
            from .. import td as td_mod
            title = "TD « %s »" % td_mod.title(course_id)
        else:
            title = self.syl.title(course_id)
        if not ok and message != "Annulé" and self._queue_hidden:
            # file masquee : la pastille passe en alerte, rien ne s'ouvre
            self._queue_alert = True
            self._sync_queue_badge()
        elif not ok and message != "Annulé":
            self.notice.show_message(
                "La génération de « %s » a échoué : %s"
                % (title, (message.splitlines() or [""])[0]),
                "Relancer", lambda c=course_id, k=_kind: self.queue.retry(c, k))
            self._reveal_queue()
        self.statusBar().showMessage(
            "%s : %s" % (title, message if ok else "échec — %s" % message), 12000)
        if self.stack.currentIndex() == PAGE_LIBRARY:
            self.library.refresh()
        elif self.stack.currentIndex() == PAGE_HOME:
            self.dashboard.refresh()
        elif self.stack.currentIndex() == PAGE_GRAPH:
            self.graph.rebuild()
        if self.course_page.course and self.course_page.course.id == course_id:
            self._on_queue_changed()
            if _kind.startswith("brouillon"):
                # mis a jour dans la page, sans recharger : la lecture reste en place
                key = _kind.partition(":")[2] or "*"
                self.course_page.push_brouillons()
                if not ok:
                    self.course_page.brouillon_failed(
                        key, "génération annulée" if message == "Annulé"
                        else (message.splitlines() or ["erreur inconnue"])[0])
                return
        if self.course_page.course and self.course_page.course.id == course_id and ok:
            if _kind == "quiz":
                self.course_page.reload_quiz()
            elif _kind.startswith("training"):
                self.course_page.reload_training()
            else:
                self.course_page.reload_content()

    # -------------------------------------------------------------------- chat
    def ask_about(self, course_id: str, excerpt: str, heading: str) -> None:
        course = self.syl.get(course_id) if course_id else None
        self.chat_dock.setVisible(True)
        self.chat.set_context(course, "course" if course else "general")
        if not excerpt:
            self.chat.composer.setFocus()
            return
        section = (" (section \"%s\")" % heading) if heading else ""
        prompt = ("À propos de ce passage du cours%s :\n\n« %s »\n\n"
                  "Explique-le moi." % (section, excerpt))
        self.chat.ask(prompt, autosend=False)
        self.chat.composer.setFocus()

    def open_proof_helper(self, course_id: str, proof_id: str, title: str, text: str) -> None:
        from ..generation.prompts import proof_walkthrough_prompt
        course = self.syl.get(course_id)
        window = ProofHelperWindow(self.syl, self)
        window.setWindowTitle("Démonstration : %s" % (title or self.syl.title(course_id)))
        window.chat.set_context(course, "proof:%s" % proof_id, mode="proof",
                                title=title or "Démonstration")
        self._proof_windows.append(window)
        window.finished.connect(lambda _=0, w=window: self._proof_windows.remove(w)
                                if w in self._proof_windows else None)
        window.show()
        if not window.chat.session.history():
            window.chat.send_hidden(
                proof_walkthrough_prompt(title or self.syl.title(course_id), text),
                shown="Explique-moi cette démonstration étape par étape.")

    def open_proof_review(self, course_id: str, proof_id: str, payload: str) -> None:
        """Ouvre la correction d'une demonstration redigee par l'utilisateur."""
        import json as _json
        from ..generation.prompts import proof_review_prompt
        try:
            data = _json.loads(payload)
        except _json.JSONDecodeError:
            return
        attempt = (data.get("attempt") or "").strip()
        if not attempt:
            return
        mode = "etape" if data.get("mode") == "etape" else "complete"
        course = self.syl.get(course_id)
        title = data.get("title") or "Démonstration"
        attempt_no = store.count_review(course_id, proof_id)

        window = self._proof_window("review:%s" % proof_id)
        if window is None:
            window = ProofHelperWindow(self.syl, self)
            self._proof_windows.append(window)
            window.finished.connect(
                lambda _=0, w=window: self._proof_windows.remove(w)
                if w in self._proof_windows else None)
        window.setWindowTitle(
            ("Sur la bonne voie ? — %s" if mode == "etape" else "Correction : %s") % title)
        # Le fil est le meme dans les deux modes : Claude voit les versions
        # precedentes. Seules les consignes changent d'un envoi a l'autre.
        window.chat.set_context(
            course, "review:%s" % proof_id,
            mode="review-etape" if mode == "etape" else "review",
            title=("Sur la bonne voie — %s" if mode == "etape" else "Correction — %s") % title)
        window.show()
        window.raise_()
        window.activateWindow()
        if window.chat.busy:
            return
        if mode == "etape":
            shown = "Voilà où j'en suis — est-ce que je suis sur la bonne voie ?\n\n%s" % attempt
        elif attempt_no == 1:
            shown = "Ma démonstration :\n\n%s" % attempt
        else:
            shown = "Version %d de ma démonstration :\n\n%s" % (attempt_no, attempt)
        window.chat.send_hidden(
            proof_review_prompt(title, data.get("statement", ""),
                                data.get("solution", ""), attempt, attempt_no, mode),
            shown=shown)
        if attempt_no == 1:
            gamify.log("proof_review", brick=True, xp=gamify.XP["proof_review"],
                       domain=course.domain if course else None)

    def _proof_window(self, context_key: str):
        for w in self._proof_windows:
            session = w.chat.session
            if session is not None and session.context_key == context_key:
                return w
        return None

    # ----------------------------------------------------------------- divers
    def toggle_theme(self) -> None:
        theme.set_name("light" if theme.name() == "dark" else "dark")
        self.apply_theme()

    def apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.chat.apply_theme()
        self.course_page.apply_theme()
        self.session.apply_theme()
        self.td_page.apply_theme()
        self.questions_page.apply_theme()
        for window in self._proof_windows:
            window.chat.apply_theme()
        index = self.stack.currentIndex()
        if index == PAGE_HOME:
            self.dashboard.refresh()
        elif index == PAGE_LIBRARY:
            self.library.refresh()
        elif index == PAGE_GRAPH:
            self.graph.rebuild()

    def import_course(self, path: str = "") -> None:
        """Importer un cours magistral en PDF : lecture, rédaction, exercices corrigés."""
        from PySide6.QtWidgets import QFileDialog
        from .. import course_import
        if not path:
            path, _filter = QFileDialog.getOpenFileName(
                self, "Importer un cours", str(pathlib.Path.home()), "PDF (*.pdf)")
            if not path:
                return
        try:
            doc = course_import.import_pdf(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import impossible", str(exc))
            return
        per_course_s, per_course_cost = content.generation_estimate()
        if QMessageBox.question(
                self, "Importer un cours",
                "Importer « %s » ?\n\nClaude lit tout le document, inscrit le cours au "
                "syllabus (domaine « Cours importés »), le réécrit section par section en "
                "relisant les pages, avec intuitions et liens vers vos cours, puis produit "
                "QCM, fiche et corrections des exercices du document.\n\n"
                "Comptez environ %d min et de l'ordre de %.0f à %.0f $. Tout reprend "
                "après une coupure." % (pathlib.Path(path).name, per_course_s / 60 * 1.5,
                                        per_course_cost * 1.5, per_course_cost * 2.5),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.queue.enqueue(doc, "Import — %s" % pathlib.Path(path).stem, "import") is None:
            self.statusBar().showMessage("Import déjà en cours", 6000)
            return
        self._reveal_queue()
        self.statusBar().showMessage("Import du cours lancé en arrière-plan", 8000)

    def open_course_at(self, course_id: str, section: str = "") -> None:
        """Lien d'une reponse : ouvre le cours, a la section citee s'il y en a une."""
        if course_id not in self.syl.courses:
            return
        self.open_course(course_id)
        if section:
            self.course_page.scroll_to_section(section)

    # ------------------------------------------------------------ assistant
    def open_assistant(self) -> None:
        self.chat_dock.setVisible(True)
        self.chat.set_context(None, "assistant", mode="assistant",
                              title="Assistant de l'application")
        self.chat.composer.setFocus()

    def _assistant_statuses(self) -> dict:
        """Statuts relus au plus une fois par envoi : l'état complet et celui de
        la file sont construits coup sur coup, inutile de relire le disque deux fois."""
        cached = getattr(self, "_assistant_cache", None)
        if cached and time.monotonic() - cached[0] < 2.0:
            return cached[1]
        statuses = st_mod.compute(self.syl)
        self._assistant_cache = (time.monotonic(), statuses)
        return statuses

    def _assistant_state(self) -> str:
        from .. import assistant
        return assistant.app_state(self.syl, self._assistant_statuses(), self.queue.jobs)

    def _assistant_queue_state(self) -> str:
        from .. import assistant
        return assistant.queue_state(self.syl, self._assistant_statuses(), list(self.queue.jobs),
                                     limit=self.queue.concurrency())

    def run_assistant_action(self, action: dict) -> None:
        """Exécute une action validée d'un clic dans l'assistant."""
        from .. import assistant
        kind, aid = action.get("type"), action["id"]

        def done(text: str) -> None:
            self.chat.set_action_state(aid, "done", text)

        def undone(text: str = "") -> None:
            self.chat.set_action_state(aid, "", text)

        try:
            if kind == "generate_courses":
                before = self.queue.active_count()
                self.enqueue(action["courses"])
                added = self.queue.active_count() - before
                if added:
                    done("%d ajouté%s à la file" % (added, "s" if added > 1 else ""))
                else:
                    undone("rien d'ajouté")
            elif kind == "regenerate_course":
                self.queue.enqueue(action["course"], self.syl.title(action["course"]),
                                   "regenerate")
                self._reveal_queue()
                done("ajouté à la file")
            elif kind == "new_quiz_set":
                self.enqueue_quiz_set(action["course"])
                done("série en production")
            elif kind == "generate_sheets":
                self.enqueue_sheets(action["courses"])
                done("fiches en production")
            elif kind == "correct_td":
                before = self.queue.active_count()
                self.enqueue_td(action["td"])
                if self.queue.active_count() > before:
                    done("correction lancée")
                else:
                    undone()
            elif kind == "extend_syllabus":
                self.open_syllabus_dialog()
                dialog = self._syllabus_dialog
                dialog.request.setPlainText(action["request"])
                dialog.count.setValue(int(action["count"]))
                dialog.propose()
                done("proposition en cours, fenêtre Syllabus")
            elif kind == "set_setting":
                settings.put(action["key"], action["value"])
                done("réglé")
            elif kind == "cancel_generation":
                targets = ([j.course_id for j in self.queue.jobs if j.active]
                           if action.get("all") else action["courses"])
                for cid in targets:
                    self.queue.cancel(cid)
                done("%d arrêt%s demandé%s" % (len(targets), "s" if len(targets) > 1 else "",
                                              "s" if len(targets) > 1 else ""))
            elif kind == "open":
                if action["page"] == "course":
                    self.open_course(action["course"])
                else:
                    self.go({"home": PAGE_HOME, "library": PAGE_LIBRARY,
                             "graph": PAGE_GRAPH, "td": PAGE_TD}[action["page"]])
                done("ouvert")
            elif kind == "start_session":
                self.start_session(action["kind"])
                done("lancé")
            elif kind == "modify_app":
                self._start_code_change(action)
            elif kind == "restart_app":
                undone()
                self.restart_app()
            elif kind == "revert_change":
                sha = assistant.revert_commit(action["commit"])
                done("annulé (commit %s) : redémarrez pour l'appliquer" % sha)
            elif kind == "discard_changes":
                assistant.discard_changes(action["tracked"], action["created"])
                done("modifications retirées")
            elif kind == "keep_changes":
                sha = assistant.commit_changes(
                    action["files"],
                    "assistant: %s (gardé malgré les tests)\n\n"
                    "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
                    % action["request"].splitlines()[0][:60])
                done("enregistré (commit %s)" % sha)
        except Exception as exc:  # noqa: BLE001
            self.chat.set_action_state(aid, "failed", str(exc)[:200])

    def _start_code_change(self, action: dict) -> None:
        aid = action["id"]
        from ..generation import claude_cli as cc
        if cc.backend() != "claude":
            # l'edition du code s'appuie sur les outils d'edition du CLI claude
            self.chat.set_action_state(
                aid, "failed", "réservé au moteur claude (Préférences > Génération)")
            return
        busy = getattr(self, "_code_worker", None) is not None
        answer = QMessageBox.question(
            self, "Modifier l'application",
            "Claude va modifier le code de l'application :\n\n%s\n\n"
            "Il peut seulement lire et éditer les fichiers du projet, pas vos cours ni votre "
            "progression. L'application lance ensuite les tests. Si tout passe, le "
            "changement est enregistré dans git, et vous pouvez redémarrer ou l'annuler.\n\n"
            "Comptez quelques minutes et de l'ordre de 1 à 5 $.%s" % (
                action["detail"],
                "\n\nUne autre modification est en cours : celle-ci attendra sa fin et "
                "démarrera automatiquement." if busy else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.chat.set_action_state(aid, "", "")
            return
        if getattr(self, "_code_worker", None) is not None:
            # ni rejet ni disparition : la carte attend la fin du chantier en cours
            self._code_waiting = getattr(self, "_code_waiting", [])
            if all(a["id"] != aid for a in self._code_waiting):
                self._code_waiting.append(action)
            self.chat.set_action_state(
                aid, "waiting", "en attente du chantier en cours : démarrera automatiquement "
                                "à sa fin")
            return
        self._launch_code_change(action)

    def _launch_code_change(self, action: dict) -> None:
        from .. import assistant
        aid = action["id"]
        worker = assistant.CodeChangeWorker(action["request"], self, title=action["detail"])
        self._code_worker = worker
        self.chat.set_action_state(aid, "running", "en cours…")
        self.chat.work_begin("Modification : %s" % action["detail"])
        worker.activity.connect(self.chat.work_line)
        worker.done.connect(lambda result, a=aid: self._on_code_change_done(a, result))
        worker.finished.connect(self._on_code_worker_finished)
        worker.start()

    def _on_code_worker_finished(self) -> None:
        """Fin d'un chantier : la modification suivante en attente démarre seule,
        sauf si le code garde des changements non enregistrés."""
        from .. import assistant
        self._code_worker = None
        waiting = getattr(self, "_code_waiting", [])
        if not waiting:
            return
        try:
            tracked, _untracked = assistant.git_status()
        except Exception:  # noqa: BLE001
            tracked = []
        if tracked:
            for action in waiting:
                self.chat.set_action_state(
                    action["id"], "",
                    "pas lancée : le chantier précédent a laissé des modifications non "
                    "enregistrées. Retirez-les ou gardez-les, puis cliquez pour lancer.")
            self._code_waiting = []
            return
        self._launch_code_change(waiting.pop(0))

    def _on_code_change_done(self, aid: str, result: dict) -> None:
        import html as html_mod
        import uuid
        summary = result.get("summary") or ""
        cost = float(result.get("cost") or 0.0)
        if result.get("ok"):
            self.chat.set_action_state(aid, "done", "fait, commit %s" % result["commit"])
            body = (summary or "<p>Modification faite.</p>") + (
                "<p><em>Tests : %s · commit %s · %.2f $</em></p>"
                % (html_mod.escape(result.get("tests", "")), result["commit"], cost))
            self.chat.work_end(body, [
                {"id": uuid.uuid4().hex[:8], "type": "restart_app", "button": "Redémarrer",
                 "label": "Redémarrer l'application",
                 "detail": "Pour charger la modification."},
                {"id": uuid.uuid4().hex[:8], "type": "revert_change", "button": "Annuler",
                 "secondary": True, "commit": result["commit"],
                 "label": "Annuler ce changement",
                 "detail": "Revient à la version précédente (git revert %s)." % result["commit"]},
            ])
            self.notice.show_message("Modification de l'application prête",
                                     "Redémarrer", self.restart_app)
        elif result.get("files"):
            self.chat.set_action_state(aid, "failed", "pas enregistré")
            body = summary + "<p><strong>%s</strong> Rien n'a été enregistré.</p>" % (
                html_mod.escape(result["error"]) if result.get("error")
                else "Les tests échouent encore.")
            if result.get("tests"):
                body += "<pre>%s</pre>" % html_mod.escape(result["tests"][-2500:])
            self.chat.work_end(body, [
                {"id": uuid.uuid4().hex[:8], "type": "discard_changes", "button": "Retirer",
                 "tracked": result.get("tracked", []), "created": result.get("created", []),
                 "label": "Retirer ces modifications",
                 "detail": ", ".join(result["files"][:8])},
                {"id": uuid.uuid4().hex[:8], "type": "keep_changes", "button": "Garder",
                 "secondary": True, "files": result["files"], "request": result["request"],
                 "label": "Les garder quand même",
                 "detail": "Enregistre dans git malgré les tests."},
            ])
        else:
            self.chat.set_action_state(aid, "failed", "échec")
            self.chat.work_end("<p>%s</p>%s" % (
                html_mod.escape(result.get("error") or "Échec."), summary))

    def restart_app(self) -> None:
        import sys
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QApplication
        from ..paths import PROJECT_ROOT
        running = self.queue.active_count()
        if running and QMessageBox.question(
                self, "Redémarrer",
                "%d génération%s en cours s'arrêter%s. Elles reprendront là où elles en "
                "étaient avec « Reprendre ». Redémarrer quand même ?"
                % (running, "s" if running > 1 else "", "ont" if running > 1 else "a"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        self.close()
        if self.isVisible():
            return
        QProcess.startDetached(sys.executable, ["-m", "mathsapp"], str(PROJECT_ROOT))
        QApplication.quit()

    def open_syllabus_dialog(self) -> None:
        dialog = getattr(self, "_syllabus_dialog", None)
        if dialog is None:
            dialog = SyllabusDialog(self.syl, self)
            dialog.changed.connect(self.reload_syllabus)
            self._syllabus_dialog = dialog
        dialog.set_syllabus(self.syl)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_curriculum_dialog(self, new: bool = False) -> None:
        dialog = getattr(self, "_curriculum_dialog", None)
        if dialog is None:
            dialog = CurriculumDialog(self.syl, self)
            dialog.changed.connect(self.reload_syllabus)
            self._curriculum_dialog = dialog
        dialog.set_syllabus(self.syl)
        if new:
            dialog.show_new()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def reload_syllabus(self) -> None:
        """Après un ajout ou un retrait : on relit le syllabus et on rafraîchit tout."""
        curriculum.reload()
        self.syl = reload_syllabus()
        title = curriculum.profile()["title"]
        self.brand.setText(title)
        self.setWindowTitle(title)
        for page in (self.library, self.course_page, self.graph, self.dashboard):
            page.set_syllabus(self.syl)
        self.session.syl = self.syl
        self.td_page.set_syllabus(self.syl)
        self.questions_page.set_syllabus(self.syl)
        self.chat.syl = self.syl
        for window in self._proof_windows:
            window.chat.syl = self.syl
        for name in ("_syllabus_dialog", "_curriculum_dialog"):
            dialog = getattr(self, name, None)
            if dialog is not None:
                dialog.set_syllabus(self.syl)
        self.statusBar().showMessage(
            "Syllabus rechargé : %d cours" % len(self.syl.courses), 6000)

    def open_prefs(self) -> None:
        dialog = PrefsDialog(self)
        before = theme.name()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self.queue.apply_concurrency()
            if theme.name() != before:
                self.apply_theme()
            else:
                self.library.refresh()
            self.chat.hint.setText("modèle : %s" % settings.get("model/chat"))

    def _check_interrupted(self) -> None:
        """Signale au demarrage les generations laissees en plan."""
        statuses = st_mod.compute(self.syl)
        ids = st_mod.incomplete(self.syl, statuses)
        if not ids:
            self.notice.hide()
            return
        names = ", ".join(self.syl.title(c) for c in ids[:2])
        more = "" if len(ids) <= 2 else " (+%d)" % (len(ids) - 2)
        self.notice.show_message(
            "%d génération%s interrompue%s : %s%s. Les sections déjà écrites sont conservées."
            % (len(ids), "s" if len(ids) > 1 else "", "s" if len(ids) > 1 else "",
               names, more),
            "Reprendre" if len(ids) == 1 else "Tout reprendre",
            lambda todo=list(ids): self.enqueue(todo))

    def _check_cli(self) -> None:
        try:
            version = check_available()
        except ClaudeError as exc:
            QMessageBox.warning(
                self, "CLI claude introuvable",
                "%s\n\nLa lecture des cours déjà générés fonctionne, mais aucune "
                "nouvelle génération ni discussion n'est possible tant que le CLI "
                "n'est pas accessible." % exc)
        else:
            self.status_info.setText("claude %s" % version.split()[0])

    def closeEvent(self, event) -> None:  # noqa: N802
        self.course_page.flush_reading()
        self.queue.cancel_all()
        self.chat.stop()
        for window in list(self._proof_windows):
            window.close()
        super().closeEvent(event)
