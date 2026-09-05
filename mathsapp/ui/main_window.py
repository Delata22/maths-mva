"""Fenetre principale."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDockWidget, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import content, settings, store
from ..generation.claude_cli import ClaudeError, check_available
from ..generation.queue import GenerationQueue
from ..syllabus import Syllabus, load as load_syllabus
from . import theme
from .chat_panel import ChatPanel
from .course_page import CoursePage
from .dashboard import Dashboard
from .graph_page import GraphPage
from .library import LibraryPage
from .prefs import PrefsDialog
from .queue_panel import QueuePanel

PAGE_HOME, PAGE_LIBRARY, PAGE_COURSE, PAGE_GRAPH = range(4)


class ProofHelperWindow(QDialog):
    """Fenetre dediee a l'explication d'une demonstration."""

    def __init__(self, syl: Syllabus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Demonstration pas a pas")
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
        self.queue = GenerationQueue(self)
        self._proof_windows: List[ProofHelperWindow] = []

        self.setWindowTitle("Maths MVA")
        self.resize(1500, 950)

        self._build_topbar()
        self._build_pages()
        self._build_docks()
        self._wire()
        self._shortcuts()

        self.statusBar().showMessage("Pret")
        self.status_info = QLabel("")
        self.status_info.setObjectName("Muted")
        self.statusBar().addPermanentWidget(self.status_info)

        QTimer.singleShot(300, self._check_cli)
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
            (PAGE_HOME, "Accueil", "Vue d'ensemble et prochaines etapes"),
            (PAGE_LIBRARY, "Bibliotheque", "Tous les cours, filtrables"),
            (PAGE_COURSE, "Cours", "Le cours ouvert"),
            (PAGE_GRAPH, "Graphe", "Le cursus comme graphe de prerequis"),
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
        self.btn_chat.setToolTip("Poser une question a Claude  (Ctrl+K)")
        self.btn_chat.setCheckable(True)
        self.btn_chat.setAutoRaise(True)
        lay.addWidget(self.btn_chat)

        self.btn_queue = QToolButton()
        self.btn_queue.setText("Generations")
        self.btn_queue.setCheckable(True)
        self.btn_queue.setAutoRaise(True)
        lay.addWidget(self.btn_queue)

        self.btn_theme = QToolButton()
        self.btn_theme.setText("Theme")
        self.btn_theme.setAutoRaise(True)
        self.btn_theme.clicked.connect(self.toggle_theme)
        lay.addWidget(self.btn_theme)

        self.btn_prefs = QToolButton()
        self.btn_prefs.setText("Preferences")
        self.btn_prefs.setAutoRaise(True)
        self.btn_prefs.clicked.connect(self.open_prefs)
        lay.addWidget(self.btn_prefs)

    def _build_pages(self) -> None:
        self.stack = QStackedWidget()
        self.dashboard = Dashboard(self.syl)
        self.library = LibraryPage(self.syl)
        self.course_page = CoursePage(self.syl)
        self.graph = GraphPage(self.syl)
        for page in (self.dashboard, self.library, self.course_page, self.graph):
            self.stack.addWidget(page)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.topbar)
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
        self.queue_dock = QDockWidget("File de generation", self)
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
        self.library.course_opened.connect(self.open_course)
        self.library.generate_requested.connect(self.enqueue)
        self.library.exercises_requested.connect(self.enqueue_exercises)
        self.library.cancel_requested.connect(self.queue.cancel)
        self.library.delete_requested.connect(self.delete_content)

        self.course_page.open_course.connect(self.open_course)
        self.course_page.generate_requested.connect(self.enqueue)
        self.course_page.exercises_requested.connect(self.enqueue_exercises)
        self.course_page.cancel_requested.connect(self.queue.cancel)
        self.course_page.ask_requested.connect(self.ask_about)
        self.course_page.proof_help_requested.connect(self.open_proof_helper)

        self.graph.course_opened.connect(self.open_course)
        self.graph.generate_requested.connect(self.enqueue)

        self.dashboard.course_opened.connect(self.open_course)
        self.dashboard.generate_requested.connect(self.enqueue)
        self.dashboard.show_graph.connect(self.show_track)

        self.queue_panel.course_opened.connect(self.open_course)
        self.queue.changed.connect(self._on_queue_changed)
        self.queue.job_done.connect(self._on_job_done)

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, self.focus_chat)
        QShortcut(QKeySequence("Ctrl+1"), self, self.go_home)
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.go(PAGE_LIBRARY))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.go(PAGE_COURSE))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.go(PAGE_GRAPH))
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_search)
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

    def go_home(self) -> None:
        self.go(PAGE_HOME)

    def open_course(self, course_id: str) -> None:
        self.course_page.show_course(course_id)
        self.go(PAGE_COURSE)
        job = self.queue.job_for(course_id)
        self.course_page.set_generation_progress(
            job is not None, job.progress if job else 0.0, job.label if job else "")

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
            answer = QMessageBox.question(
                self, "Generer plusieurs cours",
                "Lancer la generation de %d cours ?\n\n"
                "Comptez quelques minutes par cours. La file tourne en arriere-plan, "
                "vous pouvez continuer a travailler." % len(items),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        added = self.queue.enqueue_many(items)
        if added:
            self.queue_dock.setVisible(True)
            self.statusBar().showMessage(
                "%d generation%s ajoutee%s a la file"
                % (added, "s" if added > 1 else "", "s" if added > 1 else ""), 5000)

    def enqueue_exercises(self, course_id: str) -> None:
        self.queue.enqueue(course_id, self.syl.title(course_id), "exercises")
        self.queue_dock.setVisible(True)

    def delete_content(self, course_id: str) -> None:
        answer = QMessageBox.question(
            self, "Supprimer le contenu",
            "Supprimer le cours genere et ses exercices pour \"%s\" ?\n\n"
            "Votre progression (scores, notes) est conservee."
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
        return "%s  %d %%" % (job.label.split(" - ")[0], int(job.progress * 100))

    def _on_queue_changed(self) -> None:
        if self.stack.currentIndex() == PAGE_LIBRARY:
            self.library.refresh()
        course = self.course_page.course
        if course is not None:
            job = self.queue.job_for(course.id)
            self.course_page.set_generation_progress(
                job is not None, job.progress if job else 0.0, job.label if job else "")
        active = self.queue.active_count()
        self.status_info.setText(
            "" if not active else "%d generation%s en cours" % (active, "s" if active > 1 else ""))

    def _on_job_done(self, course_id: str, _kind: str, ok: bool, message: str) -> None:
        title = self.syl.title(course_id)
        self.statusBar().showMessage(
            "%s : %s" % (title, message if ok else "echec - %s" % message), 12000)
        if self.stack.currentIndex() == PAGE_LIBRARY:
            self.library.refresh()
        elif self.stack.currentIndex() == PAGE_HOME:
            self.dashboard.refresh()
        elif self.stack.currentIndex() == PAGE_GRAPH:
            self.graph.rebuild()
        if self.course_page.course and self.course_page.course.id == course_id and ok:
            self.course_page.show_course(course_id)
            self.course_page.reload_exercises()

    # -------------------------------------------------------------------- chat
    def ask_about(self, course_id: str, excerpt: str, heading: str) -> None:
        course = self.syl.get(course_id) if course_id else None
        self.chat_dock.setVisible(True)
        self.chat.set_context(course, "course" if course else "general")
        if not excerpt:
            self.chat.composer.setFocus()
            return
        section = (" (section \"%s\")" % heading) if heading else ""
        prompt = ("A propos de ce passage du cours%s :\n\n« %s »\n\n"
                  "Explique-le moi." % (section, excerpt))
        self.chat.ask(prompt, autosend=False)
        self.chat.composer.setFocus()

    def open_proof_helper(self, course_id: str, proof_id: str, title: str, text: str) -> None:
        from ..generation.prompts import proof_walkthrough_prompt
        course = self.syl.get(course_id)
        window = ProofHelperWindow(self.syl, self)
        window.setWindowTitle("Demonstration : %s" % (title or self.syl.title(course_id)))
        window.chat.set_context(course, "proof:%s" % proof_id, proof_mode=True,
                                title=title or "Demonstration")
        self._proof_windows.append(window)
        window.finished.connect(lambda _=0, w=window: self._proof_windows.remove(w)
                                if w in self._proof_windows else None)
        window.show()
        if not window.chat.session.history():
            window.chat.send_hidden(
                proof_walkthrough_prompt(title or self.syl.title(course_id), text),
                shown="Explique-moi cette demonstration etape par etape.")

    # ----------------------------------------------------------------- divers
    def toggle_theme(self) -> None:
        theme.set_name("light" if theme.name() == "dark" else "dark")
        self.apply_theme()

    def apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.chat.apply_theme()
        self.course_page.apply_theme()
        for window in self._proof_windows:
            window.chat.apply_theme()
        index = self.stack.currentIndex()
        if index == PAGE_HOME:
            self.dashboard.refresh()
        elif index == PAGE_LIBRARY:
            self.library.refresh()
        elif index == PAGE_GRAPH:
            self.graph.rebuild()

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
            self.chat.hint.setText("modele : %s" % settings.get("model/chat"))

    def _check_cli(self) -> None:
        try:
            version = check_available()
        except ClaudeError as exc:
            QMessageBox.warning(
                self, "CLI claude introuvable",
                "%s\n\nLa lecture des cours deja generes fonctionne, mais aucune "
                "nouvelle generation ni discussion n'est possible tant que le CLI "
                "n'est pas accessible." % exc)
        else:
            self.status_info.setText("claude %s" % version.split()[0])

    def closeEvent(self, event) -> None:  # noqa: N802
        self.queue.cancel_all()
        self.chat.stop()
        for window in list(self._proof_windows):
            window.close()
        super().closeEvent(event)
