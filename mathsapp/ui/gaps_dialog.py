"""Validation des fiches de lacunes proposées après une séance.

Chaque fiche se garde ou se jette d'un clic ; l'intitulé de la notion se
corrige sur place. Reformuler soi-même aide déjà à retenir.
"""
from __future__ import annotations

import re
from typing import Dict, List

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFrame, QLabel,
                               QLineEdit, QScrollArea, QVBoxLayout, QWidget)

from ..syllabus import Syllabus


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


class GapsDialog(QDialog):
    def __init__(self, cards: List[dict], syl: Syllabus, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fiches de lacunes")
        self.resize(760, 620)
        self._rows: Dict[str, tuple] = {}

        root = QVBoxLayout(self)
        intro = QLabel(
            "Les notions de base que vous avez redemandées pendant la séance. "
            "Gardez celles que vous ne voulez plus oublier ; corrigez l'intitulé "
            "si besoin. Elles reviendront dans les révisions, de plus en plus espacées.")
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        root.addWidget(intro)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(10)
        for card in cards:
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            fl = QVBoxLayout(frame)
            keep = QCheckBox("Garder · %s" % syl.title(card["course_id"]))
            keep.setChecked(True)
            fl.addWidget(keep)
            notion = QLineEdit(card.get("notion", ""))
            notion.setPlaceholderText("Intitulé de la notion")
            fl.addWidget(notion)
            answer = card["choices"][card["answer"]] if card.get("choices") else ""
            text = QLabel("<b>Q.</b> %s<br><b>R.</b> %s<br><span style='opacity:.75'>%s</span>"
                          % (_plain(card.get("question")), _plain(answer),
                             _plain(card.get("explanation"))))
            text.setWordWrap(True)
            fl.addWidget(text)
            lay.addWidget(frame)
            self._rows[card["id"]] = (keep, notion, card.get("notion", ""))
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._quiz = QCheckBox("Faire le petit quiz tout de suite")
        self._quiz.setChecked(True)
        root.addWidget(self._quiz)
        buttons = QDialogButtonBox()
        buttons.addButton("Valider", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Plus tard", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def kept(self) -> List[str]:
        return [cid for cid, (box, _e, _o) in self._rows.items() if box.isChecked()]

    def dropped(self) -> List[str]:
        return [cid for cid, (box, _e, _o) in self._rows.items() if not box.isChecked()]

    def edits(self) -> Dict[str, str]:
        return {cid: edit.text() for cid, (_b, edit, orig) in self._rows.items()
                if edit.text().strip() and edit.text() != orig}

    def quiz_now(self) -> bool:
        return self._quiz.isChecked()
