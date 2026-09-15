"""Page d'un cours : lecture, QCM, demonstrations, notes."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from .. import content, gamify, status as st_mod, store
from ..paths import ASSETS_DIR, library_dir
from ..syllabus import Course, Syllabus
from . import theme
from .webview import WebView

TAB_COURSE, TAB_SHEET, TAB_QUIZ, TAB_PROOFS, TAB_NOTES = range(5)


def _page_path(name: str):
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


class Chip(QPushButton):
    def __init__(self, text: str, tone: str = "chip", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        pal = theme.palette()
        colors = {
            "chip": (pal["bg3"], pal["fg2"], pal["line"]),
            "ok": (pal["ok_soft"], pal["ok"], pal["ok"]),
            "warn": (pal["warn_soft"], pal["warn"], pal["warn"]),
            "accent": (pal["accent_soft"], pal["accent"], pal["accent"]),
        }
        bg, fg, border = colors.get(tone, colors["chip"])
        self.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:999px;"
            "padding:3px 11px;font-size:11.5px;font-weight:500;}"
            "QPushButton:hover{border-color:%s;}" % (bg, fg, border, pal["accent"]))


class EmptyState(QWidget):
    """Ce qu'on voit quand le cours n'est pas encore genere."""

    generate = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        outer.addWidget(area)

        inner = QWidget()
        area.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(56, 46, 56, 56)
        lay.setSpacing(14)

        self.title = QLabel()
        self.title.setObjectName("H1")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        lay.addSpacing(10)
        self.obj_title = QLabel("Ce que ce cours doit vous apprendre")
        self.obj_title.setObjectName("H2")
        lay.addWidget(self.obj_title)
        self.objectives = QLabel()
        self.objectives.setWordWrap(True)
        self.objectives.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.objectives)

        lay.addSpacing(18)
        self.resume = False
        self.btn = QPushButton("Générer ce cours")
        self.btn.setProperty("primary", True)
        self.btn.setFixedWidth(220)
        self.btn.clicked.connect(self.generate.emit)
        lay.addWidget(self.btn)

        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(360)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.phase = QLabel("")
        self.phase.setObjectName("Muted")
        self.phase.setVisible(False)
        lay.addWidget(self.phase)

        lay.addStretch(1)

    def set_course(self, syl: Syllabus, course: Course, st: st_mod.Status) -> None:
        pal = theme.palette()
        self.resume = st.partial
        self.btn.setText("Reprendre la génération" if st.partial else "Générer ce cours")
        self.title.setText(course.title)
        self.summary.setText(course.summary)
        self.objectives.setText(
            "<ul style='margin-left:-18px'>%s</ul>"
            % "".join("<li style='margin-bottom:5px'>%s</li>" % o for o in course.objectives))
        if st.missing:
            names = ", ".join(syl.title(m) for m in st.missing[:4])
            more = "" if len(st.missing) <= 4 else " (+%d)" % (len(st.missing) - 4)
            self.note.setText(
                "<span style='color:%s'>Prérequis non encore maîtrisés : %s%s. "
                "Rien n'empêche de générer ce cours, mais il sera plus dur à suivre.</span>"
                % (pal["warn"], names, more))
        elif st.partial:
            self.note.setText(
                "<span style='color:%s'>Génération interrompue : %d section%s sur %d "
                "déjà écrite%s. Reprendre ne refait pas ce qui est déjà là.</span>"
                % (pal["warn"], st.sections_done, "s" if st.sections_done > 1 else "",
                   st.sections_total, "s" if st.sections_done > 1 else ""))
        else:
            self.note.setText("Généré par le Claude local. Comptez quelques minutes : "
                              "plan, puis chaque section, puis les exercices.")

    def set_sheet_placeholder(self, course: Course) -> None:
        self.title.setText("Fiche de révision")
        self.summary.setText(
            "Une version condensée de « %s » : définitions, résultats, formules, "
            "méthodes, pièges, et un rappel actif pour se tester. Deux à quatre "
            "pages, exportables en PDF." % course.title)
        self.obj_title.setText("Ce que contient une fiche")
        self.objectives.setText(
            "<ul style='margin-left:-18px'>"
            "<li style='margin-bottom:5px'>les définitions et les énoncés exacts, "
            "hypothèses comprises</li>"
            "<li style='margin-bottom:5px'>un tableau de formules</li>"
            "<li style='margin-bottom:5px'>les méthodes, formulées comme « pour "
            "montrer que…, faire… »</li>"
            "<li style='margin-bottom:5px'>les pièges du cours</li>"
            "<li style='margin-bottom:5px'>des questions de rappel avec réponses "
            "masquées</li></ul>")
        self.btn.setText("Générer la fiche")
        self.note.setText("Produite à partir du cours déjà rédigé. Une minute environ.")

    def set_progress(self, running: bool, frac: float = 0.0, label: str = "") -> None:
        self.btn.setVisible(not running)
        self.progress.setVisible(running)
        self.phase.setVisible(running)
        if running:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(frac * 1000))
            self.phase.setText(label)


class CoursePage(QWidget):
    open_course = Signal(str)
    ask_requested = Signal(str, str, str)          # course_id, extrait, section
    proof_help_requested = Signal(str, str, str, str)  # course_id, proof_id, titre, texte
    proof_review_requested = Signal(str, str, str)     # course_id, proof_id, charge utile
    generate_requested = Signal(list)
    regenerate_requested = Signal(str)
    exercises_requested = Signal(str)
    sheet_requested = Signal(str)
    quiz_set_requested = Signal(str)
    sheet_export_requested = Signal(str)
    progress_made = Signal()
    cancel_requested = Signal(str)

    def __init__(self, syllabus: Syllabus, parent=None):
        super().__init__(parent)
        self.syl = syllabus
        self.course: Optional[Course] = None
        self.status: Optional[st_mod.Status] = None
        self._statuses: Dict[str, st_mod.Status] = {}
        self._loaded_tabs: set = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ----------------------------------------------------------- en-tete
        head = QFrame()
        head.setObjectName("TopBar")
        hv = QVBoxLayout(head)
        hv.setContentsMargins(18, 12, 16, 10)
        hv.setSpacing(8)

        line1 = QHBoxLayout()
        line1.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("H1")
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        line1.addWidget(self.title, 1)

        self.btn_ask = QPushButton("Discuter")
        self.btn_ask.setToolTip("Ouvrir le chat sur ce cours")
        self.btn_ask.clicked.connect(lambda: self.ask_requested.emit(
            self.course.id if self.course else "", "", ""))
        line1.addWidget(self.btn_ask)

        self.btn_gen = QPushButton("Générer")
        self.btn_gen.setProperty("primary", True)
        self.btn_gen.clicked.connect(self._on_generate_clicked)
        line1.addWidget(self.btn_gen)

        self.btn_more = QPushButton("...")
        self.btn_more.setFixedWidth(38)
        self.btn_more.clicked.connect(self._show_menu)
        line1.addWidget(self.btn_more)
        hv.addLayout(line1)

        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        self.chips_row.addStretch(1)
        chips_host = QWidget()
        chips_host.setLayout(self.chips_row)
        hv.addWidget(chips_host)
        root.addWidget(head)

        # ---------------------------------------------------------- onglets
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab)
        root.addWidget(self.tabs, 1)

        self.empty = EmptyState()
        self.empty.generate.connect(lambda: self.generate_requested.emit(
            [self.course.id] if self.course else []))

        self.course_view = WebView(with_bridge=True)
        self._pending_section = ""
        self._course_loading = False
        self.course_view.loadFinished.connect(self._on_course_loaded)
        self.course_view.bridge.ask_requested.connect(self._forward_ask)
        self.course_view.bridge.proof_help_requested.connect(self._forward_proof_help)

        self.course_holder = QWidget()
        ch = QVBoxLayout(self.course_holder)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.addWidget(self.empty)
        ch.addWidget(self.course_view)

        self.quiz_view = WebView(with_bridge=True)
        self.quiz_view.bridge.quiz_finished.connect(self._on_quiz_finished)
        self.quiz_view.bridge.ask_requested.connect(self._forward_ask)
        self.quiz_view.bridge.quiz_set_requested.connect(
            lambda: self.quiz_set_requested.emit(self.course.id) if self.course else None)

        self.proofs_view = WebView(with_bridge=True)
        self.proofs_view.bridge.proof_status_changed.connect(self._on_proof_status)
        self.proofs_view.bridge.proof_draft_changed.connect(self._on_proof_draft)
        self.proofs_view.bridge.proof_review_requested.connect(self._on_proof_review)
        self.proofs_view.bridge.proof_help_requested.connect(self._forward_proof_help)
        self.proofs_view.bridge.ask_requested.connect(self._forward_ask)

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText(
            "Vos notes sur ce cours : ce qui coince, les analogies qui marchent, "
            "les exercices à refaire.")
        notes_host = QWidget()
        nv = QVBoxLayout(notes_host)
        nv.setContentsMargins(20, 16, 20, 16)
        nv.addWidget(self.notes)
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(900)
        self._notes_timer.timeout.connect(self._save_notes)
        self.notes.textChanged.connect(lambda: self._notes_timer.start())

        # --------------------------------------------------------- fiche
        self.sheet_view = WebView(with_bridge=True)
        self.sheet_view.bridge.ask_requested.connect(self._forward_ask)

        self.sheet_holder = QWidget()
        sh = QVBoxLayout(self.sheet_holder)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)

        sheet_bar = QWidget()
        sheet_bar.setObjectName("TopBar")
        sb = QHBoxLayout(sheet_bar)
        sb.setContentsMargins(14, 7, 14, 7)
        sb.setSpacing(8)
        hint = QLabel("Version condensée, pour revenir sur le cours. "
                      "Les réponses du rappel actif se dévoilent au clic.")
        hint.setObjectName("Muted")
        sb.addWidget(hint)
        sb.addStretch(1)
        self.btn_reveal = QPushButton("Tout dévoiler")
        self.btn_reveal.setProperty("flat", True)
        self.btn_reveal.clicked.connect(
            lambda: self.sheet_view.run_js("window.revealAll && window.revealAll();"))
        sb.addWidget(self.btn_reveal)
        self.btn_sheet_again = QPushButton("Régénérer")
        self.btn_sheet_again.setProperty("flat", True)
        self.btn_sheet_again.clicked.connect(
            lambda: self.sheet_requested.emit(self.course.id) if self.course else None)
        sb.addWidget(self.btn_sheet_again)
        self.btn_pdf = QPushButton("Exporter en PDF")
        self.btn_pdf.setProperty("primary", True)
        self.btn_pdf.clicked.connect(
            lambda: self.sheet_export_requested.emit(self.course.id) if self.course else None)
        sb.addWidget(self.btn_pdf)
        sh.addWidget(sheet_bar)

        self.sheet_empty = EmptyState()
        self.sheet_empty.generate.connect(
            lambda: self.sheet_requested.emit(self.course.id) if self.course else None)
        sh.addWidget(self.sheet_empty)
        sh.addWidget(self.sheet_view)
        self.sheet_bar = sheet_bar

        self.tabs.addTab(self.course_holder, "Cours")
        self.tabs.addTab(self.sheet_holder, "Fiche")
        self.tabs.addTab(self.quiz_view, "QCM")
        self.tabs.addTab(self.proofs_view, "Démonstrations")
        self.tabs.addTab(notes_host, "Notes")

    def set_syllabus(self, syl: Syllabus) -> None:
        self.syl = syl
        if self.course is not None and self.course.id not in syl.courses:
            self.course = None
            return
        if self.course is not None:
            self.course = syl.get(self.course.id)
            self.refresh()

    # -------------------------------------------------------------- chargement
    def scroll_to_section(self, title: str) -> None:
        """Amene la vue du cours sur une section, des que la page est prete."""
        if not title or self.course is None:
            return
        self._pending_section = title
        self.tabs.setCurrentIndex(TAB_COURSE)
        if TAB_COURSE in self._loaded_tabs and not self._course_loading:
            self._apply_pending_section()

    def _on_course_loaded(self, _ok: bool) -> None:
        self._course_loading = False
        if self._pending_section:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(450, self._apply_pending_section)

    def _apply_pending_section(self) -> None:
        import json as _json
        title, self._pending_section = self._pending_section, ""
        if title:
            self.course_view.run_js("window.scrollToSection && window.scrollToSection(%s);"
                                    % _json.dumps(title))

    def show_course(self, course_id: str) -> None:
        same = self.course is not None and self.course.id == course_id
        self.course = self.syl.get(course_id)
        if self.course is None:
            return
        if not same:
            self._loaded_tabs.clear()
            self.notes.blockSignals(True)
            self.notes.setPlainText(store.get_notes(course_id))
            self.notes.blockSignals(False)
            store.mark_opened(course_id)
            self.tabs.setCurrentIndex(TAB_COURSE)
        self.refresh()

    def refresh(self) -> None:
        if self.course is None:
            return
        cid = self.course.id
        self._statuses = st_mod.compute(self.syl)
        self.status = self._statuses[cid]
        self.title.setText(self.course.title)
        self._build_chips()

        readable = self.status.complete
        self.empty.setVisible(not readable)
        self.course_view.setVisible(readable)
        has_sheet = content.has_sheet(cid)
        self.tabs.setTabEnabled(TAB_SHEET, self.status.generated)
        self.sheet_bar.setVisible(has_sheet)
        self.sheet_view.setVisible(has_sheet)
        self.sheet_empty.setVisible(not has_sheet)
        if not has_sheet:
            self.sheet_empty.set_sheet_placeholder(self.course)
        self.tabs.setTabEnabled(TAB_QUIZ, self.status.has_exercises)
        self.tabs.setTabEnabled(TAB_PROOFS, self.status.has_exercises)
        if not readable:
            self.empty.set_course(self.syl, self.course, self.status)
        self._sync_generate_button()
        self._on_tab(self.tabs.currentIndex())

    def _build_chips(self) -> None:
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        course, st = self.course, self.status
        pal = theme.palette()

        dom = Chip(self.syl.domain_name(course.domain))
        dom.setStyleSheet(dom.styleSheet().replace(pal["fg2"], self.syl.domain_color(course.domain)))
        dom.setEnabled(False)
        self.chips_row.addWidget(dom)

        lvl = Chip("Niveau %d — %s" % (course.level, self.syl.levels.get(course.level, "")))
        lvl.setEnabled(False)
        self.chips_row.addWidget(lvl)

        state_tone = {"mastered": "ok", "started": "warn", "locked": "chip"}.get(st.state, "accent")
        state_text = st.label
        if st.score_pct is not None:
            state_text += "  ·  %d %%" % st.score_pct
            if not st.enough_answered:
                state_text += "  (%d/%d tentées)" % (st.answered, st.questions_needed)
        state = Chip(state_text, state_tone)
        state.setEnabled(False)
        self.chips_row.addWidget(state)

        if course.prereqs:
            label = QLabel("Prerequis")
            label.setObjectName("Muted")
            label.setStyleSheet("padding-left:8px")
            self.chips_row.addWidget(label)
            for pid in course.prereqs:
                ok = self._statuses[pid].mastered
                chip = Chip(self.syl.title(pid), "ok" if ok else "warn")
                chip.setToolTip("Maîtrisé" if ok else "Pas encore maitrise — cliquez pour l'ouvrir")
                chip.clicked.connect(lambda _=False, p=pid: self.open_course.emit(p))
                self.chips_row.addWidget(chip)
        self.chips_row.addStretch(1)

    def _on_tab(self, index: int) -> None:
        if self.course is None or index in self._loaded_tabs:
            return
        cid = self.course.id
        if index == TAB_COURSE and self.status and self.status.generated:
            path = content.render_course_page(cid, self.course.title, theme.name())
            self._course_loading = True
            self.course_view.load_file(path)
            self._loaded_tabs.add(index)
        elif index == TAB_SHEET and content.has_sheet(cid):
            path = content.render_sheet_page(cid, self.course.title, theme.name())
            self.sheet_view.load_file(path)
            self._loaded_tabs.add(index)
        elif index == TAB_QUIZ and self.status and self.status.has_exercises:
            self._load_quiz()
            self._loaded_tabs.add(index)
        elif index == TAB_PROOFS and self.status and self.status.has_exercises:
            self._load_proofs()
            self._loaded_tabs.add(index)

    def _load_quiz(self) -> None:
        sets = content.quiz_sets(self.course.id)
        history = store.question_history(self.course.id)
        tpl = (ASSETS_DIR / "quiz.html").read_text(encoding="utf-8")
        page = (tpl.replace("__THEME__", theme.name())
                   .replace("__ASSETS__", content.assets_url())
                   .replace("__SETS__", json.dumps(content.protect_math_data(sets), ensure_ascii=False))
                   .replace("__HISTORY__", json.dumps(history, ensure_ascii=False)))
        path = _page_path("quiz_%s.html" % self.course.id)
        path.write_text(page, encoding="utf-8")
        self.quiz_view.load_file(path)

    def _load_proofs(self) -> None:
        data = content.read_exercises(self.course.id) or {"proofs": []}
        statuses = store.proof_statuses(self.course.id)
        drafts = store.proof_drafts(self.course.id)
        tpl = (ASSETS_DIR / "proofs.html").read_text(encoding="utf-8")
        page = (tpl.replace("__THEME__", theme.name())
                   .replace("__ASSETS__", content.assets_url())
                   .replace("__DATA__", json.dumps(content.protect_math_data(data), ensure_ascii=False))
                   .replace("__STATUS__", json.dumps(statuses, ensure_ascii=False))
                   .replace("__DRAFTS__", json.dumps(drafts, ensure_ascii=False)))
        path = _page_path("proofs_%s.html" % self.course.id)
        path.write_text(page, encoding="utf-8")
        self.proofs_view.load_file(path)

    def reload_quiz(self) -> None:
        """Apres l'ajout d'une serie : on recharge la page de QCM."""
        self._loaded_tabs.discard(TAB_QUIZ)
        if self.tabs.currentIndex() == TAB_QUIZ:
            self._on_tab(TAB_QUIZ)

    def reload_content(self) -> None:
        """Force le rechargement des vues web (apres une (re)generation)."""
        self._loaded_tabs.clear()
        self.refresh()

    # ----------------------------------------------------------------- actions
    def _sync_generate_button(self) -> None:
        st = self.status
        if st is None:
            return
        if st.partial:
            self.btn_gen.setText("Reprendre")
            self.btn_gen.setToolTip("%d section(s) sur %d déjà écrites"
                                    % (st.sections_done, st.sections_total))
        elif st.complete:
            self.btn_gen.setText("Régénérer")
            self.btn_gen.setToolTip("Refait le cours entier depuis un nouveau plan")
        else:
            self.btn_gen.setText("Générer")
            self.btn_gen.setToolTip("")

    def _on_generate_clicked(self) -> None:
        if self.course is None:
            return
        if self.status is not None and self.status.complete:
            self.regenerate_requested.emit(self.course.id)
        else:
            self.generate_requested.emit([self.course.id])

    def _show_menu(self) -> None:
        if self.course is None:
            return
        cid = self.course.id
        menu = QMenu(self)
        if self.status and self.status.generated:
            act = QAction("Régénérer la fiche de révision" if content.has_sheet(cid)
                          else "Générer la fiche de révision", self)
            act.triggered.connect(lambda: self.sheet_requested.emit(cid))
            menu.addAction(act)
        if self.status and self.status.complete:
            act = QAction("Régénérer seulement les exercices", self)
            act.triggered.connect(lambda: self.exercises_requested.emit(cid))
            menu.addAction(act)
            act = QAction("Régénérer le cours entier", self)
            act.triggered.connect(lambda: self.regenerate_requested.emit(cid))
            menu.addAction(act)
        missing = [c for c in self.syl.path_to(cid) if not content.is_complete(c)]
        if missing:
            act = QAction("Générer tout le chemin de prérequis (%d cours)" % len(missing), self)
            act.triggered.connect(lambda: self.generate_requested.emit(missing))
            menu.addAction(act)
        act = QAction("Annuler la génération en cours", self)
        act.triggered.connect(lambda: self.cancel_requested.emit(cid))
        menu.addAction(act)
        menu.addSeparator()
        act = QAction("Ouvrir le dossier du cours", self)
        act.triggered.connect(self._reveal)
        menu.addAction(act)
        menu.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def _reveal(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from ..paths import course_dir
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(course_dir(self.course.id, create=True))))

    def set_generation_progress(self, running: bool, frac: float, label: str) -> None:
        self.empty.set_progress(running, frac, label)
        self.btn_gen.setEnabled(not running)
        if running:
            self.btn_gen.setText("Génération  %d %%" % int(frac * 100))
            self.btn_gen.setToolTip(label)
        else:
            self._sync_generate_button()

    def apply_theme(self) -> None:
        for view in (self.course_view, self.sheet_view, self.quiz_view, self.proofs_view):
            view.set_theme(theme.name())
        if self.course:
            self._build_chips()

    # ------------------------------------------------------------------ ponts
    def _forward_ask(self, text: str, heading: str) -> None:
        if self.course:
            self.ask_requested.emit(self.course.id, text, heading)

    def _forward_proof_help(self, proof_id: str, heading: str, text: str) -> None:
        if self.course:
            self.proof_help_requested.emit(self.course.id, proof_id, heading, text)

    def _on_quiz_finished(self, payload: str) -> None:
        if self.course is None:
            return
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        store.record_attempt(self.course.id, int(data.get("total", 0)),
                             int(data.get("correct", 0)), data,
                             set_id=str(data.get("setId") or "1"),
                             partial=bool(data.get("partial")))
        self.refresh()
        st = self.status
        if st is not None and st.score_pct is not None:
            self.quiz_view.run_js(
                "window.showCourseScore && window.showCourseScore(%d, %d, %d, %d);"
                % (st.score_pct, st.correct, st.answered, st.questions_total))

    def _on_proof_status(self, proof_id: str, value: str) -> None:
        if not self.course:
            return
        before = store.proof_statuses(self.course.id).get(proof_id)
        store.set_proof_status(self.course.id, proof_id, value)
        if value == "done" and before != "done":
            gamify.log("proof_solved", proofs=1, brick=True,
                       xp=gamify.XP["proof_solved"], domain=self.course.domain)
            self.progress_made.emit()

    def _on_proof_draft(self, proof_id: str, text: str) -> None:
        if self.course:
            store.set_proof_draft(self.course.id, proof_id, text)

    def _on_proof_review(self, proof_id: str, payload: str) -> None:
        if self.course:
            self.proof_review_requested.emit(self.course.id, proof_id, payload)

    def _save_notes(self) -> None:
        if self.course:
            store.set_notes(self.course.id, self.notes.toPlainText())
