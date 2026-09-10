"""Accueil : ou j'en suis, et qu'est-ce que j'attaque maintenant."""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import content, status as st_mod
from ..status import MASTERED, PARTIAL, Status
from ..syllabus import Syllabus
from . import theme


def _bar(value: int, total: int, color: str) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, max(1, total))
    bar.setValue(value)
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    bar.setStyleSheet(
        "QProgressBar{background:%s;border:none;border-radius:3px;}"
        "QProgressBar::chunk{background:%s;border-radius:3px;}"
        % (theme.palette()["bg3"], color))
    return bar


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(9)


class Dashboard(QWidget):
    course_opened = Signal(str)
    generate_requested = Signal(list)
    show_graph = Signal(str)

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self._queue_lookup = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        outer.addWidget(self.area)
        self.host = QWidget()
        self.area.setWidget(self.host)
        self.root = QVBoxLayout(self.host)
        self.root.setContentsMargins(34, 30, 34, 40)
        self.root.setSpacing(18)

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl
        self.refresh()

    def set_queue_lookup(self, fn) -> None:
        """fn(course_id) -> texte d'avancement, ou None si rien en cours."""
        self._queue_lookup = fn

    def running(self, course_id: str):
        return self._queue_lookup(course_id) if self._queue_lookup else None

    def refresh(self) -> None:
        scroll = self.area.verticalScrollBar().value()
        while self.root.count():
            item = self.root.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        pal = theme.palette()
        statuses = st_mod.compute(self.syl)
        total = len(self.syl.courses)
        mastered = sum(1 for s in statuses.values() if s.mastered)
        generated = sum(1 for s in statuses.values() if s.complete)

        title = QLabel("Remise à niveau M2 MVA")
        title.setObjectName("H1")
        self.root.addWidget(title)

        sub = QLabel("%d cours sur %d maîtrisé%s  ·  %d généré%s  ·  seuil de maîtrise : %d %%"
                     % (mastered, total, "s" if mastered > 1 else "",
                        generated, "s" if generated > 1 else "", st_mod.threshold()))
        sub.setObjectName("Muted")
        self.root.addWidget(sub)
        self.root.addWidget(_bar(mastered, total, pal["ok"]))
        self.root.addSpacing(6)

        self._interrupted(statuses, pal)
        self._tracks(statuses, pal)
        self._tracks_compact(statuses, pal)
        self._next(statuses, pal)
        self._review(statuses, pal)
        self._domains(statuses, pal)
        self.root.addStretch(1)
        # on garde la position de lecture : la page se rafraichit pendant les
        # generations, et repartir en haut a chaque tick serait insupportable
        QTimer.singleShot(0, lambda: self.area.verticalScrollBar().setValue(scroll))

    # ------------------------------------------------------------- sections
    def _section_title(self, text: str, hint: str = "") -> None:
        row = QHBoxLayout()
        label = QLabel(text)
        label.setObjectName("H2")
        row.addWidget(label)
        if hint:
            h = QLabel(hint)
            h.setObjectName("Muted")
            row.addWidget(h)
        row.addStretch(1)
        host = QWidget()
        host.setLayout(row)
        self.root.addSpacing(10)
        self.root.addWidget(host)

    def _interrupted(self, statuses: Dict[str, Status], pal: dict) -> None:
        ids = st_mod.incomplete(self.syl, statuses)
        if not ids:
            return
        self._section_title(
            "Générations interrompues",
            "reprendre ne refait pas les sections déjà écrites")
        card = Card()
        for cid in ids[:8]:
            s = statuses[cid]
            row = QHBoxLayout()
            row.setContentsMargins(0, 3, 0, 3)
            row.setSpacing(10)
            dot = QLabel("&#9679;")
            dot.setTextFormat(Qt.TextFormat.RichText)
            dot.setStyleSheet("color:%s" % pal["err"])
            row.addWidget(dot)
            link = QPushButton(self.syl.title(cid))
            link.setProperty("flat", True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setStyleSheet("QPushButton{text-align:left;padding:2px 4px;}"
                               "QPushButton:hover{color:%s;}" % pal["accent"])
            link.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            link.clicked.connect(lambda _=False, c=cid: self.course_opened.emit(c))
            row.addWidget(link, 1)
            progress = self.running(cid)
            info = QLabel(progress or "%d / %d sections" % (s.sections_done, s.sections_total))
            info.setObjectName("Muted")
            if progress:
                info.setStyleSheet("color:%s;font-weight:600" % pal["accent"])
            row.addWidget(info)
            host = QWidget()
            host.setLayout(row)
            card.lay.addWidget(host)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        todo = [cid for cid in ids if not self.running(cid)]
        btn = QPushButton("Tout reprendre (%d)" % len(todo) if len(todo) > 1 else "Reprendre")
        btn.setProperty("primary", True)
        btn.setEnabled(bool(todo))
        btn.clicked.connect(lambda _=False, batch=list(todo): self.generate_requested.emit(batch))
        actions.addWidget(btn)
        if not todo:
            running = QLabel("reprise en cours")
            running.setStyleSheet("color:%s;font-weight:600" % pal["accent"])
            actions.addWidget(running)
        actions.addStretch(1)
        host = QWidget()
        host.setLayout(actions)
        card.lay.addWidget(host)
        self.root.addWidget(card)

    def _tracks(self, statuses: Dict[str, Status], pal: dict) -> None:
        group = "rentree"
        tracks = self.syl.tracks_in(group)
        if not tracks:
            return
        self._section_title(self.syl.group_name(group),
                            "chaque parcours = le cours cible et tout ce qu'il faut avant")
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, track in enumerate(tracks):
            path = self.syl.track_path(track.id)
            done = sum(1 for c in path if statuses[c].mastered)
            gen = sum(1 for c in path if statuses[c].complete)
            card = Card()
            name = QLabel(track.title)
            name.setObjectName("H2")
            name.setWordWrap(True)
            card.lay.addWidget(name)
            info = QLabel("%d cours  ·  %d maîtrisé%s  ·  %d généré%s"
                          % (len(path), done, "s" if done > 1 else "",
                             gen, "s" if gen > 1 else ""))
            info.setObjectName("Muted")
            card.lay.addWidget(info)
            card.lay.addWidget(_bar(done, len(path), pal["ok"] if done else pal["accent"]))
            row = QHBoxLayout()
            row.setSpacing(7)
            btn = QPushButton("Voir le parcours")
            btn.setProperty("flat", True)
            btn.clicked.connect(lambda _=False, t=track.id: self.show_graph.emit(t))
            row.addWidget(btn)
            todo = [c for c in path if not statuses[c].complete]
            if todo:
                gen_btn = QPushButton("Générer le cours manquant" if len(todo) == 1
                                      else "Générer les %d manquants" % len(todo))
                gen_btn.setProperty("flat", True)
                gen_btn.clicked.connect(lambda _=False, ids=todo: self.generate_requested.emit(ids))
                row.addWidget(gen_btn)
            row.addStretch(1)
            host = QWidget()
            host.setLayout(row)
            card.lay.addWidget(host)
            grid.addWidget(card, i // 3, i % 3)
        host = QWidget()
        host.setLayout(grid)
        self.root.addWidget(host)

    def _tracks_compact(self, statuses: Dict[str, Status], pal: dict) -> None:
        """Les parcours du M2 : trop nombreux pour des cartes, une ligne chacun."""
        group = "mva"
        tracks = self.syl.tracks_in(group)
        if not tracks:
            return
        self._section_title(self.syl.group_name(group),
                            "ce que chaque cours suppose acquis, et le chemin pour y arriver")
        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for i, track in enumerate(sorted(tracks, key=lambda t: t.title)):
            path = self.syl.track_path(track.id)
            done = sum(1 for c in path if statuses[c].mastered)

            link = QPushButton(track.title)
            link.setProperty("flat", True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setStyleSheet("QPushButton{text-align:left;padding:2px 4px;}"
                               "QPushButton:hover{color:%s;}" % pal["accent"])
            link.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            link.clicked.connect(lambda _=False, t=track.id: self.show_graph.emit(t))
            grid.addWidget(link, i, 0)

            bar = _bar(done, len(path), pal["ok"] if done else pal["accent"])
            bar.setMinimumWidth(140)
            grid.addWidget(bar, i, 1)

            count = QLabel("%d / %d" % (done, len(path)))
            count.setObjectName("Muted")
            grid.addWidget(count, i, 2)

            todo = [c for c in path if not statuses[c].complete]
            gen_btn = QPushButton("Générer (%d)" % len(todo))
            gen_btn.setProperty("flat", True)
            gen_btn.setEnabled(bool(todo))
            gen_btn.clicked.connect(lambda _=False, ids=todo: self.generate_requested.emit(ids))
            grid.addWidget(gen_btn, i, 3)
        host = QWidget()
        host.setLayout(grid)
        card.lay.addWidget(host)
        self.root.addWidget(card)

    def _course_row(self, cid: str, statuses: Dict[str, Status], pal: dict) -> QWidget:
        course = self.syl.get(cid)
        s = statuses[cid]
        row = QHBoxLayout()
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)

        dot = QLabel("&#9679;")
        dot.setTextFormat(Qt.TextFormat.RichText)
        dot.setStyleSheet("color:%s" % self.syl.domain_color(course.domain))
        row.addWidget(dot)

        link = QPushButton(course.title)
        link.setProperty("flat", True)
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setStyleSheet("QPushButton{text-align:left;padding:2px 4px;}"
                           "QPushButton:hover{color:%s;}" % pal["accent"])
        link.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        link.clicked.connect(lambda _=False, c=cid: self.course_opened.emit(c))
        row.addWidget(link, 1)

        meta = QLabel("%s  ·  niveau %d" % (self.syl.domain_name(course.domain), course.level))
        meta.setObjectName("Muted")
        row.addWidget(meta)

        if s.score_pct is not None:
            score = QLabel("%d %%" % s.score_pct)
            score.setToolTip("%d justes sur %d tentées" % (s.correct, s.answered))
            score.setStyleSheet("color:%s;font-weight:600"
                                % (pal["ok"] if s.mastered else pal["warn"]))
            row.addWidget(score)
        elif not s.complete:
            progress = self.running(cid)
            if progress:
                tag = QLabel(progress)
                tag.setStyleSheet("color:%s;font-weight:600" % pal["accent"])
                row.addWidget(tag)
            else:
                btn = QPushButton("Reprendre" if s.partial else "Générer")
                btn.setProperty("flat", True)
                btn.clicked.connect(lambda _=False, c=cid: self.generate_requested.emit([c]))
                row.addWidget(btn)
        else:
            tag = QLabel("à étudier")
            tag.setObjectName("Muted")
            row.addWidget(tag)

        host = QWidget()
        host.setLayout(row)
        return host

    def _next(self, statuses: Dict[str, Status], pal: dict) -> None:
        ids = st_mod.next_recommended(self.syl, statuses, 8)
        if not ids:
            return
        self._section_title("À faire ensuite", "prérequis satisfaits, du plus simple au plus avancé")
        card = Card()
        for cid in ids:
            card.lay.addWidget(self._course_row(cid, statuses, pal))
        self.root.addWidget(card)

    def _review(self, statuses: Dict[str, Status], pal: dict) -> None:
        ids = [cid for cid in self.syl.order
               if statuses[cid].answered and not statuses[cid].mastered]
        if not ids:
            return
        ids.sort(key=lambda c: statuses[c].score_pct or 0)
        self._section_title("À réviser", "QCM sous le seuil de maîtrise")
        card = Card()
        for cid in ids[:8]:
            card.lay.addWidget(self._course_row(cid, statuses, pal))
        self.root.addWidget(card)

    def _domains(self, statuses: Dict[str, Status], pal: dict) -> None:
        self._section_title("Avancement par domaine")
        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(9)
        for i, did in enumerate(self.syl.domain_order):
            ids = [c.id for c in self.syl.by_domain(did)]
            if not ids:
                continue
            done = sum(1 for c in ids if statuses[c].mastered)
            name = QLabel(self.syl.domain_name(did))
            name.setStyleSheet("color:%s;font-weight:600" % self.syl.domain_color(did))
            grid.addWidget(name, i, 0)
            bar = _bar(done, len(ids), self.syl.domain_color(did))
            bar.setMinimumWidth(160)
            grid.addWidget(bar, i, 1)
            count = QLabel("%d / %d" % (done, len(ids)))
            count.setObjectName("Muted")
            grid.addWidget(count, i, 2)
        host = QWidget()
        host.setLayout(grid)
        card.lay.addWidget(host)
        self.root.addWidget(card)
