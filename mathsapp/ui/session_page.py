"""Séance de travail transversale : révisions, quiz du jour, défi éclair.

Ces séances portent sur plusieurs cours à la fois, contrairement au QCM d'un
cours. On réutilise la même page web, alimentée par une série synthétique dont
chaque question porte son cours d'origine.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import content
from ..paths import ASSETS_DIR, library_dir
from ..syllabus import Syllabus
from . import theme
from .webview import WebView

KIND_TITLE = {
    "review": "Révisions du jour",
    "daily": "Quiz du jour",
    "challenge": "Défi éclair",
}
KIND_HINT = {
    "review": "Les questions dont c'est le moment, toutes matières confondues. "
              "Une réponse juste repousse la question ; une erreur la ramène.",
    "daily": "Vingt questions neuves réparties sur plusieurs chapitres déjà "
             "travaillés, comme dans un examen.",
    "challenge": "Cinq questions déjà vues, chronométrées. Il y a un record à battre.",
}


class SessionPage(QWidget):
    finished = Signal(str, str)      # kind, charge utile JSON
    leave = Signal()

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.kind = "review"
        self._questions: List[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 14, 10)
        bl.setSpacing(10)
        self.title = QLabel("")
        self.title.setObjectName("H2")
        bl.addWidget(self.title)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        bl.addWidget(self.hint, 1)
        back = QPushButton("Quitter la séance")
        back.setProperty("flat", True)
        back.clicked.connect(self.leave.emit)
        bl.addWidget(back)
        root.addWidget(bar)

        self.view = WebView(with_bridge=True)
        self.view.bridge.quiz_finished.connect(self._on_finished)
        self.view.bridge.ask_requested.connect(lambda *_: None)
        root.addWidget(self.view, 1)

    # ------------------------------------------------------------- session
    def start(self, kind: str, questions: List[dict],
              history: Optional[Dict[str, dict]] = None,
              timed: bool = False) -> None:
        self.kind = kind
        self._questions = questions
        self.title.setText(KIND_TITLE.get(kind, "Séance"))
        self.hint.setText(KIND_HINT.get(kind, ""))

        set_id = "%s:%s" % (kind, questions[0].get("day", "")) if questions else kind
        sets = [{"id": set_id, "title": KIND_TITLE.get(kind, "Séance"),
                 "qcm": questions}]
        tpl = (ASSETS_DIR / "quiz.html").read_text(encoding="utf-8")
        page = (tpl.replace("__THEME__", theme.name())
                   .replace("__ASSETS__", content.assets_url())
                   .replace("__SETS__", json.dumps(sets, ensure_ascii=False))
                   .replace("__HISTORY__", json.dumps({set_id: history or {}},
                                                      ensure_ascii=False)))
        # Le script de la page lit window.SESSION des son premier passage : il
        # faut donc la definir AVANT lui, dans l'en-tete.
        extra = ("<script>window.SESSION = %s;</script>\n"
                 % json.dumps({"kind": kind, "timed": bool(timed),
                               "autostart": True}, ensure_ascii=False))
        page = page.replace("</head>", extra + "</head>", 1)
        d = library_dir() / "_views"
        d.mkdir(parents=True, exist_ok=True)
        path = d / ("session_%s.html" % kind)
        path.write_text(page, encoding="utf-8")
        self.view.load_file(path)

    def _on_finished(self, payload: str) -> None:
        self.finished.emit(self.kind, payload)

    def apply_theme(self) -> None:
        self.view.set_theme(theme.name())
