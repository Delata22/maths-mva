"""Boite de dialogue des preferences."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import settings
from ..generation import claude_cli as cc
from . import theme

MODELS = ["opus", "sonnet", "haiku"]


def _model_combo(key: str) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.addItems(MODELS)
    current = str(settings.get(key))
    if current not in MODELS:
        box.addItem(current)
    box.setCurrentText(current)
    return box


class PrefsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Préférences")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setSpacing(14)

        models = QGroupBox("Modèles")
        mf = QFormLayout(models)
        self.m_course = _model_combo("model/course")
        self.m_exos = _model_combo("model/exercises")
        self.m_chat = _model_combo("model/chat")
        mf.addRow("Cours", self.m_course)
        mf.addRow("Exercices", self.m_exos)
        mf.addRow("Chat", self.m_chat)
        root.addWidget(models)

        gen = QGroupBox("Génération")
        gf = QFormLayout(gen)
        self.backend = QComboBox()
        self.backend.addItem("Automatique (le CLI installé)", "auto")
        self.backend.addItem("Claude (CLI claude)", "claude")
        self.backend.addItem("Codex (CLI codex)", "codex")
        self.backend.setCurrentIndex(max(0, self.backend.findData(str(settings.get("gen/backend")))))
        self.backend.setToolTip(
            "Quel assistant en ligne de commande produit les cours. Avec codex, les "
            "coûts affichés restent à zéro (le CLI ne les donne pas) et la lecture "
            "des PDF passe par pdftotext.")
        gf.addRow("Moteur", self.backend)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setValue(int(settings.get("gen/concurrency")))
        self.concurrency.setToolTip("Nombre de cours générés en parallèle.")
        gf.addRow("Générations en parallèle", self.concurrency)

        self.section_parallel = QSpinBox()
        self.section_parallel.setRange(1, 6)
        self.section_parallel.setValue(int(settings.get("gen/section_parallel")))
        self.section_parallel.setToolTip(
            "Sections d'un même cours rédigées en parallèle. Accélère nettement "
            "la génération ; 3 est un bon compromis.")
        gf.addRow("Sections en parallèle", self.section_parallel)

        self.sections = QSpinBox()
        self.sections.setRange(4, 14)
        self.sections.setValue(int(settings.get("gen/max_sections")))
        self.sections.setToolTip("Plus de sections = cours plus long et plus détaillé.")
        gf.addRow("Sections maximum par cours", self.sections)

        self.timeout = QSpinBox()
        self.timeout.setRange(120, 7200)
        self.timeout.setSingleStep(60)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(settings.get("claude/timeout")))
        gf.addRow("Délai maximum par appel", self.timeout)

        self.stall = QSpinBox()
        self.stall.setRange(60, 1800)
        self.stall.setSingleStep(30)
        self.stall.setSuffix(" s")
        self.stall.setValue(int(settings.get("claude/stall_timeout")))
        self.stall.setToolTip(
            "Silence au-delà duquel un appel est considéré comme perdu : il est "
            "interrompu, puis relancé automatiquement. Une section longue peut "
            "rester muette une à deux minutes, ne descendez pas trop bas.")
        gf.addRow("Silence toléré", self.stall)

        self.retries = QSpinBox()
        self.retries.setRange(1, 6)
        self.retries.setValue(int(settings.get("claude/retries")))
        self.retries.setToolTip("Nombre de tentatives sur une erreur réseau.")
        gf.addRow("Tentatives par appel", self.retries)

        self.binary = QLineEdit(str(settings.get("claude/binary")))
        gf.addRow("Binaire claude", self.binary)
        self.codex_binary = QLineEdit(str(settings.get("codex/binary")))
        gf.addRow("Binaire codex", self.codex_binary)
        self.codex_strong = QLineEdit(str(settings.get("codex/model_strong")))
        self.codex_strong.setPlaceholderText("vide = modèle par défaut de codex")
        self.codex_strong.setToolTip("Modèle codex utilisé là où l'app demande « opus ».")
        gf.addRow("Modèle codex (cours)", self.codex_strong)
        self.codex_fast = QLineEdit(str(settings.get("codex/model_fast")))
        self.codex_fast.setPlaceholderText("vide = modèle par défaut de codex")
        self.codex_fast.setToolTip("Modèle codex utilisé là où l'app demande « sonnet ».")
        gf.addRow("Modèle codex (exercices)", self.codex_fast)
        self.test = QPushButton("Tester le CLI")
        self.test.clicked.connect(self._test)
        gf.addRow("", self.test)
        self.test_result = QLabel("")
        self.test_result.setObjectName("Muted")
        self.test_result.setWordWrap(True)
        gf.addRow("", self.test_result)
        root.addWidget(gen)

        ui = QGroupBox("Interface")
        uf = QFormLayout(ui)
        self.threshold = QSpinBox()
        self.threshold.setRange(50, 100)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(int(settings.get("ui/mastery_threshold")))
        self.threshold.setToolTip("Score de QCM à partir duquel un cours est considéré maîtrisé "
                                  "et débloque ses suites.")
        uf.addRow("Seuil de maîtrise", self.threshold)

        self.goal = QSpinBox()
        self.goal.setRange(1, 6)
        self.goal.setValue(int(settings.get("goal/bricks")))
        self.goal.setToolTip(
            "Nombre de briques à faire par jour pour tenir la série. Une brique = "
            "une séance de QCM, une révision terminée, une démonstration soumise "
            "ou réussie. Une seule suffit pour que l'habitude prenne.")
        uf.addRow("Objectif quotidien", self.goal)

        self.review_batch = QSpinBox()
        self.review_batch.setRange(5, 60)
        self.review_batch.setSingleStep(5)
        self.review_batch.setValue(int(settings.get("goal/review_batch")))
        self.review_batch.setToolTip(
            "Nombre maximum de questions par séance de révision, même s'il y en "
            "a davantage à revoir. Le reste attendra demain.")
        uf.addRow("Révisions par séance", self.review_batch)

        self.theme = QComboBox()
        self.theme.addItem("Clair", "light")
        self.theme.addItem("Sombre", "dark")
        self.theme.setCurrentIndex(1 if theme.name() == "dark" else 0)
        uf.addRow("Thème", self.theme)
        root.addWidget(ui)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _test(self) -> None:
        settings.put("gen/backend", self.backend.currentData())
        settings.put("claude/binary", self.binary.text().strip() or "claude")
        settings.put("codex/binary", self.codex_binary.text().strip() or "codex")
        try:
            version = cc.check_available()
        except cc.ClaudeError as exc:
            self.test_result.setText(str(exc))
        else:
            self.test_result.setText("CLI détecté : %s" % version)

    def apply(self) -> None:
        settings.put("model/course", self.m_course.currentText().strip())
        settings.put("model/exercises", self.m_exos.currentText().strip())
        settings.put("model/chat", self.m_chat.currentText().strip())
        settings.put("gen/concurrency", self.concurrency.value())
        settings.put("gen/section_parallel", self.section_parallel.value())
        settings.put("gen/max_sections", self.sections.value())
        settings.put("claude/timeout", self.timeout.value())
        settings.put("claude/stall_timeout", self.stall.value())
        settings.put("claude/retries", self.retries.value())
        settings.put("claude/binary", self.binary.text().strip() or "claude")
        settings.put("gen/backend", self.backend.currentData())
        settings.put("codex/binary", self.codex_binary.text().strip() or "codex")
        settings.put("codex/model_strong", self.codex_strong.text().strip())
        settings.put("codex/model_fast", self.codex_fast.text().strip())
        settings.put("ui/mastery_threshold", self.threshold.value())
        settings.put("goal/bricks", self.goal.value())
        settings.put("goal/review_batch", self.review_batch.value())
        theme.set_name(self.theme.currentData())
