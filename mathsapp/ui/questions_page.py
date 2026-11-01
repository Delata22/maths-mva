"""Questions libres : une question, une réponse, et les cours qui en parlent."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from .. import questions, store
from ..syllabus import Syllabus
from .chat_panel import ChatPanel


class QuestionsPage(QWidget):
    course_opened = Signal(str, str)     # cours, section

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self._key: Optional[str] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 8, 12)
        lv.setSpacing(8)
        head = QLabel("Questions")
        head.setObjectName("H2")
        lv.addWidget(head)
        hint = QLabel("Une question sur le cursus, n'importe laquelle. La réponse indique "
                      "les cours du cursus qui la traitent.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lv.addWidget(hint)
        btn_new = QPushButton("Nouvelle question")
        btn_new.setProperty("primary", True)
        btn_new.clicked.connect(self.new_question)
        lv.addWidget(btn_new)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSpacing(2)
        self.list.currentItemChanged.connect(self._on_item)
        lv.addWidget(self.list, 1)
        self.btn_delete = QPushButton("Supprimer la question")
        self.btn_delete.setProperty("flat", True)
        self.btn_delete.clicked.connect(self._delete)
        lv.addWidget(self.btn_delete)
        splitter.addWidget(left)

        self.panel = ChatPanel(syllabus)
        self.panel.btn_clear.setVisible(False)     # la suppression passe par la liste
        self.panel.composer.setPlaceholderText(
            "Votre question  (Entrée pour envoyer, Maj+Entrée pour un saut de ligne)")
        self.panel.course_opened.connect(self.course_opened.emit)
        self.panel.busy_changed.connect(lambda _busy: self.refresh_list())
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1000])

    # ---------------------------------------------------------------- fils
    def refresh(self) -> None:
        keep = self.panel.session.thread_id if self.panel.session else None
        store.delete_empty_threads(questions.PREFIX, keep)
        self.refresh_list()
        if self._key is None:
            rows = questions.threads()
            if rows:
                self._open(rows[0]["context_key"], rows[0]["title"])
            else:
                self.new_question()

    def refresh_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for row in questions.threads():
            when = dt.datetime.fromtimestamp(row["updated_at"]).strftime("%d/%m %H:%M")
            item = QListWidgetItem("%s\n%s" % (row["title"] or "Question", when))
            item.setData(Qt.ItemDataRole.UserRole, row["context_key"])
            item.setToolTip(row["title"] or "")
            self.list.addItem(item)
            if row["context_key"] == self._key:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        has_messages = bool(self.panel.session and self.panel.session.history())
        self.btn_delete.setEnabled(has_messages)

    def new_question(self) -> None:
        self._open(questions.new_key(), "Nouvelle question")
        self.list.clearSelection()
        self.panel.composer.setFocus()

    def _open(self, key: str, title: str) -> None:
        self._key = key
        self.panel.set_context(None, key, mode="question", title=title)
        self.btn_delete.setEnabled(bool(self.panel.session.history()))

    def _on_item(self, item, _previous=None) -> None:
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key and key != self._key:
            self._open(key, item.toolTip() or "Question")

    def _delete(self) -> None:
        session = self.panel.session
        if session is None or not session.history():
            return
        if QMessageBox.question(
                self, "Supprimer la question", "Supprimer cette question et sa réponse ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        self.panel.stop()
        store.delete_thread(session.thread_id)
        self._key = None
        self.panel.session = None
        self.refresh()

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl
        self.panel.syl = syl

    def apply_theme(self) -> None:
        self.panel.apply_theme()
