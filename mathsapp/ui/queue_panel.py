"""Panneau de la file de generation."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..generation.queue import (
    CANCELLED, DONE, ERROR, KIND_LABEL, QUEUED, RUNNING, GenerationQueue,
)
from . import theme


class QueuePanel(QWidget):
    course_opened = Signal(str)

    def __init__(self, queue: GenerationQueue, parent=None):
        super().__init__(parent)
        self.queue = queue
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(8)
        self.summary = QLabel("Aucune generation en cours")
        self.summary.setObjectName("Muted")
        bl.addWidget(self.summary)
        bl.addStretch(1)
        btn_clear = QPushButton("Effacer les terminees")
        btn_clear.setProperty("flat", True)
        btn_clear.clicked.connect(self.queue.clear_finished)
        bl.addWidget(btn_clear)
        self.btn_cancel = QPushButton("Tout annuler")
        self.btn_cancel.setProperty("flat", True)
        self.btn_cancel.clicked.connect(self.queue.cancel_all)
        bl.addWidget(self.btn_cancel)
        root.addWidget(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Cours", "Type", "Etape", "Avancement"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(
            lambda item, _c: self.course_opened.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 130)
        self.tree.setColumnWidth(3, 150)
        root.addWidget(self.tree, 1)

        self.queue.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        pal = theme.palette()
        self.tree.clear()
        for job in reversed(self.queue.jobs):
            item = QTreeWidgetItem(self.tree)
            item.setData(0, Qt.ItemDataRole.UserRole, job.course_id)
            item.setText(0, job.title)
            item.setText(1, KIND_LABEL.get(job.kind, job.kind))
            item.setForeground(1, QColor(pal["muted"]))
            item.setText(2, job.error or job.label)
            colors = {RUNNING: pal["accent"], DONE: pal["ok"], ERROR: pal["err"],
                      CANCELLED: pal["muted"], QUEUED: pal["muted"]}
            item.setForeground(2, QColor(colors.get(job.state, pal["fg2"])))
            if job.error:
                item.setToolTip(2, job.error)
            if job.state == RUNNING:
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setValue(int(job.progress * 1000))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                self.tree.setItemWidget(item, 3, bar)
            else:
                labels = {DONE: "termine", ERROR: "echec", CANCELLED: "annule", QUEUED: "en attente"}
                item.setText(3, labels.get(job.state, ""))
                item.setForeground(3, QColor(pal["muted"]))

        active = self.queue.active_count()
        self.summary.setText("Aucune generation en cours" if not active
                             else "%d generation%s en cours ou en attente"
                                  % (active, "s" if active > 1 else ""))
        self.btn_cancel.setEnabled(active > 0)
