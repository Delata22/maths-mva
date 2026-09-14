"""Fenetre principale."""
from __future__ import annotations

import pathlib
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDockWidget, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import content, gamify, review as review_mod, settings, status as st_mod, store
from ..generation.claude_cli import ClaudeError, check_available
from ..generation.queue import GenerationQueue
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
from .syllabus_dialog import SyllabusDialog

PAGE_HOME, PAGE_LIBRARY, PAGE_COURSE, PAGE_GRAPH, PAGE_SESSION, PAGE_TD = range(6)


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

        self.setWindowTitle("Maths MVA")
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
        self.go_home()

    # ------------------------------------------------------------- barre haute
    def _build_topbar(self) -> None:
        self.topbar = QWidget()
        self.topbar.setObjectName("TopBar")
        lay = QHBoxLayout(self.topbar)
        lay.setContentsMargins(14, 8, 12, 8)
        lay.setSpacing(4)

        brand = QLabel("Maths MVA")
        brand.setObjectName("Brand")
        lay.addWidget(brand)

        self.nav_buttons = {}
        for key, label, tip in [
            (PAGE_HOME, "Accueil", "Vue d'ensemble et prochaines étapes"),
            (PAGE_LIBRARY, "Bibliothèque", "Tous les cours, filtrables"),
            (PAGE_COURSE, "Cours", "Le cours ouvert"),
            (PAGE_GRAPH, "Graphe", "Le cursus comme graphe de prérequis"),
            (PAGE_TD, "TD", "Sujets de TD importés et leurs corrections commentées"),
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

        self.btn_queue = QToolButton()
        self.btn_queue.setText("Générations")
        self.btn_queue.setCheckable(True)
        self.btn_queue.setAutoRaise(True)
        lay.addWidget(self.btn_queue)

        self.btn_syllabus = QToolButton()
        self.btn_syllabus.setText("Syllabus")
        self.btn_syllabus.setToolTip("Créer de nouveaux cours dans le syllabus  (Ctrl+N)")
        self.btn_syllabus.setAutoRaise(True)
        self.btn_syllabus.clicked.connect(self.open_syllabus_dialog)
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
        for page in (self.dashboard, self.library, self.course_page, self.graph,
                     self.session, self.td_page):
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

        self.queue_panel = QueuePanel(self.queue)
        self.queue_dock = QDockWidget("File de génération", self)
        self.queue_dock.setObjectName("queueDock")
        self.queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.queue_dock)
        self.queue_dock.setVisible(False)

        self.btn_chat.toggled.connect(self.chat_dock.setVisible)
        self.chat_dock.visibilityChanged.connect(
            lambda v: self.btn_chat.setChecked(v))
        self.btn_queue.toggled.connect(self.queue_dock.setVisible)
        self.queue_dock.visibilityChanged.connect(
            lambda v: self.btn_queue.setChecked(v))

    def _wire(self) -> None:
        self.library.set_queue_lookup(self._queue_label)
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
        self.session.finished.connect(self._on_session_finished)
        self.session.leave.connect(self.go_home)
        self.td_page.course_opened.connect(self.open_course)
        self.td_page.ask_requested.connect(self.ask_about)
        self.td_page.proof_help_requested.connect(self.open_proof_helper)
        self.td_page.correct_requested.connect(self.enqueue_td)

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
        QShortcut(QKeySequence("Ctrl+1"), self, self.go_home)
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.go(PAGE_LIBRARY))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.go(PAGE_COURSE))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.go(PAGE_GRAPH))
        QShortcut(QKeySequence("Ctrl+5"), self, lambda: self.go(PAGE_TD))
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_search)
        QShortcut(QKeySequence("Ctrl+N"), self, self.open_syllabus_dialog)
        QShortcut(QKeySequence("Ctrl+G"), self, lambda: self.queue_dock.setVisible(
            not self.queue_dock.isVisible()))

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

    def go_home(self) -> None:
        self.go(PAGE_HOME)

    def open_course(self, course_id: str) -> None:
        self.course_page.show_course(course_id)
        self.go(PAGE_COURSE)
        job = self.queue.job_for(course_id)
        self.course_page.set_generation_progress(
            job is not None, job.progress if job else 0.0, job.label if job else "")

    # ------------------------------------------------------------- seances
    def start_session(self, kind: str) -> None:
        statuses = st_mod.compute(self.syl)
        if kind == "daily":
            day = gamify.today()
            data = content.read_daily(day)
            if not data or not data.get("qcm"):
                if self.queue.enqueue(day, "Quiz du %s" % day, "daily") is None:
                    self.statusBar().showMessage("Quiz du jour déjà en préparation", 6000)
                else:
                    self.queue_dock.setVisible(True)
                    self.statusBar().showMessage(
                        "Quiz du jour en préparation — deux minutes environ", 10000)
                return
            questions = [dict(q, day=day) for q in data["qcm"]]
            self.session.start("daily", questions)
        elif kind == "review":
            batch = int(settings.get("goal/review_batch") or 20)
            questions = [
                dict(q, course_id=q.get("course_id") or item.course_id,
                     set_id=item.set_id)
                for item, q in review_mod.due_resolved(limit=batch)]
            if not questions:
                self.statusBar().showMessage("Rien à revoir pour le moment", 6000)
                return
            self.session.start("review", questions)
        else:
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

    def _on_session_finished(self, kind: str, payload: str) -> None:
        import json as _json
        try:
            data = _json.loads(payload)
        except _json.JSONDecodeError:
            return
        answers = [a for a in (data.get("answers") or []) if isinstance(a, dict)]
        if not answers:
            return

        by_course: dict = {}
        for answer in answers:
            cid = answer.get("courseId") or ""
            by_course.setdefault(cid, []).append(answer)

        xp = 0
        for cid, group in by_course.items():
            if not cid or cid not in self.syl.courses:
                continue
            set_id = "daily" if kind == "daily" else str(group[0].get("setId") or "1")
            detail = {"answers": group, "session": kind}
            store.record_attempt(cid, len(group),
                                 sum(1 for a in group if a.get("ok")),
                                 detail, set_id=set_id, partial=True)
            course = self.syl.get(cid)
            gained = sum(gamify.question_xp(a.get("difficulty", 1), bool(a.get("ok")),
                                            a.get("kind", "direct")) for a in group)
            gamify.log("session:%s" % kind, questions=len(group),
                       correct=sum(1 for a in group if a.get("ok")),
                       reviews=len(group) if kind == "review" else 0,
                       xp=gained, domain=course.domain)
            xp += gained

        bonus = 0
        if kind == "review":
            bonus = gamify.XP["review_done"]
        elif kind == "daily":
            bonus = gamify.XP["daily_quiz"]
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
            self.queue_dock.setVisible(True)
            self.statusBar().showMessage(
                "%d génération%s ajoutée%s à la file"
                % (added, "s" if added > 1 else "", "s" if added > 1 else ""), 5000)
        else:
            # sans ce retour, un second clic ne produisait rien du tout
            self.queue_dock.setVisible(True)
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
        self.queue_dock.setVisible(True)

    def resume_all(self) -> None:
        """Reprend toutes les generations interrompues."""
        statuses = st_mod.compute(self.syl)
        ids = st_mod.incomplete(self.syl, statuses)
        if ids:
            self.enqueue(ids)

    def enqueue_exercises(self, course_id: str) -> None:
        self.queue.enqueue(course_id, self.syl.title(course_id), "exercises")
        self.queue_dock.setVisible(True)

    def enqueue_quiz_set(self, course_id: str) -> None:
        if self.queue.enqueue(course_id, self.syl.title(course_id), "quiz") is None:
            self.statusBar().showMessage("Série déjà en production", 5000)
            return
        self.queue_dock.setVisible(True)
        self.statusBar().showMessage(
            "Nouvelle série de questions pour « %s » — environ deux minutes"
            % self.syl.title(course_id), 8000)

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
        self.queue_dock.setVisible(True)
        self.statusBar().showMessage("Correction du TD lancée en arrière-plan", 8000)

    def enqueue_sheet(self, course_id: str) -> None:
        if self.queue.enqueue(course_id, self.syl.title(course_id), "sheet") is None:
            self.statusBar().showMessage("Fiche déjà en cours de production", 5000)
            return
        self.queue_dock.setVisible(True)
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
        self.queue_dock.setVisible(True)

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

    def _queue_label(self, course_id: str) -> Optional[str]:
        job = self.queue.job_for(course_id)
        if job is None:
            return None
        short = job.label.split(" — ")[0].split(" · ")[0]
        return "%s  %d %%" % (short, int(job.progress * 100))

    def _update_liveness(self) -> None:
        """Indicateur permanent : ce qui tourne, et depuis quand c'est muet."""
        from .queue_panel import _age
        pal = theme.palette()
        running = self.queue.running_jobs()
        waiting = self.queue.active_count() - len(running)
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
                "Ouvrir la file", lambda: self.queue_dock.setVisible(True))
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
            job = self.queue.job_for(course.id)
            self.course_page.set_generation_progress(
                job is not None, job.progress if job else 0.0, job.label if job else "")
        self._update_liveness()

    def _on_job_done(self, course_id: str, _kind: str, ok: bool, message: str) -> None:
        self._library_refresh.stop()
        if _kind == "td" and self.stack.currentIndex() == PAGE_TD:
            self.td_page.refresh()
        if _kind == "td":
            from .. import td as td_mod
            title = "TD « %s »" % td_mod.title(course_id)
        else:
            title = self.syl.title(course_id)
        if not ok and message != "Annulé":
            self.notice.show_message(
                "La génération de « %s » a échoué : %s"
                % (title, message.splitlines()[0]),
                "Relancer", lambda c=course_id, k=_kind: self.queue.retry(c, k))
            self.queue_dock.setVisible(True)
        self.statusBar().showMessage(
            "%s : %s" % (title, message if ok else "échec — %s" % message), 12000)
        if self.stack.currentIndex() == PAGE_LIBRARY:
            self.library.refresh()
        elif self.stack.currentIndex() == PAGE_HOME:
            self.dashboard.refresh()
        elif self.stack.currentIndex() == PAGE_GRAPH:
            self.graph.rebuild()
        if self.course_page.course and self.course_page.course.id == course_id and ok:
            if _kind == "quiz":
                self.course_page.reload_quiz()
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
        for window in self._proof_windows:
            window.chat.apply_theme()
        index = self.stack.currentIndex()
        if index == PAGE_HOME:
            self.dashboard.refresh()
        elif index == PAGE_LIBRARY:
            self.library.refresh()
        elif index == PAGE_GRAPH:
            self.graph.rebuild()

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

    def reload_syllabus(self) -> None:
        """Après un ajout ou un retrait : on relit le syllabus et on rafraîchit tout."""
        self.syl = reload_syllabus()
        for page in (self.library, self.course_page, self.graph, self.dashboard):
            page.set_syllabus(self.syl)
        self.session.syl = self.syl
        self.td_page.set_syllabus(self.syl)
        self.chat.syl = self.syl
        for window in self._proof_windows:
            window.chat.syl = self.syl
        dialog = getattr(self, "_syllabus_dialog", None)
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
        self.queue.cancel_all()
        self.chat.stop()
        for window in list(self._proof_windows):
            window.close()
        super().closeEvent(event)
