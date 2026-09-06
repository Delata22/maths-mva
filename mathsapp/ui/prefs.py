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
        settings.put("claude/binary", self.binary.text().strip() or "claude")
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
        settings.put("ui/mastery_threshold", self.threshold.value())
        theme.set_name(self.theme.currentData())
