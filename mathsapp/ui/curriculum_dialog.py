"""Le cursus : choisir ses packs, régler son profil, en concevoir un nouveau."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import content, curriculum, curriculum_gen, settings, syllabus_extra
from ..generation import pipeline
from ..generation.claude_cli import ClaudeError
from ..syllabus import Syllabus
from . import theme

GOALS_PLACEHOLDER = (
    "Ce que vous voulez savoir faire à la fin, avec vos mots.\n\n"
    "Par exemple :\n"
    "  • comprendre la mécanique quantique jusqu'à l'intrication et aux bases\n"
    "    de l'information quantique, avec les calculs\n"
    "  • lire un article de recherche en physique quantique sans bloquer\n"
    "  • je n'ai fait que de la physique de lycée : il faut tout reprendre"
)

TARGETS = [
    ("Laisser Claude décider", ""),
    ("Licence", "niveau licence"),
    ("Master 1", "niveau master 1"),
    ("Master 2 / recherche", "niveau master 2, entrée en recherche"),
]


class DesignWorker(QThread):
    progress = Signal(str, float)
    done = Signal(dict, list, float)
    failed = Signal(str)

    def __init__(self, syl: Syllabus, brief: dict, size: int, parent=None):
        super().__init__(parent)
        self.syl = syl
        self.brief = brief
        self.size = size
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            pack, notes, cost = pipeline.design_curriculum(
                self.brief, self.size,
                on_progress=lambda label, frac: self.progress.emit(label, frac),
                cancel=lambda: self._stop, syl=self.syl)
            self.done.emit(pack, notes, cost)
        except InterruptedError:
            self.failed.emit("annulé")
        except (ClaudeError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("%s : %s" % (type(exc).__name__, exc))


class CurriculumDialog(QDialog):
    """Packs actifs, profil, et conception d'un nouveau cursus."""

    changed = Signal()

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.worker: Optional[DesignWorker] = None
        self.pack: Optional[dict] = None
        self.setWindowTitle("Cursus")
        self.setMinimumSize(940, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_packs(), "Mes packs")
        self.tabs.addTab(self._build_new(), "Nouveau cursus")
        root.addWidget(self.tabs)
        self._reload_packs()

    def show_new(self) -> None:
        self.tabs.setCurrentIndex(1)

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl

    # ------------------------------------------------------------ onglet 1
    def _build_packs(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        intro = QLabel(
            "Le cursus est fait de packs. Les mathématiques sont le socle, toujours "
            "actif ; chaque autre pack ajoute un domaine qui s'appuie dessus. "
            "Désactiver un pack le masque sans rien effacer : le contenu déjà généré "
            "reste sur le disque.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.packs = QTreeWidget()
        self.packs.setColumnCount(4)
        self.packs.setHeaderLabels(["Pack", "Cours", "Rédigés", "Origine"])
        self.packs.setRootIsDecorated(False)
        header = self.packs.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 70), (2, 80), (3, 110)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.packs.setColumnWidth(col, width)
        self.packs.itemChanged.connect(self._on_pack_toggled)
        self.packs.currentItemChanged.connect(lambda *_: self._sync_pack_buttons())
        lay.addWidget(self.packs, 1)

        self.pack_info = QLabel("")
        self.pack_info.setObjectName("Muted")
        self.pack_info.setWordWrap(True)
        lay.addWidget(self.pack_info)

        row = QHBoxLayout()
        self.btn_import = QPushButton("Importer un pack…")
        self.btn_import.clicked.connect(self._import)
        row.addWidget(self.btn_import)
        self.btn_export = QPushButton("Exporter…")
        self.btn_export.clicked.connect(self._export)
        row.addWidget(self.btn_export)
        self.btn_delete = QPushButton("Supprimer")
        self.btn_delete.clicked.connect(self._delete)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        lay.addLayout(row)

        prof_title = QLabel("Profil")
        prof_title.setObjectName("H2")
        lay.addWidget(prof_title)
        form = QFormLayout()
        prof = curriculum.profile()
        self.f_title = QLineEdit(prof["title"])
        self.f_title.setPlaceholderText("Nom affiché en haut de la fenêtre")
        form.addRow("Nom affiché", self.f_title)
        self.f_start = QLineEdit(prof["start_level"])
        self.f_start.setPlaceholderText("Par exemple : fin de lycée, spécialité maths et physique")
        form.addRow("Niveau de départ", self.f_start)
        self.f_about = QLineEdit(prof.get("about", ""))
        self.f_about.setPlaceholderText(
            "Facultatif : ce que les cours doivent savoir de vous (rythme, manière d'apprendre…)")
        form.addRow("À propos de vous", self.f_about)
        lay.addLayout(form)
        hint = QLabel("Le niveau de départ et ce que vous dites de vous sont repris dans "
                      "toutes les consignes de génération (cours, exercices, chat).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        save = QPushButton("Enregistrer le profil")
        save.setProperty("primary", True)
        save.clicked.connect(self._save_profile)
        actions.addWidget(save)
        lay.addLayout(actions)
        return page

    def _reload_packs(self) -> None:
        pal = theme.palette()
        active = set(curriculum.active_ids())
        self.packs.blockSignals(True)
        self.packs.clear()
        for pid, pack in curriculum.available().items():
            item = QTreeWidgetItem(self.packs)
            item.setData(0, Qt.ItemDataRole.UserRole, pid)
            item.setText(0, pack["title"])
            item.setToolTip(0, pack.get("description") or pack["title"])
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if pid == curriculum.BASE_PACK:
                flags &= ~Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            item.setCheckState(0, Qt.CheckState.Checked if pid in active
                               else Qt.CheckState.Unchecked)
            ids = [c["id"] for c in pack["courses"]]
            item.setText(1, str(len(ids)))
            written = sum(1 for cid in ids if content.is_complete(cid))
            item.setText(2, str(written))
            item.setText(3, "intégré" if pack["builtin"] else "créé / importé")
            for col in (1, 2, 3):
                item.setForeground(col, QColor(pal["muted"]))
        self.packs.blockSignals(False)
        self._sync_pack_buttons()

    def _current_pack(self) -> Optional[dict]:
        item = self.packs.currentItem()
        return curriculum.get_pack(item.data(0, Qt.ItemDataRole.UserRole)) if item else None

    def _sync_pack_buttons(self) -> None:
        pack = self._current_pack()
        self.btn_export.setEnabled(pack is not None)
        self.btn_delete.setEnabled(bool(pack and not pack["builtin"]))
        if pack is None:
            self.pack_info.setText("")
            return
        bits = [pack.get("description") or ""]
        if pack.get("goal"):
            bits.append("Objectif : %s." % pack["goal"])
        if pack.get("requires"):
            names = [curriculum.get_pack(r)["title"] if curriculum.get_pack(r) else r
                     for r in pack["requires"]]
            bits.append("S'appuie sur : %s." % ", ".join(names))
        self.pack_info.setText("  ".join(b for b in bits if b))

    def _on_pack_toggled(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        active = list(curriculum.active_ids())
        if item.checkState(0) == Qt.CheckState.Checked:
            active.append(pid)
        else:
            dependents = curriculum.dependents_of(pid)
            if dependents:
                names = ", ".join(curriculum.get_pack(d)["title"] for d in dependents)
                if QMessageBox.question(
                        self, "Désactiver un pack",
                        "Ces packs s'appuient sur celui-ci et seront aussi désactivés : "
                        "%s. Continuer ?" % names,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                ) != QMessageBox.StandardButton.Yes:
                    self._reload_packs()
                    return
            drop = {pid, *dependents}
            active = [p for p in active if p not in drop]
        curriculum.set_active(active)
        self._reload_packs()
        self.changed.emit()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un pack", "",
                                              "Pack de cours (*.json)")
        if not path:
            return
        try:
            pid = curriculum.import_pack(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import impossible", str(exc))
            return
        curriculum.set_active(curriculum.active_ids() + [pid])
        self._reload_packs()
        self.changed.emit()

    def _export(self) -> None:
        pack = self._current_pack()
        if pack is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le pack",
                                              "%s.json" % pack["id"], "Pack de cours (*.json)")
        if path:
            curriculum.export_pack(pack["id"], path)

    def _delete(self) -> None:
        pack = self._current_pack()
        if not pack or pack["builtin"]:
            return
        if QMessageBox.question(
                self, "Supprimer un pack",
                "Supprimer le pack « %s » ?\n\nLe contenu déjà généré pour ses cours "
                "reste sur le disque, dans library/, et sera réutilisé si vous "
                "réimportez le pack." % pack["title"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        curriculum.delete_pack(pack["id"])
        self._reload_packs()
        self.changed.emit()

    def _save_profile(self) -> None:
        curriculum.set_profile(title=self.f_title.text(), start_level=self.f_start.text(),
                               about=self.f_about.text())
        self.changed.emit()

    # ------------------------------------------------------------ onglet 2
    def _build_new(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        intro = QLabel(
            "Claude conçoit un cursus complet à partir de vos objectifs : les domaines, "
            "les cours dans l'ordre, les prérequis (branchés sur les maths déjà "
            "présentes), les parcours. Les fondations qui manquent sont ajoutées. "
            "Rien n'est enregistré avant que vous l'ayez relu ; les cours eux-mêmes "
            "se génèrent ensuite comme les autres.")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self.n_subject = QLineEdit()
        self.n_subject.setPlaceholderText("Physique quantique, chimie organique, "
                                          "neurosciences computationnelles…")
        form.addRow("Domaine", self.n_subject)
        self.n_goals = QPlainTextEdit()
        self.n_goals.setPlaceholderText(GOALS_PLACEHOLDER)
        self.n_goals.setFixedHeight(110)
        form.addRow("Objectifs", self.n_goals)
        self.n_start = QLineEdit(curriculum.profile()["start_level"])
        form.addRow("Niveau de départ", self.n_start)
        row = QHBoxLayout()
        self.n_target = QComboBox()
        for label, value in TARGETS:
            self.n_target.addItem(label, value)
        row.addWidget(self.n_target, 1)
        row.addWidget(QLabel("Taille"))
        self.n_size = QSpinBox()
        self.n_size.setRange(8, 150)
        self.n_size.setValue(40)
        self.n_size.setSuffix(" cours environ")
        row.addWidget(self.n_size)
        form.addRow("Niveau visé", row)
        self.n_notes = QLineEdit()
        self.n_notes.setPlaceholderText("Facultatif : à inclure, à laisser de côté, "
                                        "manuels ou cours à suivre…")
        form.addRow("Remarques", self.n_notes)
        lay.addLayout(form)

        bar = QHBoxLayout()
        self.n_status = QLabel("")
        self.n_status.setObjectName("Muted")
        self.n_status.setWordWrap(True)
        bar.addWidget(self.n_status, 1)
        self.btn_design = QPushButton("Concevoir le cursus")
        self.btn_design.setProperty("primary", True)
        self.btn_design.clicked.connect(self.design)
        bar.addWidget(self.btn_design)
        lay.addLayout(bar)

        self.n_progress = QProgressBar()
        self.n_progress.setRange(0, 1000)
        self.n_progress.setTextVisible(False)
        self.n_progress.setVisible(False)
        lay.addWidget(self.n_progress)

        self.preview = QTreeWidget()
        self.preview.setColumnCount(3)
        self.preview.setHeaderLabels(["Cours proposé", "Niveau", "Prérequis"])
        header = self.preview.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview.setColumnWidth(1, 70)
        lay.addWidget(self.preview, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.btn_save = QPushButton("Enregistrer et activer")
        self.btn_save.setProperty("primary", True)
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save)
        actions.addWidget(self.btn_save)
        lay.addLayout(actions)
        return page

    def design(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.btn_design.setEnabled(False)
            self.n_status.setText("Arrêt en cours…")
            return
        subject = self.n_subject.text().strip()
        if len(subject) < 3:
            self.n_subject.setFocus()
            self.n_status.setText("Indiquez le domaine du cursus.")
            return
        brief = {
            "subject": subject,
            "goals": self.n_goals.toPlainText().strip(),
            "start_level": self.n_start.text().strip(),
            "target_level": self.n_target.currentData() or "",
            "notes": self.n_notes.text().strip(),
        }
        self.pack = None
        self.preview.clear()
        self.btn_save.setEnabled(False)
        self.btn_design.setText("Arrêter")
        self.n_progress.setVisible(True)
        self.n_progress.setValue(0)
        self.n_status.setText("Modèle : %s. Comptez quelques minutes : un appel pour "
                              "l'architecture, puis un par domaine." % settings.get("model/course"))
        self.worker = DesignWorker(self.syl, brief, self.n_size.value(), self)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(lambda msg: self.n_status.setText("Échec : %s" % msg))
        self.worker.finished.connect(self._cleanup)
        self.worker.start()

    def _on_progress(self, label: str, frac: float) -> None:
        self.n_progress.setValue(int(frac * 1000))
        self.n_status.setText(label)

    def _cleanup(self) -> None:
        self.worker = None
        self.btn_design.setEnabled(True)
        self.btn_design.setText("Concevoir le cursus")
        self.n_progress.setVisible(False)

    def _on_done(self, pack: dict, notes: list, cost: float) -> None:
        pal = theme.palette()
        self.pack = pack
        self.preview.clear()
        titles = {c["id"]: c["title"] for c in pack["courses"]}
        for d in pack["domains"]:
            group = QTreeWidgetItem(self.preview)
            courses = [c for c in pack["courses"] if c["domain"] == d["id"]]
            group.setText(0, "%s  (%d)" % (d["name"], len(courses)))
            group.setToolTip(0, d.get("description", ""))
            group.setForeground(0, QColor(d["color"]))
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            group.setExpanded(True)
            for c in courses:
                item = QTreeWidgetItem(group)
                item.setText(0, c["title"])
                item.setToolTip(0, "%s\n\n%s\n\n%s"
                                % (c["id"], c["summary"], " · ".join(c["objectives"])))
                item.setText(1, str(c["level"]))
                names = [titles.get(p) or self.syl.title(p) for p in c["prereqs"]]
                item.setText(2, ", ".join(names) or "aucun")
                item.setForeground(2, QColor(pal["muted"]))
        errors = curriculum_gen.check(pack, syllabus_extra.merged())
        s = curriculum_gen.summary(pack)
        text = "« %s » : %d domaines, %d cours, %d parcours" % (
            pack["title"], s["domains"], s["courses"], s["tracks"])
        if cost:
            text += "  ·  %.2f $" % cost
        if pack.get("notes"):
            text += "\n" + pack["notes"]
        if notes:
            text += "\nCorrigé : " + " ; ".join(notes[:4])
            if len(notes) > 4:
                text += " (+%d)" % (len(notes) - 4)
        if errors:
            text += "\n" + "\n".join(errors)
        self.n_status.setText(text)
        self.btn_save.setEnabled(not errors)

    def save(self) -> None:
        if not self.pack:
            return
        try:
            pid = curriculum.save_pack(self.pack)
        except ValueError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
            return
        curriculum.set_active(curriculum.active_ids() + [pid])
        self.n_status.setText(
            "Cursus « %s » enregistré et activé. Ses parcours sont sur l'accueil ; "
            "générez les cours depuis la bibliothèque ou le bouton « Générer » d'un "
            "parcours." % self.pack["title"])
        self.pack = None
        self.btn_save.setEnabled(False)
        self.preview.clear()
        self._reload_packs()
        self.changed.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None:
            self.worker.request_stop()
            self.worker.wait(2000)
        super().closeEvent(event)
