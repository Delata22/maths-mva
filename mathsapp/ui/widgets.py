"""Petits composants d'affichage propres au tableau de bord."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget

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


class FlowLayout(QLayout):
    """Rangée qui passe à la ligne quand la place manque (puces de cours).

    Une QHBoxLayout impose la somme des largeurs de ses éléments : quelques
    prérequis aux titres longs suffisaient à rendre la fenêtre plus large que
    l'écran dès qu'un panneau latéral s'ouvrait.
    """

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def addStretch(self, _stretch: int = 0) -> None:  # noqa: N802
        """Sans objet dans une rangée qui passe à la ligne."""

    def setSpacing(self, spacing: int) -> None:  # noqa: N802
        self._spacing = spacing

    def spacing(self) -> int:
        return self._spacing

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry_run=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect, dry_run: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x = area.x()
                y += line + self._spacing
                line = 0
            if not dry_run:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()
