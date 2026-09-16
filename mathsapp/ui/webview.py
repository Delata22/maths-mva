"""Vue web (contenu des cours) et pont JavaScript vers l'application."""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


class Bridge(QObject):
    """Objet expose au JavaScript sous le nom `app`."""

    ask_requested = Signal(str, str)              # extrait, titre de section
    proof_help_requested = Signal(str, str, str)  # id, titre, texte
    quiz_finished = Signal(str)                   # charge utile JSON
    proof_status_changed = Signal(str, str)       # id, statut
    proof_draft_changed = Signal(str, str)        # id, texte du brouillon
    proof_review_requested = Signal(str, str)     # id, charge utile JSON
    quiz_set_requested = Signal()                 # nouvelle serie de QCM
    course_open_requested = Signal(str)           # identifiant de cours
    action_requested = Signal(str)                # assistant : identifiant d'action
    course_section_requested = Signal(str, str)   # cours, titre de section
    exercise_requested = Signal(str)              # cours importe : numero d'exercice

    @Slot(str, str)
    def askAbout(self, text: str, heading: str) -> None:  # noqa: N802 (appele par JS)
        self.ask_requested.emit(text, heading)

    @Slot(str, str, str)
    def openProofHelper(self, proof_id: str, heading: str, text: str) -> None:  # noqa: N802
        self.proof_help_requested.emit(proof_id, heading, text)

    @Slot(str)
    def quizFinished(self, payload: str) -> None:  # noqa: N802
        self.quiz_finished.emit(payload)

    @Slot()
    def newQuizSet(self) -> None:  # noqa: N802
        self.quiz_set_requested.emit()

    @Slot(str)
    def openCourse(self, course_id: str) -> None:  # noqa: N802
        self.course_open_requested.emit(course_id)

    @Slot(str, str)
    def openCourseAt(self, course_id: str, section: str) -> None:  # noqa: N802
        self.course_section_requested.emit(course_id, section)

    @Slot(str)
    def openExercise(self, number: str) -> None:  # noqa: N802
        self.exercise_requested.emit(number)

    @Slot(str)
    def runAction(self, action_id: str) -> None:  # noqa: N802
        self.action_requested.emit(action_id)

    @Slot(str, str)
    def setProofStatus(self, proof_id: str, value: str) -> None:  # noqa: N802
        self.proof_status_changed.emit(proof_id, value)

    @Slot(str, str)
    def saveProofDraft(self, proof_id: str, text: str) -> None:  # noqa: N802
        self.proof_draft_changed.emit(proof_id, text)

    @Slot(str, str)
    def reviewProof(self, proof_id: str, payload: str) -> None:  # noqa: N802
        self.proof_review_requested.emit(proof_id, payload)


class _Page(QWebEnginePage):
    """Bloque la navigation externe : l'app ne doit pas ouvrir de navigateur."""

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if url.scheme() in ("http", "https"):
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print("[page] %s:%s %s" % (source.rsplit("/", 1)[-1], line, message))


class WebView(QWebEngineView):
    """QWebEngineView configure pour du contenu local, avec pont optionnel."""

    def __init__(self, parent=None, with_bridge: bool = False):
        super().__init__(parent)
        self.setPage(_Page(self))
        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, False)
        self.bridge = None
        if with_bridge:
            self.bridge = Bridge(self)
            channel = QWebChannel(self)
            channel.registerObject("app", self.bridge)
            self.page().setWebChannel(channel)

    def load_file(self, path) -> None:
        self.load(QUrl.fromLocalFile(str(path)))

    def run_js(self, code: str) -> None:
        self.page().runJavaScript(code)

    def set_theme(self, theme: str) -> None:
        self.run_js("window.setTheme && window.setTheme(%r);" % theme)
