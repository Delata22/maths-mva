"""Vue web (contenu des cours) et pont JavaScript vers l'application."""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWidgets import QToolTip

# Seuls les contenus locaux sont autorises : l'app doit rester un espace de
# travail ferme (pas de web, pas de navigateur), meme si une page generee
# contient un lien ou une ressource distante.
LOCAL_SCHEMES = {"file", "qrc", "data", "blob", "about", "qt"}


def is_local(url: QUrl) -> bool:
    return url.scheme().lower() in LOCAL_SCHEMES
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
    action_ignored = Signal(str)                  # assistant : carte ignorée
    course_section_requested = Signal(str, str)   # cours, titre de section
    exercise_requested = Signal(str)              # cours importe : numero d'exercice
    reading_position_changed = Signal(str)        # position de lecture, JSON
    quiz_progress_saved = Signal(str)             # tentative de QCM en cours, JSON
    quiz_progress_cleared = Signal(str)           # serie dont la tentative est effacee
    training_status_changed = Signal(str, str)    # TD d'entrainement : "td/exercice", statut
    training_action_requested = Signal(str, str)  # "regenerate" | "delete", numero du TD
    brouillon_requested = Signal(str)             # cle de la demonstration a (re)generer

    @Slot(str, str)
    def askAbout(self, text: str, heading: str) -> None:  # noqa: N802 (appele par JS)
        self.ask_requested.emit(text, heading)

    @Slot(str, str, str)
    def openProofHelper(self, proof_id: str, heading: str, text: str) -> None:  # noqa: N802
        self.proof_help_requested.emit(proof_id, heading, text)

    @Slot(str)
    def quizFinished(self, payload: str) -> None:  # noqa: N802
        self.quiz_finished.emit(payload)

    @Slot(str)
    def saveQuizProgress(self, payload: str) -> None:  # noqa: N802
        self.quiz_progress_saved.emit(payload)

    @Slot(str)
    def clearQuizProgress(self, set_id: str) -> None:  # noqa: N802
        self.quiz_progress_cleared.emit(set_id)

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
    def saveReadingPosition(self, payload: str) -> None:  # noqa: N802
        self.reading_position_changed.emit(payload)

    @Slot(str)
    def runAction(self, action_id: str) -> None:  # noqa: N802
        self.action_requested.emit(action_id)

    @Slot(str)
    def ignoreAction(self, action_id: str) -> None:  # noqa: N802
        self.action_ignored.emit(action_id)

    @Slot(str, str)
    def setProofStatus(self, proof_id: str, value: str) -> None:  # noqa: N802
        self.proof_status_changed.emit(proof_id, value)

    @Slot(str, str)
    def saveProofDraft(self, proof_id: str, text: str) -> None:  # noqa: N802
        self.proof_draft_changed.emit(proof_id, text)

    @Slot(str, str)
    def reviewProof(self, proof_id: str, payload: str) -> None:  # noqa: N802
        self.proof_review_requested.emit(proof_id, payload)

    @Slot(str, str)
    def setTrainingStatus(self, key: str, value: str) -> None:  # noqa: N802
        self.training_status_changed.emit(key, value)

    @Slot(str, str)
    def trainingAction(self, action: str, td_id: str) -> None:  # noqa: N802
        self.training_action_requested.emit(action, td_id)

    @Slot(str)
    def generateBrouillon(self, key: str) -> None:  # noqa: N802
        self.brouillon_requested.emit(key)


class _Interceptor(QWebEngineUrlRequestInterceptor):
    """Refuse toute requete reseau (images, scripts, iframes, XHR...)."""

    def interceptRequest(self, info) -> None:  # noqa: N802
        if not is_local(info.requestUrl()):
            info.block(True)


_interceptor = None


def _lock_profile() -> None:
    global _interceptor
    if _interceptor is None:
        _interceptor = _Interceptor()
        QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(_interceptor)


class _Page(QWebEnginePage):
    """Bloque la navigation externe : l'app ne doit pas ouvrir de navigateur."""

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if not is_local(url):
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                QToolTip.showText(QCursor.pos(), "Lien externe bloqué")
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, _type):  # noqa: N802
        # target=_blank, window.open : pas de nouvelle fenetre
        QToolTip.showText(QCursor.pos(), "Lien externe bloqué")
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print("[page] %s:%s %s" % (source.rsplit("/", 1)[-1], line, message))


class WebView(QWebEngineView):
    """QWebEngineView configure pour du contenu local, avec pont optionnel."""

    def __init__(self, parent=None, with_bridge: bool = False):
        super().__init__(parent)
        _lock_profile()
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
