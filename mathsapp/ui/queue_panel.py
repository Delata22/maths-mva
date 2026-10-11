"""Panneau de la file de generation."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMenu, QProgressBar, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..generation.queue import (
    CANCELLED, DONE, ERROR, KIND_LABEL, QUEUED, RUNNING, GenerationQueue, kind_label,
)

HEALTH_COLOR = {"vivant": "ok", "lent": "warn", "muet": "err", "inactif": "muted"}


def _age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "%d s" % seconds
    return "%d min %02d" % (seconds // 60, seconds % 60)
from . import theme


class QueuePanel(QWidget):
    course_opened = Signal(str)
    retried = Signal()
    hide_requested = Signal()      # « Masquer » : la file se replie en pastille

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
        self.summary = QLabel("Aucune génération en cours")
        self.summary.setObjectName("Muted")
        bl.addWidget(self.summary)
        bl.addStretch(1)
        self.btn_retry = QPushButton("Relancer les échecs")
        self.btn_retry.setProperty("primary", True)
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(self._retry_failed)
        bl.addWidget(self.btn_retry)
        btn_clear = QPushButton("Effacer les terminées")
        btn_clear.setProperty("flat", True)
        btn_clear.clicked.connect(self.queue.clear_finished)
        bl.addWidget(btn_clear)
        self.btn_cancel = QPushButton("Tout annuler")
        self.btn_cancel.setProperty("flat", True)
        self.btn_cancel.clicked.connect(self.queue.cancel_all)
        bl.addWidget(self.btn_cancel)
        self.btn_hide = QPushButton("Masquer")
        self.btn_hide.setProperty("flat", True)
        self.btn_hide.setToolTip("Replier la file en pastille dans l'en-tête. Les générations "
                                 "continuent en arrière-plan.  (Ctrl+G)")
        self.btn_hide.clicked.connect(self.hide_requested.emit)
        bl.addWidget(self.btn_hide)
        root.addWidget(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Cours", "Type", "Étape", "Activité", "Avancement"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(
            lambda item, _c: self.course_opened.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 130)
        self.tree.setColumnWidth(3, 170)
        self.tree.setColumnWidth(4, 150)
        root.addWidget(self.tree, 1)

        # Le temps passe meme quand rien n'arrive : sans ce battement, l'age du
        # dernier signe de vie resterait fige et on ne saurait pas si ca avance.
        self._tick = QTimer(self)
        self._tick.setInterval(2000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self.queue.changed.connect(self.refresh)
        self.refresh()

    def _on_tick(self) -> None:
        if self.queue.running_jobs():
            self.refresh()

    def _retry(self, course_id: str, kind: str) -> None:
        self.queue.retry(course_id, kind)
        self.retried.emit()

    def _retry_failed(self) -> None:
        if self.queue.retry_failed():
            self.retried.emit()

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        course_id = item.data(0, Qt.ItemDataRole.UserRole)
        kind = item.data(1, Qt.ItemDataRole.UserRole) or "course"
        menu = QMenu(self)
        act = QAction("Ouvrir le cours", self)
        act.triggered.connect(lambda: self.course_opened.emit(course_id))
        menu.addAction(act)
        act = QAction("Relancer", self)
        act.triggered.connect(lambda: self._retry(course_id, kind))
        menu.addAction(act)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def refresh(self) -> None:
        pal = theme.palette()
        self.tree.clear()
        # Ce qui tourne d'abord, puis ce qui attend dans l'ordre de la file,
        # puis les echecs, puis les terminees les plus recentes.
        rank = {RUNNING: 0, QUEUED: 1, ERROR: 2, CANCELLED: 3, DONE: 4}
        order = list(enumerate(self.queue.jobs))
        order.sort(key=lambda pair: (rank.get(pair[1].state, 5),
                                     pair[0] if pair[1].active else -pair[0]))
        for _index, job in order:
            item = QTreeWidgetItem(self.tree)
            item.setData(0, Qt.ItemDataRole.UserRole, job.course_id)
            item.setText(0, job.title)
            item.setData(1, Qt.ItemDataRole.UserRole, job.kind)
            item.setText(1, kind_label(job.kind))
            item.setForeground(1, QColor(pal["muted"]))
            item.setText(2, job.error or job.label)
            colors = {RUNNING: pal["accent"], DONE: pal["ok"], ERROR: pal["err"],
                      CANCELLED: pal["muted"], QUEUED: pal["muted"]}
            item.setForeground(2, QColor(colors.get(job.state, pal["fg2"])))
            if job.error:
                item.setToolTip(2, job.error)
            if job.state == RUNNING:
                health = job.health
                mark = {"vivant": "●", "lent": "●", "muet": "▲"}.get(health, "●")
                if health == "vivant":
                    text = "%s  actif il y a %s" % (mark, _age(job.silent_for))
                elif health == "lent":
                    text = "%s  rien depuis %s" % (mark, _age(job.silent_for))
                else:
                    text = "%s  muet depuis %s" % (mark, _age(job.silent_for))
                status, reason = self.queue.explain(job)
                tip = ("Démarré il y a %s.\nDernier signe de vie il y a %s."
                       % (_age(job.elapsed), _age(job.silent_for)))
                if status == "en pause":
                    text = "en pause : %s" % reason
                    tip += "\n%s" % job.last_notice if job.last_notice else ""
                item.setText(3, text)
                item.setForeground(3, QColor(pal["warn" if status == "en pause"
                                                 else HEALTH_COLOR[health]]))
                item.setToolTip(3, tip)
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setValue(int(job.progress * 1000))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                self.tree.setItemWidget(item, 4, bar)
            elif job.state in (ERROR, CANCELLED):
                button = QPushButton("Relancer")
                button.setProperty("flat", True)
                button.clicked.connect(
                    lambda _=False, c=job.course_id, k=job.kind: self._retry(c, k))
                self.tree.setItemWidget(item, 4, button)
            else:
                labels = {DONE: "terminé", QUEUED: "en attente"}
                item.setText(4, labels.get(job.state, ""))
                item.setForeground(4, QColor(pal["muted"]))
                if job.state == QUEUED:
                    item.setToolTip(4, self.queue.explain(job)[1])
                if job.state == DONE and job.elapsed:
                    item.setText(3, "en %s" % _age(job.elapsed))
                    item.setForeground(3, QColor(pal["muted"]))

        active = self.queue.active_count()
        failed = sum(1 for j in self.queue.jobs if j.state == ERROR)
        if active:
            text = "%d génération%s en cours ou en attente" % (active, "s" if active > 1 else "")
            health, silence, _job = self.queue.health()
            if health == "muet":
                text += "  ·  plus aucun signe de vie depuis %s" % _age(silence)
            elif health == "lent":
                text += "  ·  dernier signe de vie il y a %s" % _age(silence)
        else:
            text = "Aucune génération en cours"
        if failed:
            text += "  ·  %d échec%s" % (failed, "s" if failed > 1 else "")
        self.summary.setText(text)
        self.btn_cancel.setEnabled(active > 0)
        self.btn_retry.setVisible(failed > 0)
        self.btn_retry.setText("Relancer %s" % ("l'échec" if failed == 1 else "les %d échecs" % failed))
