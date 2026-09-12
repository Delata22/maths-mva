"""Petits composants d'affichage propres au tableau de bord."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme


class Ring(QWidget):
    """Anneau de progression, avec une valeur au centre."""

    def __init__(self, size: int = 92, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._fraction = 0.0
        self._label = ""
        self._sub = ""
        self._colour = "accent"

    def set_value(self, fraction: float, label: str, sub: str = "",
                  colour: str = "accent") -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._label = label
        self._sub = sub
        self._colour = colour
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        thickness = max(7, self.width() // 11)
        rect = QRectF(thickness / 2 + 1, thickness / 2 + 1,
                      self.width() - thickness - 2, self.height() - thickness - 2)

        pen = QPen(QColor(pal["bg3"]), thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._fraction > 0:
            pen.setColor(QColor(pal[self._colour]))
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._fraction))

        shift = self.height() // 9 if self._sub else 0
        painter.setPen(QPen(QColor(pal["fg"])))
        font = QFont()
        font.setPointSizeF(self.width() / 5.6)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, -shift, 0, -shift),
                         int(Qt.AlignmentFlag.AlignCenter), self._label)
        if self._sub:
            painter.setPen(QPen(QColor(pal["muted"])))
            small = QFont()
            small.setPointSizeF(self.width() / 12.5)
            painter.setFont(small)
            painter.drawText(self.rect().adjusted(0, shift * 2, 0, shift * 2),
                             int(Qt.AlignmentFlag.AlignCenter), self._sub)
        painter.end()


class Heatmap(QWidget):
    """Calendrier des jours travaillés, sur quelques semaines."""

    def __init__(self, weeks: int = 14, parent=None):
        super().__init__(parent)
        self.weeks = weeks
        self._days: Dict[str, dict] = {}
        self.setMinimumHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_days(self, days: Dict[str, dict]) -> None:
        self._days = days
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        pal = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        cell, gap = 11, 3
        today = dt.date.today()
        # on commence au lundi de la semaine la plus ancienne affichee
        start = today - dt.timedelta(days=today.weekday() + 7 * (self.weeks - 1))
        for column in range(self.weeks):
            for row in range(7):
                day = start + dt.timedelta(days=column * 7 + row)
                if day > today:
                    continue
                info = self._days.get(day.isoformat())
                bricks = (info or {}).get("bricks", 0)
                frozen = (info or {}).get("frozen", 0)
                if bricks >= 3:
                    colour = QColor(pal["ok"])
                elif bricks == 2:
                    colour = QColor(pal["ok"]); colour.setAlpha(200)
                elif bricks == 1:
                    colour = QColor(pal["ok"]); colour.setAlpha(130)
                elif frozen:
                    colour = QColor(pal["accent"]); colour.setAlpha(110)
                else:
                    colour = QColor(pal["bg3"])
                painter.setBrush(colour)
                painter.drawRoundedRect(
                    QRectF(column * (cell + gap), row * (cell + gap), cell, cell), 3, 3)
        painter.end()
