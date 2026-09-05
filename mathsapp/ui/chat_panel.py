"""Panneau de discussion avec Claude (streaming, rendu LaTeX)."""
from __future__ import annotations

import html as html_mod
import json
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import content, settings
from ..chat import ChatSession, ChatWorker, clean_answer
from ..paths import ASSETS_DIR, library_dir
from ..syllabus import Course, Syllabus
from . import theme
from .webview import WebView

EMPTY_GENERAL = (
    "Posez n'importe quelle question de maths.<br>"
    "Sélectionnez un passage d'un cours pour le mettre en contexte."
)
EMPTY_COURSE = "Questions sur ce cours. Le contexte du cursus est déjà fourni à Claude."


class Composer(QPlainTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Votre question  (Entrée pour envoyer, Maj+Entrée pour un saut de ligne)")
        self.setFixedHeight(64)
        self.textChanged.connect(self._grow)

    def _grow(self) -> None:
        doc = self.document().size().height()
        self.setFixedHeight(int(min(150, max(64, doc + 18))))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    """Un fil de discussion. Reutilise pour le chat general, le chat de cours
    et l'assistant de demonstration."""

    busy_changed = Signal(bool)

    def __init__(self, syllabus: Optional[Syllabus] = None, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.session: Optional[ChatSession] = None
        self.worker: Optional[ChatWorker] = None
        self._empty_text = EMPTY_GENERAL
        self._ready = False
        self._queued_calls: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("TopBar")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 7, 8, 7)
        hl.setSpacing(8)
        self.title = QLabel("Discussion générale")
        self.title.setObjectName("H2")
        hl.addWidget(self.title)
        hl.addStretch(1)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setProperty("flat", True)
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self.stop)
        hl.addWidget(self.btn_stop)
        self.btn_clear = QPushButton("Effacer")
        self.btn_clear.setProperty("flat", True)
        self.btn_clear.setToolTip("Oublier cette conversation et repartir de zéro")
        self.btn_clear.clicked.connect(self.reset)
        hl.addWidget(self.btn_clear)
        root.addWidget(head)

        self.view = WebView(self)
        self.view.loadFinished.connect(self._on_loaded)
        root.addWidget(self.view, 1)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(10, 8, 10, 10)
        bl.setSpacing(6)
        self.composer = Composer()
        self.composer.submitted.connect(self.send)
        bl.addWidget(self.composer)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        row.addWidget(self.hint)
        row.addStretch(1)
        self.btn_send = QPushButton("Envoyer")
        self.btn_send.setProperty("primary", True)
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.btn_send)
        bl.addLayout(row)
        root.addWidget(bottom)

        self._load_page()

    # ------------------------------------------------------------------ page
    def _load_page(self) -> None:
        tpl = (ASSETS_DIR / "chat.html").read_text(encoding="utf-8")
        page = (tpl.replace("__THEME__", theme.name())
                   .replace("__ASSETS__", content.assets_url())
                   .replace("__EMPTY__", self._empty_text))
        views = library_dir() / "_views"
        views.mkdir(parents=True, exist_ok=True)
        path = views / ("chat_%x.html" % id(self))
        path.write_text(page, encoding="utf-8")
        self._ready = False
        self.view.load_file(path)

    def _on_loaded(self, ok: bool) -> None:
        self._ready = bool(ok)
        for code in self._queued_calls:
            self.view.run_js(code)
        self._queued_calls.clear()

    def _js(self, code: str) -> None:
        if self._ready:
            self.view.run_js(code)
        else:
            self._queued_calls.append(code)

    def apply_theme(self) -> None:
        self._js("window.setTheme(%s);" % json.dumps(theme.name()))

    # --------------------------------------------------------------- session
    def set_context(self, course: Optional[Course], context_key: str = "general",
                    mode: str = "general", title: Optional[str] = None) -> None:
        if (self.session and self.session.context_key == context_key
                and (self.session.course.id if self.session.course else None)
                == (course.id if course else None)):
            return
        self.stop()
        self.session = ChatSession(course, self.syl, context_key, mode)
        self._empty_text = EMPTY_COURSE if course else EMPTY_GENERAL
        self.title.setText(title or (course.title if course else "Discussion générale"))
        self.hint.setText("modèle : %s" % settings.get("model/chat"))
        self._js("window.chatReset(%s);" % json.dumps(self._empty_text))
        for msg in self.session.history():
            role = msg["role"]
            body = (html_mod.escape(msg["content"]) if role == "user"
                    else clean_answer(msg["content"]))
            self._js("window.chatAdd(%s, %s);" % (json.dumps(role), json.dumps(body)))

    def reset(self) -> None:
        if self.session is None:
            return
        self.stop()
        self.session.reset()
        self._js("window.chatReset(%s);" % json.dumps(self._empty_text))

    # ---------------------------------------------------------------- envoi
    def ask(self, text: str, autosend: bool = True) -> None:
        """Pre-remplit (et envoie) une question depuis l'exterieur."""
        self.composer.setPlainText(text)
        if autosend:
            self.send()
        else:
            self.composer.setFocus()

    def send(self) -> None:
        if self.session is None or self.worker is not None:
            return
        text = self.composer.toPlainText().strip()
        if not text:
            return
        self.composer.clear()
        self._js("window.chatAdd('user', %s);" % json.dumps(html_mod.escape(text)))
        self.session.record_user(text)
        self._start(text)

    def send_hidden(self, prompt: str, shown: Optional[str] = None) -> None:
        """Envoie un prompt construit par l'app (affiche une version courte)."""
        if self.session is None or self.worker is not None:
            return
        if shown:
            self._js("window.chatAdd('user', %s);" % json.dumps(html_mod.escape(shown)))
        self.session.record_user(shown or prompt)
        self._start(prompt)

    def _start(self, prompt: str) -> None:
        self._js("window.chatBegin();")
        self.worker = ChatWorker(prompt, self.session.model, self.session.system,
                                 self.session.session_id, self)
        self.worker.delta.connect(self._on_delta)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._cleanup)
        self._set_busy(True)
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("..." if busy else "Envoyer")
        self.btn_stop.setVisible(busy)
        self.busy_changed.emit(busy)

    def _on_delta(self, chunk: str) -> None:
        self._js("window.chatDelta(%s);" % json.dumps(chunk))

    def _on_done(self, text: str, session_id: str) -> None:
        answer = clean_answer(text)
        self._js("window.chatFinalize(%s);" % json.dumps(answer))
        if self.session:
            self.session.record_assistant(answer, session_id)

    def _on_failed(self, message: str) -> None:
        self._js("window.chatError(%s);" % json.dumps(html_mod.escape(message)))

    def _cleanup(self) -> None:
        self.worker = None
        self._set_busy(False)

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait(2500)
            self.worker = None
        self._set_busy(False)

    @property
    def busy(self) -> bool:
        return self.worker is not None
