"""Bibliotheque : liste filtrable de tous les cours avec leur progression."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QStyledItemDelegate,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import content, status as st_mod
from ..status import AVAILABLE, LOCKED, MASTERED, PARTIAL, READY, STARTED, Status
from ..syllabus import Syllabus
from . import theme

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_SCORE = Qt.ItemDataRole.UserRole + 1
ROLE_STATE = Qt.ItemDataRole.UserRole + 2

COL_TITLE, COL_LEVEL, COL_PREREQ, COL_SCORE, COL_STATE = range(5)

STATE_COLOR = {
    LOCKED: "locked", AVAILABLE: "accent", PARTIAL: "err", READY: "fg2",
    STARTED: "warn", MASTERED: "ok",
}


class ScoreDelegate(QStyledItemDelegate):
    """Barre de progression compacte dans la colonne score."""

    def paint(self, painter: QPainter, option, index) -> None:
        score = index.data(ROLE_SCORE)
        if score is None:
            super().paint(painter, option, index)
            return
        pal = theme.palette()
        painter.save()
        if option.state & option.state.__class__.State_Selected:
            painter.fillRect(option.rect, QColor(pal["accent_soft"]))
        r = option.rect
        bar_w, bar_h = 62, 6
        y = r.center().y() - bar_h // 2
        x = r.left() + 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal["bg3"]))
        painter.drawRoundedRect(QRect(x, y, bar_w, bar_h), 3, 3)
        thr = st_mod.threshold()
        col = pal["ok"] if score >= thr else (pal["warn"] if score >= 50 else pal["err"])
        painter.setBrush(QColor(col))
        painter.drawRoundedRect(QRect(x, y, max(3, int(bar_w * score / 100)), bar_h), 3, 3)
        painter.setPen(QPen(QColor(pal["fg2"])))
        f = painter.font()
        f.setPointSizeF(f.pointSizeF() - 0.5)
        painter.setFont(f)
        painter.drawText(QRect(x + bar_w + 8, r.top(), 46, r.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         "%d %%" % score)
        painter.restore()


class LibraryPage(QWidget):
    course_opened = Signal(str)
    generate_requested = Signal(list)       # liste d'identifiants
    regenerate_requested = Signal(str)
    exercises_requested = Signal(str)
    sheets_requested = Signal(list)
    cancel_requested = Signal(str)
    delete_requested = Signal(str)
    import_requested = Signal()

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.statuses: Dict[str, Status] = {}
        self._queue_lookup = None
        self._pause_lookup = None
        self._first_build = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 9, 14, 9)
        bl.setSpacing(9)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un cours, un mot-clé...")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(230)
        self.search.textChanged.connect(self.refresh)
        bl.addWidget(self.search, 2)
        from PySide6.QtWidgets import QPushButton
        self.btn_import = QPushButton("Importer un cours (PDF)…")
        self.btn_import.setToolTip(
            "Un cours magistral en PDF devient un cours de l'application : réécrit avec "
            "des intuitions, relié au cursus, exercices corrigés à part.")
        self.btn_import.clicked.connect(self.import_requested.emit)
        bl.addWidget(self.btn_import)

        self.f_domain = QComboBox()
        self._fill_domains()
        self.f_domain.currentIndexChanged.connect(self.refresh)
        bl.addWidget(self.f_domain)

        self.f_level = QComboBox()
        self.f_level.addItem("Tous niveaux", None)
        for value, label in sorted(self.syl.levels.items()):
            self.f_level.addItem("%d - %s" % (value, label), value)
        self.f_level.currentIndexChanged.connect(self.refresh)
        bl.addWidget(self.f_level)

        self.f_state = QComboBox()
        for label, key in [
            ("Tous les cours", None),
            ("Accessibles maintenant", "unlocked"),
            ("Non générés", "ungenerated"),
            ("Générés", "generated"),
            ("À réviser (sous le seuil)", "weak"),
            ("Maîtrisés", MASTERED),
            ("Verrouillés", LOCKED),
        ]:
            self.f_state.addItem(label, key)
        self.f_state.currentIndexChanged.connect(self.refresh)
        bl.addWidget(self.f_state)

        self.f_track = QComboBox()
        self._fill_tracks()
        self.f_track.currentIndexChanged.connect(self.refresh)
        bl.addWidget(self.f_track)

        bl.addStretch(1)
        # les filtres gardent leur largeur naturelle quand il y a la place, mais
        # peuvent retrecir : sinon la page imposait sa largeur a toute la fenetre
        self.search.setMinimumWidth(150)
        for combo in (self.f_domain, self.f_level, self.f_state, self.f_track):
            combo.setMinimumWidth(100)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        bl.addWidget(self.summary)
        self.summary.setMinimumWidth(40)
        root.addWidget(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Cours", "Niveau", "Prérequis", "Score QCM", "État"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setItemDelegateForColumn(COL_SCORE, ScoreDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._activate)
        header = self.tree.header()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_LEVEL, 108), (COL_PREREQ, 130), (COL_SCORE, 130), (COL_STATE, 120)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.tree.setColumnWidth(col, width)
        root.addWidget(self.tree, 1)

    # ------------------------------------------------------------------ etat
    def set_syllabus(self, syl: Syllabus) -> None:
        """Après un ajout au syllabus : on reconstruit les filtres."""
        self.syl = syl
        for combo, rebuild in ((self.f_domain, self._fill_domains),
                               (self.f_track, self._fill_tracks)):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            rebuild()
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self._first_build = True
        self.refresh()

    def _fill_domains(self) -> None:
        self.f_domain.addItem("Tous les domaines", None)
        for did in self.syl.domain_order:
            self.f_domain.addItem(self.syl.domain_name(did), did)

    def _fill_tracks(self) -> None:
        self.f_track.addItem("Tout le syllabus", None)
        for gid in self.syl.track_groups:
            for track in sorted(self.syl.tracks_in(gid), key=lambda t: t.title):
                self.f_track.addItem("%s — %s" % (self.syl.group_name(gid), track.title),
                                     track.id)

    def set_queue_lookup(self, fn) -> None:
        """fn(course_id) -> texte d'avancement ou None."""
        self._queue_lookup = fn

    def set_pause_lookup(self, fn) -> None:
        """fn(course_id) -> raison d'une génération interrompue, ou texte vide."""
        self._pause_lookup = fn

    def selected_id(self) -> Optional[str]:
        item = self.tree.currentItem()
        return item.data(0, ROLE_ID) if item else None

    def _filtered(self) -> List[str]:
        query = self.search.text().strip().lower()
        domain = self.f_domain.currentData()
        level = self.f_level.currentData()
        state = self.f_state.currentData()
        track = self.f_track.currentData()
        allowed = set(self.syl.track_path(track)) if track else None

        out = []
        for course in self.syl.all():
            s = self.statuses[course.id]
            if allowed is not None and course.id not in allowed:
                continue
            if domain and course.domain != domain:
                continue
            if level and course.level != level:
                continue
            if state == "unlocked" and not (s.unlocked and s.state != MASTERED):
                continue
            if state == "ungenerated" and s.complete:
                continue
            if state == "generated" and not s.complete:
                continue
            if state == "weak" and not (s.attempts and not s.mastered):
                continue
            if state == MASTERED and not s.mastered:
                continue
            if state == LOCKED and s.unlocked:
                continue
            if state == PARTIAL and not s.partial:
                continue
            if query:
                hay = " ".join([course.title, course.summary, " ".join(course.keywords),
                                " ".join(course.objectives)]).lower()
                if query not in hay:
                    continue
            out.append(course.id)
        return out

    def refresh(self) -> None:
        self.statuses = st_mod.compute(self.syl)
        pal = theme.palette()
        visible = self._filtered()
        by_domain: Dict[str, List[str]] = {}
        for cid in visible:
            by_domain.setdefault(self.syl.get(cid).domain, []).append(cid)

        if self._first_build:
            expanded = set(self.syl.domain_order)
            self._first_build = False
        else:
            expanded = {
                self.tree.topLevelItem(i).data(0, ROLE_ID)
                for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).isExpanded()
            }
        current = self.selected_id()

        self.tree.clear()
        mono = QFont("monospace")
        for did in self.syl.domain_order:
            ids = by_domain.get(did)
            if not ids:
                continue
            mastered = sum(1 for c in ids if self.statuses[c].mastered)
            generated = sum(1 for c in ids if self.statuses[c].complete)
            group = QTreeWidgetItem(self.tree)
            group.setData(0, ROLE_ID, did)
            group.setText(COL_TITLE, self.syl.domain_name(did))
            group.setText(COL_STATE, "%d/%d maîtrisés" % (mastered, len(ids)))
            group.setText(COL_PREREQ, "%d/%d générés" % (generated, len(ids)))
            f = group.font(COL_TITLE)
            f.setBold(True)
            group.setFont(COL_TITLE, f)
            group.setForeground(COL_TITLE, QColor(self.syl.domain_color(did)))
            group.setForeground(COL_STATE, QColor(pal["muted"]))
            group.setForeground(COL_PREREQ, QColor(pal["muted"]))
            group.setFirstColumnSpanned(False)

            for cid in ids:
                course = self.syl.get(cid)
                s = self.statuses[cid]
                item = QTreeWidgetItem(group)
                item.setData(0, ROLE_ID, cid)
                item.setData(0, ROLE_STATE, s.state)
                item.setText(COL_TITLE, course.title)
                item.setToolTip(COL_TITLE, course.summary)
                item.setText(COL_LEVEL, "%d - %s" % (course.level, self.syl.levels.get(course.level, "")))
                item.setForeground(COL_LEVEL, QColor(pal["muted"]))

                if s.missing:
                    item.setText(COL_PREREQ, "%d manquant%s" % (len(s.missing), "s" if len(s.missing) > 1 else ""))
                    item.setForeground(COL_PREREQ, QColor(pal["locked"]))
                    item.setToolTip(COL_PREREQ, "\n".join(self.syl.title(m) for m in s.missing))
                elif course.prereqs:
                    item.setText(COL_PREREQ, "ok")
                    item.setForeground(COL_PREREQ, QColor(pal["ok"]))
                else:
                    item.setText(COL_PREREQ, "aucun")
                    item.setForeground(COL_PREREQ, QColor(pal["muted"]))

                if s.score_pct is not None:
                    item.setData(COL_SCORE, ROLE_SCORE, s.score_pct)
                    tip = ("%d questions justes sur %d tentées\n"
                           "%d question(s) au total dans les séries"
                           % (s.correct, s.answered, s.questions_total))
                    if not s.enough_answered:
                        tip += ("\nIl en faut %d tentées pour juger de la maîtrise."
                                % s.questions_needed)
                    if s.best_pct is not None:
                        tip += "\nMeilleure séance complète : %d %%" % s.best_pct
                    item.setToolTip(COL_SCORE, tip)
                else:
                    item.setText(COL_SCORE, "-")
                    item.setForeground(COL_SCORE, QColor(pal["muted"]))
                    item.setFont(COL_SCORE, mono)

                running = self._queue_lookup(cid) if self._queue_lookup else None
                if running:
                    item.setText(COL_STATE, running)
                    item.setForeground(COL_STATE, QColor(pal["accent"]))
                else:
                    extra = ""
                    if s.partial and s.sections_total:
                        extra = "  (%d/%d sections)" % (s.sections_done, s.sections_total)
                    elif s.generated and s.proofs_total:
                        extra = "  (%d/%d démos)" % (s.proofs_done, s.proofs_total)
                    reason = (self._pause_lookup(cid) if s.partial and self._pause_lookup
                              else "")
                    if reason:
                        extra += "  — %s" % reason
                        item.setToolTip(COL_STATE, "Génération interrompue : %s" % reason)
                    item.setText(COL_STATE, s.label + extra)
                    item.setForeground(COL_STATE, QColor(pal[STATE_COLOR[s.state]]))
                if s.state == LOCKED:
                    item.setForeground(COL_TITLE, QColor(pal["locked"]))

            group.setExpanded(did in expanded or bool(self.search.text()))

        if current:
            self.select(current)
        total = len(visible)
        mastered = sum(1 for c in visible if self.statuses[c].mastered)
        generated = sum(1 for c in visible if self.statuses[c].complete)
        partial = sum(1 for c in visible if self.statuses[c].partial)
        text = "%d cours  ·  %d générés  ·  %d maîtrisés" % (total, generated, mastered)
        if partial:
            text += "  ·  %d interrompu%s" % (partial, "s" if partial > 1 else "")
        self.summary.setText(text)
        self.summary.setToolTip(text)

    def select(self, course_id: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.data(0, ROLE_ID) == course_id:
                    group.setExpanded(True)
                    self.tree.setCurrentItem(child)
                    self.tree.scrollToItem(child)
                    return

    # ---------------------------------------------------------------- actions
    def _activate(self, item: QTreeWidgetItem, _col: int) -> None:
        cid = item.data(0, ROLE_ID)
        if cid and cid in self.syl.courses:
            self.course_opened.emit(cid)
        else:
            item.setExpanded(not item.isExpanded())

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        cid = item.data(0, ROLE_ID)
        menu = QMenu(self)

        if cid in self.syl.courses:
            s = self.statuses[cid]
            course = self.syl.get(cid)
            running = self._queue_lookup(cid) if self._queue_lookup else None

            act = QAction("Ouvrir", self)
            act.triggered.connect(lambda: self.course_opened.emit(cid))
            menu.addAction(act)
            menu.addSeparator()

            if running:
                act = QAction("Annuler la génération", self)
                act.triggered.connect(lambda: self.cancel_requested.emit(cid))
                menu.addAction(act)
            else:
                if s.partial:
                    act = QAction("Reprendre la génération (%d/%d sections faites)"
                                  % (s.sections_done, s.sections_total), self)
                    act.triggered.connect(lambda: self.generate_requested.emit([cid]))
                    menu.addAction(act)
                elif not s.complete:
                    act = QAction("Générer le cours", self)
                    act.triggered.connect(lambda: self.generate_requested.emit([cid]))
                    menu.addAction(act)
                if s.complete:
                    act = QAction("Régénérer seulement les exercices", self)
                    act.triggered.connect(lambda: self.exercises_requested.emit(cid))
                    menu.addAction(act)
                if s.generated:
                    act = QAction("Régénérer le cours entier", self)
                    act.triggered.connect(lambda: self.regenerate_requested.emit(cid))
                    menu.addAction(act)
                    act = QAction("Régénérer la fiche" if content.has_sheet(cid)
                                  else "Générer la fiche de révision", self)
                    act.triggered.connect(lambda: self.sheets_requested.emit([cid]))
                    menu.addAction(act)

            missing_path = [c for c in self.syl.path_to(cid)
                            if not self.statuses[c].complete]
            if missing_path:
                act = QAction("Générer tout le chemin de prérequis (%d cours)" % len(missing_path), self)
                act.triggered.connect(lambda: self.generate_requested.emit(missing_path))
                menu.addAction(act)

            if s.generated:
                menu.addSeparator()
                act = QAction("Supprimer le contenu généré", self)
                act.triggered.connect(lambda: self.delete_requested.emit(cid))
                menu.addAction(act)
        else:
            ids = [item.child(i).data(0, ROLE_ID) for i in range(item.childCount())]
            todo = [c for c in ids if not self.statuses[c].complete]
            if todo:
                act = QAction("Générer les %d cours manquants de ce domaine" % len(todo), self)
                act.triggered.connect(lambda: self.generate_requested.emit(todo))
                menu.addAction(act)
            missing_sheets = [c for c in ids
                              if content.has_course(c) and not content.has_sheet(c)]
            if missing_sheets:
                act = QAction("Générer les %d fiches manquantes de ce domaine"
                              % len(missing_sheets), self)
                act.triggered.connect(
                    lambda _=False, batch=missing_sheets: self.sheets_requested.emit(batch))
                menu.addAction(act)
            act = QAction("Tout déplier", self)
            act.triggered.connect(lambda: item.setExpanded(True))
            menu.addAction(act)

        menu.exec(self.tree.viewport().mapToGlobal(pos))
