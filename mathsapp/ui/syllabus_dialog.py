"""Créer de nouveaux cours dans le syllabus, depuis l'application."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import content, settings, syllabus_extra
from ..generation import pipeline
from ..generation.claude_cli import ClaudeError
from ..syllabus import Syllabus
from . import theme

PLACEHOLDER = (
    "Décrivez ce que vous voulez couvrir.\n\n"
    "Par exemple :\n"
    "  • les séries temporelles, de la stationnarité aux modèles d'état\n"
    "  • la théorie des jeux algorithmique pour l'apprentissage multi-agents\n"
    "  • tout ce qu'il faut sur les EDP pour l'imagerie médicale\n"
    "  • approfondir la théorie de la mesure jusqu'aux processus ponctuels"
)

LEVELS = [
    ("Laisser Claude décider", None),
    ("Fondations (post-bac)", "fondations, accessible juste apres le lycee"),
    ("Licence", "niveau licence"),
    ("Master 1", "niveau master 1"),
    ("Master 2 / MVA", "niveau master 2, recherche"),
]


class ProposalWorker(QThread):
    progress = Signal(str, float)
    done = Signal(dict, list, str)
    failed = Signal(str)

    def __init__(self, syl: Syllabus, request: str, count: int,
                 domain: Optional[str], level: Optional[str], parent=None):
        super().__init__(parent)
        self.syl = syl
        self.request = request
        self.count = count
        self.domain = domain
        self.level = level
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            batch, notes, summary = pipeline.propose_syllabus(
                self.request, self.count, self.domain, self.level,
                on_progress=lambda label, frac: self.progress.emit(label, frac),
                cancel=lambda: self._stop, syl=self.syl,
            )
            self.done.emit(batch, notes, summary)
        except ClaudeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("%s : %s" % (type(exc).__name__, exc))


class SyllabusDialog(QDialog):
    """Proposer, relire, puis ajouter des cours au syllabus."""

    changed = Signal()

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.worker: Optional[ProposalWorker] = None
        self.batch: Dict[str, list] = {}
        self.setWindowTitle("Étendre le syllabus")
        self.setMinimumSize(900, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_new(), "Proposer des cours")
        self.tabs.addTab(self._build_mine(), "Mes ajouts")
        self.tabs.currentChanged.connect(
            lambda i: self._reload_mine() if i == 1 else None)
        root.addWidget(self.tabs)

    # ------------------------------------------------------------ onglet 1
    def _build_new(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        intro = QLabel(
            "Claude conçoit une série de cours cohérente et la branche sur les "
            "prérequis déjà présents dans le cursus. Rien n'est ajouté avant que "
            "vous l'ayez relu.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.request = QPlainTextEdit()
        self.request.setPlaceholderText(PLACEHOLDER)
        self.request.setFixedHeight(120)
        lay.addWidget(self.request)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Domaine"))
        self.domain = QComboBox()
        self.domain.addItem("Nouveau domaine", None)
        for did in self.syl.domain_order:
            self.domain.addItem(self.syl.domain_name(did), did)
        row.addWidget(self.domain, 1)

        row.addWidget(QLabel("Cours"))
        self.count = QSpinBox()
        self.count.setRange(3, 24)
        self.count.setValue(10)
        row.addWidget(self.count)

        row.addWidget(QLabel("Niveau"))
        self.level = QComboBox()
        for label, value in LEVELS:
            self.level.addItem(label, value)
        row.addWidget(self.level, 1)

        self.btn_propose = QPushButton("Proposer")
        self.btn_propose.setProperty("primary", True)
        self.btn_propose.clicked.connect(self.propose)
        row.addWidget(self.btn_propose)
        lay.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Cours proposé", "Niveau", "Domaine", "Prérequis"])
        self.tree.setRootIsDecorated(False)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 190)
        self.tree.itemChanged.connect(lambda *_: self._sync_add_button())
        lay.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_toggle = QPushButton("Tout décocher")
        self.btn_toggle.setProperty("flat", True)
        self.btn_toggle.setEnabled(False)
        self.btn_toggle.clicked.connect(self._toggle_all)
        actions.addWidget(self.btn_toggle)
        actions.addStretch(1)
        self.btn_close = QPushButton("Fermer")
        self.btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_close)
        self.btn_add = QPushButton("Ajouter au syllabus")
        self.btn_add.setProperty("primary", True)
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self.commit)
        actions.addWidget(self.btn_add)
        lay.addLayout(actions)
        return page

    # ------------------------------------------------------------ onglet 2
    def _build_mine(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        self.mine_intro = QLabel("")
        self.mine_intro.setObjectName("Muted")
        self.mine_intro.setWordWrap(True)
        lay.addWidget(self.mine_intro)

        self.mine = QTreeWidget()
        self.mine.setColumnCount(3)
        self.mine.setHeaderLabels(["Cours ajouté", "Niveau", "Contenu généré"])
        self.mine.setRootIsDecorated(True)
        self.mine.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        header = self.mine.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.mine.setColumnWidth(1, 70)
        self.mine.setColumnWidth(2, 150)
        lay.addWidget(self.mine, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_remove = QPushButton("Retirer du syllabus")
        self.btn_remove.clicked.connect(self._remove_selected)
        row.addWidget(self.btn_remove)
        lay.addLayout(row)
        return page

    def _reload_mine(self) -> None:
        pal = theme.palette()
        extra = syllabus_extra.read_extra()
        self.mine.clear()
        courses = extra["courses"]
        self.mine_intro.setText(
            "Aucun cours ajouté pour l'instant."
            if not courses else
            "%d cours ajoutés depuis l'application. Ils vivent dans "
            "library/syllabus_extra.json et survivent aux mises à jour du "
            "syllabus de base." % len(courses))
        by_domain: Dict[str, List[dict]] = {}
        for c in courses:
            by_domain.setdefault(c["domain"], []).append(c)
        for did, items in by_domain.items():
            group = QTreeWidgetItem(self.mine)
            group.setText(0, self.syl.domain_name(did))
            group.setForeground(0, QColor(self.syl.domain_color(did)))
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            group.setExpanded(True)
            for c in items:
                item = QTreeWidgetItem(group)
                item.setData(0, Qt.ItemDataRole.UserRole, c["id"])
                item.setText(0, c["title"])
                item.setText(1, str(c["level"]))
                state = content.generation_state(c["id"])
                item.setText(2, "oui" if state["complete"]
                             else ("partiel" if state["partial"] else "non"))
                item.setForeground(2, QColor(pal["muted"]))
        self.btn_remove.setEnabled(bool(courses))

    def _remove_selected(self) -> None:
        ids = [i.data(0, Qt.ItemDataRole.UserRole) for i in self.mine.selectedItems()]
        ids = [i for i in ids if i]
        if not ids:
            QMessageBox.information(self, "Retirer du syllabus",
                                    "Sélectionnez d'abord les cours à retirer.")
            return
        generated = [i for i in ids if content.generation_state(i)["started"]]
        message = "Retirer %d cours du syllabus ?" % len(ids)
        if generated:
            message += ("\n\n%d d'entre eux ont du contenu généré. Il reste sur le "
                        "disque dans library/ et sera réutilisé si vous les "
                        "recréez." % len(generated))
        if QMessageBox.question(
                self, "Retirer du syllabus", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        syllabus_extra.remove_courses(ids)
        self.changed.emit()
        self._reload_mine()

    # ----------------------------------------------------------- proposition
    def propose(self) -> None:
        request = self.request.toPlainText().strip()
        if len(request) < 8:
            self.request.setFocus()
            self.status.setText("Décrivez en une phrase au moins ce que vous voulez couvrir.")
            return
        if self.worker is not None:
            return
        self.tree.clear()
        self.batch = {}
        self.btn_add.setEnabled(False)
        self.btn_toggle.setEnabled(False)
        self.btn_propose.setEnabled(False)
        self.btn_propose.setText("…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText("Modèle : %s" % settings.get("model/course"))

        self.worker = ProposalWorker(
            self.syl, request, self.count.value(),
            self.domain.currentData(), self.level.currentData(), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._cleanup)
        self.worker.start()

    def _on_progress(self, label: str, frac: float) -> None:
        self.progress.setValue(int(frac * 1000))
        self.status.setText(label)

    def _cleanup(self) -> None:
        self.worker = None
        self.btn_propose.setEnabled(True)
        self.btn_propose.setText("Proposer")
        self.progress.setVisible(False)

    def _on_failed(self, message: str) -> None:
        self.status.setText("Échec : %s" % message)

    def _on_done(self, batch: dict, notes: list, summary: str) -> None:
        pal = theme.palette()
        self.batch = batch
        self.tree.clear()
        known = set(self.syl.courses)
        titles = {c["id"]: c["title"] for c in batch["courses"]}

        for c in batch["courses"]:
            item = QTreeWidgetItem(self.tree)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, c["id"])
            item.setText(0, c["title"])
            item.setToolTip(0, "%s\n\n%s\n\n%s"
                            % (c["id"], c["summary"], " · ".join(c["objectives"])))
            item.setText(1, str(c["level"]))
            domain_name = (self.syl.domain_name(c["domain"])
                           if c["domain"] in self.syl.domains
                           else next((d["name"] for d in batch["domains"]
                                      if d["id"] == c["domain"]), c["domain"]))
            item.setText(2, domain_name)
            names = [self.syl.title(p) if p in known else titles.get(p, p)
                     for p in c["prereqs"]]
            item.setText(3, ", ".join(names) if names else "aucun")
            item.setForeground(3, QColor(pal["muted"]))

        bits = []
        if batch["domains"]:
            bits.append("nouveau domaine : %s"
                        % ", ".join(d["name"] for d in batch["domains"]))
        bits.append("%d cours proposés" % len(batch["courses"]))
        if batch["tracks"]:
            bits.append("parcours : %s" % batch["tracks"][0]["title"])
        text = "  ·  ".join(bits)
        if summary:
            text += "\n" + summary
        if notes:
            text += "\n" + " ; ".join(notes[:4])
        self.status.setText(text)
        self.btn_toggle.setEnabled(bool(batch["courses"]))
        self._sync_add_button()

    # ---------------------------------------------------------------- ajout
    def _checked_ids(self) -> List[str]:
        return [self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]

    def _sync_add_button(self) -> None:
        n = len(self._checked_ids())
        self.btn_add.setEnabled(n > 0)
        self.btn_add.setText("Ajouter au syllabus" if n == 0
                             else "Ajouter %d cours" % n)

    def _toggle_all(self) -> None:
        target = (Qt.CheckState.Unchecked if self._checked_ids()
                  else Qt.CheckState.Checked)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, target)
        self.btn_toggle.setText("Tout cocher" if target == Qt.CheckState.Unchecked
                                else "Tout décocher")

    def commit(self) -> None:
        keep = set(self._checked_ids())
        if not keep:
            return
        courses = [dict(c) for c in self.batch["courses"] if c["id"] in keep]
        # un prerequis vers un cours decoche n'aurait plus de cible
        for c in courses:
            c["prereqs"] = [p for p in c["prereqs"]
                            if p in self.syl.courses or p in keep]
        used = {c["domain"] for c in courses}
        batch = {
            "domains": [d for d in self.batch["domains"] if d["id"] in used],
            "courses": courses,
            "tracks": [t for t in self.batch["tracks"]
                       if t["goal"] in keep or t["goal"] in self.syl.courses],
        }
        for t in batch["tracks"]:
            t["extra"] = [e for e in t["extra"] if e in keep or e in self.syl.courses]

        errors = syllabus_extra.add(batch)
        if errors:
            QMessageBox.warning(self, "Ajout impossible", "\n".join(errors))
            return
        self.changed.emit()
        self.status.setText("%d cours ajoutés au syllabus." % len(courses))
        self.tree.clear()
        self.batch = {}
        self.btn_add.setEnabled(False)
        self.btn_toggle.setEnabled(False)

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait(2000)
        super().closeEvent(event)
