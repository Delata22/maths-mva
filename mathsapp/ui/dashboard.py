"""Accueil : ou j'en suis, et qu'est-ce que j'attaque maintenant."""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import content, curriculum, gamify, gaps, review as review_mod, status as st_mod, store
from ..status import MASTERED, PARTIAL, Status
from ..syllabus import Syllabus
from . import theme
from .widgets import Heatmap, Ring


def ago(timestamp: float, now: float = None) -> str:
    """Ancienneté lisible : « il y a 5 min », « hier »…"""
    import time
    seconds = max(0.0, (time.time() if now is None else now) - float(timestamp or 0))
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return "il y a %d min" % (seconds // 60)
    if seconds < 86400:
        return "il y a %d h" % (seconds // 3600)
    days = int(seconds // 86400)
    return "hier" if days == 1 else "il y a %d jours" % days


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
    session_requested = Signal(str)      # review / daily / challenge
    resume_requested = Signal(str)       # cours a rouvrir a la position de lecture
    curriculum_requested = Signal()      # ouvrir « Nouveau cursus »

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

        title = QLabel(curriculum.profile()["title"])
        title.setObjectName("H1")
        self.root.addWidget(title)

        sub = QLabel("%d cours sur %d maîtrisé%s  ·  %d généré%s  ·  seuil de maîtrise : %d %%"
                     % (mastered, total, "s" if mastered > 1 else "",
                        generated, "s" if generated > 1 else "", st_mod.threshold()))
        sub.setObjectName("Muted")
        self.root.addWidget(sub)
        self.root.addWidget(_bar(mastered, total, pal["ok"]))
        self.root.addSpacing(6)

        self._welcome(pal)
        self._resume(statuses, pal)
        self._today(statuses, pal)
        self._progression(statuses, pal)
        self._milestones(statuses, pal)
        self._interrupted(statuses, pal)
        for group in self.syl.ordered_groups():
            tracks = self.syl.tracks_in(group)
            if len(tracks) <= 6:
                self._tracks(group, tracks, statuses, pal)
            else:
                self._tracks_compact(group, tracks, statuses, pal)
        self._next(statuses, pal)
        self._review(statuses, pal)
        self._week(statuses, pal)
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

    # --------------------------------------------------------------- reprendre
    def _resume(self, statuses: Dict[str, Status], pal: dict) -> None:
        """Le dernier cours consulté, là où la lecture s'est arrêtée."""
        position = store.last_reading()
        if not store.resumable(position):
            return
        cid = position["course_id"]
        if cid not in self.syl.courses or not statuses[cid].generated:
            return
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(self.syl.title(cid))
        name.setObjectName("H2")
        name.setWordWrap(True)
        text.addWidget(name)
        section = position["section_title"]
        if len(section) > 90:
            section = section[:89] + "…"
        detail = QLabel("Section : %s  ·  %d %% du cours  ·  %s"
                        % (section, int(round(100 * float(position["fraction"] or 0))),
                           ago(position["updated_at"])))
        detail.setObjectName("Muted")
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        text.addWidget(detail)
        host = QWidget()
        host.setLayout(text)
        row.addWidget(host, 1)
        btn = QPushButton("Reprendre")
        btn.setProperty("primary", True)
        btn.setToolTip("Rouvrir le cours à la section où vous vous étiez arrêté")
        btn.clicked.connect(lambda _=False, c=cid: self.resume_requested.emit(c))
        row.addWidget(btn)
        holder = QWidget()
        holder.setLayout(row)
        card.lay.addWidget(holder)
        self._section_title("Reprendre la lecture")
        self.root.addWidget(card)

    # ------------------------------------------------------------ aujourd'hui
    def _today(self, statuses: Dict[str, Status], pal: dict) -> None:
        goal = gamify.goal_state()
        streak = gamify.refresh_streak()
        due = review_mod.due_resolved()
        day = gamify.today()
        has_daily = content.has_daily(day)

        self._section_title(
            "Aujourd'hui",
            "objectif atteint" if goal.met else "une brique suffit pour tenir la série")
        card = Card()
        top = QHBoxLayout()
        top.setSpacing(20)

        ring = Ring(96)
        ring.set_value(goal.fraction,
                       "%d/%d" % (goal.done, goal.target),
                       "brique" if goal.target == 1 else "briques",
                       "ok" if goal.met else "accent")
        ring.setToolTip("Une brique = une séance de QCM, une révision terminée, "
                        "une démonstration soumise ou réussie.")
        top.addWidget(ring)

        info = QVBoxLayout()
        info.setSpacing(3)
        flame = QLabel(
            "<span style='font-size:19px;font-weight:700'>%d</span> "
            "<span style='color:%s'>jour%s d'affilée</span>"
            % (streak.current, pal["muted"], "s" if streak.current > 1 else ""))
        flame.setTextFormat(Qt.TextFormat.RichText)
        info.addWidget(flame)
        detail = QLabel("record %d  ·  %d gel%s disponible%s ce mois"
                        % (streak.best, streak.freezes_left,
                           "s" if streak.freezes_left > 1 else "",
                           "s" if streak.freezes_left > 1 else ""))
        detail.setObjectName("Muted")
        detail.setToolTip("Un gel couvre un jour manqué des deux derniers jours, "
                          "pour qu'un oubli ne casse pas la série.")
        info.addWidget(detail)
        if goal.questions or goal.reviews or goal.proofs:
            done = QLabel("aujourd'hui : %d question%s · %d révision%s · %d démo%s · %d XP"
                          % (goal.questions, "s" if goal.questions > 1 else "",
                             goal.reviews, "s" if goal.reviews > 1 else "",
                             goal.proofs, "s" if goal.proofs > 1 else "", goal.xp))
            done.setObjectName("Muted")
            info.addWidget(done)
        info.addStretch(1)
        host = QWidget()
        host.setLayout(info)
        top.addWidget(host, 1)

        heat = Heatmap()
        heat.set_days(streak.days)
        heat.setToolTip("Les jours travaillés des trois derniers mois.")
        top.addWidget(heat, 1)
        holder = QWidget()
        holder.setLayout(top)
        card.lay.addWidget(holder)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        btn_review = QPushButton("Réviser  (%d)" % len(due) if due else "Rien à revoir")
        btn_review.setProperty("primary", bool(due))
        btn_review.setEnabled(bool(due))
        if due:
            btn_review.setToolTip("%d question%s à revoir, environ %d min"
                                  % (len(due), "s" if len(due) > 1 else "",
                                     review_mod.estimate_minutes(len(due))))
        else:
            btn_review.setToolTip("Rien n'est dû aujourd'hui. "
                                  "Le prochain rappel viendra tout seul.")
        btn_review.clicked.connect(lambda: self.session_requested.emit("review"))
        actions.addWidget(btn_review)

        btn_daily = QPushButton("Quiz du jour" if has_daily else "Préparer le quiz du jour")
        btn_daily.setProperty("primary", has_daily and not due)
        btn_daily.clicked.connect(lambda: self.session_requested.emit("daily"))
        actions.addWidget(btn_daily)

        pending = content.pending_refresher(day)
        candidates = [] if pending else review_mod.refresher_candidates()
        if pending or candidates:
            cid = pending or candidates[0]["course_id"]
            name = self.syl.title(cid)
            short = name if len(name) <= 32 else name[:31] + "…"
            btn_refresh = QPushButton(("Rappel : %s" if pending else "Rappel conseillé : %s")
                                      % short)
            btn_refresh.setToolTip(
                "Cinq questions neuves sur « %s », prêtes." % name if pending else
                "%s. Cinq questions neuves ciblées sur ce qui coince, avec le "
                "rappel de cours dans chaque correction." % candidates[0]["reason"].capitalize())
            btn_refresh.clicked.connect(
                lambda _=False, c=cid: self.session_requested.emit("refresher:" + c))
            actions.addWidget(btn_refresh)

        btn_challenge = QPushButton("Défi éclair")
        btn_challenge.setToolTip("Cinq questions déjà vues, chronométrées.")
        btn_challenge.clicked.connect(lambda: self.session_requested.emit("challenge"))
        actions.addWidget(btn_challenge)

        # fiches de lacunes : fin de seance, validation, compteur
        gs = gaps.stats()
        if gs["proposed"]:
            btn_gaps = QPushButton("Valider %d fiche%s de lacunes"
                                   % (gs["proposed"], "s" if gs["proposed"] > 1 else ""))
            btn_gaps.setProperty("primary", True)
            btn_gaps.clicked.connect(lambda: self.session_requested.emit("gaps-validate"))
        else:
            btn_gaps = QPushButton("Fin de séance : mes lacunes")
            btn_gaps.setToolTip("Relit vos questions à l'assistant depuis la dernière fois et "
                                "propose une fiche par notion de base oubliée.")
            btn_gaps.clicked.connect(lambda: self.session_requested.emit("gaps-scan"))
        actions.addWidget(btn_gaps)
        if gs["active"]:
            label = QLabel("fiches : %d acquise%s · %d en cours"
                           % (gs["acquired"], "s" if gs["acquired"] > 1 else "", gs["learning"]))
            label.setObjectName("Muted")
            label.setToolTip("Une fiche est acquise quand elle ne revient plus qu'au bout "
                             "de trois semaines.")
            actions.addWidget(label)

        upcoming = review_mod.upcoming(8)
        if sum(upcoming[1:]):
            nxt = next((i for i, n in enumerate(upcoming) if n and i > 0), None)
            if nxt:
                label = QLabel("prochaine échéance : %d question%s dans %d jour%s"
                               % (upcoming[nxt], "s" if upcoming[nxt] > 1 else "",
                                  nxt, "s" if nxt > 1 else ""))
                label.setObjectName("Muted")
                actions.addWidget(label)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        card.lay.addWidget(holder)
        self.root.addWidget(card)

    # ------------------------------------------------------------ progression
    def _progression(self, statuses: Dict[str, Status], pal: dict) -> None:
        total = gamify.xp_total()
        level, into, need = gamify.level_of(total)
        week = gamify.xp_last_days(7)
        self._section_title("Niveau %d" % level,
                            "%d XP au total  ·  %d cette semaine" % (total, week))
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(14)
        bar = _bar(into, need, pal["accent"])
        bar.setMinimumWidth(220)
        row.addWidget(bar, 1)
        row.addWidget(QLabel("%d / %d XP" % (into, need)))
        holder = QWidget()
        holder.setLayout(row)
        card.lay.addWidget(holder)

        by_domain = gamify.xp_by_domain()
        if by_domain:
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(7)
            ordered = sorted(by_domain.items(), key=lambda kv: -kv[1])[:10]
            for i, (did, xp) in enumerate(ordered):
                dlevel, dinto, dneed = gamify.level_of(xp)
                name = QLabel(self.syl.domain_name(did))
                name.setStyleSheet("color:%s;font-weight:600" % self.syl.domain_color(did))
                grid.addWidget(name, i, 0)
                dbar = _bar(dinto, dneed, self.syl.domain_color(did))
                dbar.setMinimumWidth(140)
                grid.addWidget(dbar, i, 1)
                tag = QLabel("niveau %d" % dlevel)
                tag.setObjectName("Muted")
                grid.addWidget(tag, i, 2)
            holder = QWidget()
            holder.setLayout(grid)
            card.lay.addWidget(holder)
        self.root.addWidget(card)

    # ---------------------------------------------------------------- jalons
    def _milestones(self, statuses: Dict[str, Status], pal: dict) -> None:
        ctx = gamify.build_context(self.syl, statuses)
        gamify.check_milestones(ctx)
        reached = gamify.reached_ids()
        done = [m for m in gamify.MILESTONES if m.id in reached]
        todo = [m for m in gamify.MILESTONES if m.id not in reached]

        def distance(milestone):
            if milestone.progress is None:
                return 1.0
            try:
                value, target = milestone.progress(ctx)
            except Exception:  # noqa: BLE001
                return 1.0
            return 1.0 - min(1.0, value / max(1, target))

        todo.sort(key=distance)
        self._section_title("Jalons", "%d sur %d" % (len(done), len(gamify.MILESTONES)))
        card = Card()
        for milestone in done[-3:] + todo[:5]:
            got = milestone.id in reached
            row = QHBoxLayout()
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(10)
            mark = QLabel("✓" if got else "○")
            mark.setStyleSheet("color:%s;font-weight:700"
                               % (pal["ok"] if got else pal["muted"]))
            row.addWidget(mark)
            label = QLabel(milestone.label)
            if not got:
                label.setObjectName("Muted")
            label.setToolTip(milestone.detail or milestone.label)
            row.addWidget(label, 1)
            if not got and milestone.progress is not None:
                try:
                    value, target = milestone.progress(ctx)
                    count = QLabel("%d / %d" % (value, target))
                    count.setObjectName("Muted")
                    row.addWidget(count)
                except Exception:  # noqa: BLE001
                    pass
            holder = QWidget()
            holder.setLayout(row)
            card.lay.addWidget(holder)
        self.root.addWidget(card)

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

    def _welcome(self, pal: dict) -> None:
        """Seul le socle de maths est actif : on montre comment aller plus loin."""
        if any(p.id not in (curriculum.BASE_PACK, curriculum.CUSTOM_PACK)
               for p in self.syl.packs.values()):
            return
        card = Card()
        name = QLabel("Étendre le cursus à votre domaine")
        name.setObjectName("H2")
        card.lay.addWidget(name)
        text = QLabel(
            "Les mathématiques sont le socle. Décrivez vos objectifs (physique "
            "quantique, chimie, neurosciences…) : Claude conçoit le cursus complet, "
            "fondations comprises, branché sur ces cours de maths. D'autres packs sont "
            "déjà prêts, comme l'apprentissage automatique.")
        text.setObjectName("Muted")
        text.setWordWrap(True)
        card.lay.addWidget(text)
        row = QHBoxLayout()
        btn = QPushButton("Créer un cursus…")
        btn.setProperty("primary", True)
        btn.clicked.connect(self.curriculum_requested.emit)
        row.addWidget(btn)
        row.addStretch(1)
        host = QWidget()
        host.setLayout(row)
        card.lay.addWidget(host)
        self.root.addWidget(card)

    def _tracks(self, group: str, tracks, statuses: Dict[str, Status], pal: dict) -> None:
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
            info = QLabel("%d cours%s  ·  %d maîtrisé%s  ·  %d généré%s"
                          % (len(path), " choisis, dans l'ordre" if track.courses else "", done, "s" if done > 1 else "",
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

    def _tracks_compact(self, group: str, tracks, statuses: Dict[str, Status],
                        pal: dict) -> None:
        """Groupe trop fourni pour des cartes : une ligne par parcours."""
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

    def _week(self, statuses: Dict[str, Status], pal: dict) -> None:
        now = gamify.week_totals(0)
        before = gamify.week_totals(1)
        if not now["questions"] and not before["questions"]:
            return

        def delta(key: str, suffix: str = "") -> str:
            diff = (now[key] or 0) - (before[key] or 0)
            if not diff:
                return "<span style='color:%s'>inchangé</span>" % pal["muted"]
            colour = pal["ok"] if diff > 0 else pal["warn"]
            return ("<span style='color:%s'>%+d%s</span>" % (colour, diff, suffix))

        self._section_title("Cette semaine",
                            "du %s au %s" % (now["first"][8:10] + "/" + now["first"][5:7],
                                             now["last"][8:10] + "/" + now["last"][5:7]))
        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        rows = [
            ("Questions", "%d" % now["questions"], delta("questions")),
            ("Score moyen", "%s" % ("%d %%" % now["score"] if now["score"] is not None else "—"),
             ("<span style='color:%s'>%+d pts</span>"
              % (pal["ok"] if (now["score"] or 0) >= (before["score"] or 0) else pal["warn"],
                 (now["score"] or 0) - (before["score"] or 0))
              if now["score"] is not None and before["score"] is not None
              else "<span style='color:%s'>—</span>" % pal["muted"])),
            ("Révisions", "%d" % now["reviews"], delta("reviews")),
            ("Démonstrations", "%d" % now["proofs"], delta("proofs")),
            ("Jours travaillés", "%d / 7" % now["days"], delta("days")),
            ("XP", "%d" % now["xp"], delta("xp")),
        ]
        for i, (label, value, change) in enumerate(rows):
            name = QLabel(label)
            name.setObjectName("Muted")
            grid.addWidget(name, i, 0)
            val = QLabel(value)
            val.setStyleSheet("font-weight:600")
            grid.addWidget(val, i, 1)
            chg = QLabel(change)
            chg.setTextFormat(Qt.TextFormat.RichText)
            grid.addWidget(chg, i, 2)
        grid.setColumnStretch(3, 1)
        holder = QWidget()
        holder.setLayout(grid)
        card.lay.addWidget(holder)

        gains = gamify.week_domains(0)
        if gains:
            best = max(gains.items(), key=lambda kv: kv[1])
            line = QLabel("Le domaine qui a le plus avancé : "
                          "<span style='color:%s;font-weight:600'>%s</span> (+%d XP)"
                          % (self.syl.domain_color(best[0]),
                             self.syl.domain_name(best[0]), best[1]))
            line.setTextFormat(Qt.TextFormat.RichText)
            card.lay.addWidget(line)
        stale = [did for did in self.syl.domain_order
                 if did not in gains and gamify.xp_by_domain().get(did)]
        if stale:
            line = QLabel("Sans activité cette semaine : %s"
                          % ", ".join(self.syl.domain_name(d) for d in stale[:4]))
            line.setObjectName("Muted")
            line.setWordWrap(True)
            card.lay.addWidget(line)
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
