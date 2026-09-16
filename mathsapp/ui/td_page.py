"""Sujets de TD : import, lecture et correction commentée."""
from __future__ import annotations

import pathlib
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .. import content, td as td_mod
from ..paths import library_dir
from ..syllabus import Syllabus
from . import theme
from .webview import WebView
from .widgets import FlowLayout


class TdPage(QWidget):
    course_opened = Signal(str)
    ask_requested = Signal(str, str, str)             # cours, extrait, section
    proof_help_requested = Signal(str, str, str, str)  # cours, id, titre, texte
    correct_requested = Signal(str)                    # identifiant du TD

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.td_id: Optional[str] = None
        self.index = 0
        self.statement_only = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 9, 14, 9)
        bl.setSpacing(9)
        self.picker = QComboBox()
        self.picker.setMinimumWidth(300)
        self.picker.currentIndexChanged.connect(self._on_pick)
        bl.addWidget(self.picker)
        btn_import = QPushButton("Importer un TD…")
        btn_import.clicked.connect(self._import)
        bl.addWidget(btn_import)
        bl.addStretch(1)
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        bl.addWidget(self.info)
        self.btn_correct = QPushButton("Lire et corriger")
        self.btn_correct.setProperty("primary", True)
        self.btn_correct.clicked.connect(
            lambda: self.correct_requested.emit(self.td_id) if self.td_id else None)
        bl.addWidget(self.btn_correct)
        self.btn_delete = QPushButton("Supprimer")
        self.btn_delete.setProperty("flat", True)
        self.btn_delete.clicked.connect(self._delete)
        bl.addWidget(self.btn_delete)
        root.addWidget(bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(270)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSpacing(2)
        self.list.currentRowChanged.connect(self._on_row)
        self.splitter.addWidget(self.list)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        head = QWidget()
        head.setObjectName("TopBar")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(16, 10, 14, 10)
        hv.setSpacing(7)
        line = QHBoxLayout()
        self.ex_title = QLabel("")
        self.ex_title.setObjectName("H2")
        self.ex_title.setWordWrap(True)
        self.ex_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        line.addWidget(self.ex_title, 1)
        self.btn_view = QPushButton("Énoncé seul")
        self.btn_view.setProperty("flat", True)
        self.btn_view.setToolTip("Masquer la correction pour chercher d'abord")
        self.btn_view.clicked.connect(self._toggle_view)
        line.addWidget(self.btn_view)
        hv.addLayout(line)
        self.chips = FlowLayout(spacing=6)
        self.chips.setSpacing(6)
        chips_host = QWidget()
        chips_host.setLayout(self.chips)
        hv.addWidget(chips_host)
        rv.addWidget(head)

        self.view = WebView(with_bridge=True)
        self.view.bridge.ask_requested.connect(self._ask)
        self.view.bridge.proof_help_requested.connect(self._proof_help)
        self.view.bridge.course_open_requested.connect(self.course_opened.emit)
        rv.addWidget(self.view, 1)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([360, 1040])
        root.addWidget(self.splitter, 1)

    # ------------------------------------------------------------- données
    def refresh(self) -> None:
        ids = td_mod.list_ids()
        if self.td_id not in ids:
            self.td_id = ids[0] if ids else None
            self.index = 0
        self.picker.blockSignals(True)
        self.picker.clear()
        for td_id in ids:
            self.picker.addItem(td_mod.title(td_id), td_id)
        if self.td_id:
            self.picker.setCurrentIndex(max(0, self.picker.findData(self.td_id)))
        self.picker.blockSignals(False)
        self._load()

    def open_td(self, td_id: str) -> None:
        self.td_id = td_id
        self.index = 0
        self.refresh()

    def _on_pick(self, _row: int) -> None:
        td_id = self.picker.currentData()
        if td_id and td_id != self.td_id:
            self.td_id = td_id
            self.index = 0
            self._load()

    def _load(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        self.list.blockSignals(False)
        has_td = self.td_id is not None
        self.btn_delete.setEnabled(has_td)
        self.btn_correct.setEnabled(has_td)
        if not has_td:
            self.info.setText("")
            self.ex_title.setText("Aucun TD importé")
            self._set_chips([])
            self._render("<h2>Sujets de TD</h2><p class=\"lead\">Importez un sujet en PDF : "
                         "l'application le lit, formules comprises, rattache chaque "
                         "exercice aux cours qui contiennent les résultats nécessaires, "
                         "et produit une correction commentée — l'idée avant les calculs, "
                         "la solution détaillée à déplier.</p>", "TD")
            return

        state = td_mod.state(self.td_id)
        if not state["structured"]:
            self.info.setText("sujet pas encore lu")
            self.btn_correct.setText("Lire et corriger")
        elif state["complete"]:
            self.info.setText("%d exercices, tous corrigés" % state["total"])
            self.btn_correct.setText("Corrigé")
            self.btn_correct.setEnabled(False)
        else:
            self.info.setText("%d/%d exercices corrigés" % (state["corrected"], state["total"]))
            self.btn_correct.setText("Reprendre la correction" if state["corrected"]
                                     else "Corriger")

        items = td_mod.exercises(self.td_id)
        pal = theme.palette()
        self.list.blockSignals(True)
        for i, ex in enumerate(items):
            done = td_mod.read_correction(self.td_id, i, td_mod.exercise_fingerprint(ex)) is not None
            item = QListWidgetItem("%s  Exercice %s — %s"
                                   % ("✓" if done else "○", ex.get("number", i + 1),
                                      ex.get("title", "")))
            item.setForeground(QColor(pal["fg"] if done else pal["muted"]))
            item.setToolTip("\n".join(ex.get("key_results") or []))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if items:
            self.index = min(self.index, len(items) - 1)
            self.list.setCurrentRow(self.index)
            self._show(self.index)
        else:
            self.ex_title.setText(td_mod.title(self.td_id))
            self._set_chips([])
            self._render("<h2>%s</h2><p class=\"lead\">Le sujet n'a pas encore été lu. "
                         "« Lire et corriger » le découpe en exercices, puis produit la "
                         "correction de chacun.</p>" % td_mod.title(self.td_id),
                         td_mod.title(self.td_id))

    def _on_row(self, row: int) -> None:
        if row >= 0:
            self.index = row
            self._show(row)

    def _show(self, index: int) -> None:
        items = td_mod.exercises(self.td_id)
        if not (0 <= index < len(items)):
            return
        ex = items[index]
        self.ex_title.setText("Exercice %s — %s" % (ex.get("number", index + 1), ex.get("title", "")))
        self._set_chips(ex.get("courses") or [])
        correction = td_mod.read_correction(self.td_id, index, td_mod.exercise_fingerprint(ex))
        body = ('<div class="box example"><span class="box-title">Énoncé</span>%s</div>'
                % ex.get("statement", ""))
        if correction and not self.statement_only:
            body += correction
        elif correction:
            body += ("<p class=\"lead\">Correction masquée : cherchez d'abord, puis "
                     "revenez avec « Voir la correction ».</p>")
        else:
            body += ("<p class=\"lead\">Cet exercice n'est pas encore corrigé.</p>")
        self.btn_view.setText("Voir la correction" if self.statement_only else "Énoncé seul")
        self.btn_view.setEnabled(bool(correction))
        self._render(body, "Exercice %s" % ex.get("number", index + 1),
                     name="td_%s_%02d" % (self.td_id, index))

    def _render(self, body: str, title: str, name: str = "td_accueil") -> None:
        d = library_dir() / "_views"
        d.mkdir(parents=True, exist_ok=True)
        path = d / ("%s.html" % name)
        path.write_text(content.build_page(body, title, theme.name()), encoding="utf-8")
        self.view.load_file(path)

    def _set_chips(self, course_ids) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        pal = theme.palette()
        if course_ids:
            label = QLabel("Cours utiles")
            label.setObjectName("Muted")
            self.chips.addWidget(label)
        for cid in course_ids:
            course = self.syl.get(cid)
            if course is None:
                continue
            ready = content.has_course(cid)
            chip = QPushButton(course.title)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            colour, soft = (pal["ok"], pal["ok_soft"]) if ready else (pal["warn"], pal["warn_soft"])
            chip.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:999px;"
                "padding:3px 11px;font-size:11.5px;}QPushButton:hover{border-color:%s;}"
                % (soft, colour, colour, pal["accent"]))
            chip.setToolTip("Cours rédigé : cliquer pour l'ouvrir" if ready
                            else "Cours pas encore généré : cliquer pour l'ouvrir et le générer")
            chip.clicked.connect(lambda _=False, c=cid: self.course_opened.emit(c))
            self.chips.addWidget(chip)
        self.chips.addStretch(1)

    # ------------------------------------------------------------- actions
    def _toggle_view(self) -> None:
        self.statement_only = not self.statement_only
        self._show(self.index)

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Importer un sujet de TD", str(pathlib.Path.home()), "PDF (*.pdf)")
        if not path:
            return
        try:
            td_id = td_mod.import_pdf(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import impossible", str(exc))
            return
        self.open_td(td_id)
        if not td_mod.state(td_id)["complete"]:
            self.correct_requested.emit(td_id)

    def _delete(self) -> None:
        if not self.td_id:
            return
        if QMessageBox.question(
                self, "Supprimer le TD",
                "Supprimer « %s » et sa correction ?" % td_mod.title(self.td_id),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        td_mod.delete(self.td_id)
        self.td_id = None
        self.refresh()

    def _current_course(self) -> str:
        items = td_mod.exercises(self.td_id) if self.td_id else []
        if 0 <= self.index < len(items):
            courses = items[self.index].get("courses") or []
            return courses[0] if courses else ""
        return ""

    def _ask(self, text: str, heading: str) -> None:
        self.ask_requested.emit(self._current_course(), text, heading)

    def _proof_help(self, proof_id: str, heading: str, text: str) -> None:
        self.proof_help_requested.emit(
            self._current_course(), "td:%s:%d:%s" % (self.td_id, self.index, proof_id),
            heading, text)

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl
        self._load()

    def apply_theme(self) -> None:
        self.view.set_theme(theme.name())
