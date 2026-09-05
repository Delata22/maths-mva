"""Theme de l'application (QSS) et palette partagee avec les pages web."""
from __future__ import annotations

from PySide6.QtGui import QColor

from .. import settings

LIGHT = {
    "bg": "#ffffff", "bg2": "#f4f6fa", "bg3": "#eaedf4",
    "fg": "#1a1d24", "fg2": "#525b6b", "muted": "#818b9e",
    "line": "#dfe3ec", "line2": "#c9d0de",
    "accent": "#2f6df6", "accent_fg": "#ffffff", "accent_soft": "#e8efff",
    "ok": "#0f9d76", "ok_soft": "#e4f6f0",
    "warn": "#c2740a", "warn_soft": "#fdf2e0",
    "err": "#d92d20", "err_soft": "#fdecea",
    "locked": "#a8b0c0",
}

DARK = {
    "bg": "#12151c", "bg2": "#171b23", "bg3": "#1e232e",
    "fg": "#e6e9f0", "fg2": "#b3bbcb", "muted": "#7f889b",
    "line": "#262c39", "line2": "#333b4c",
    "accent": "#6ea0ff", "accent_fg": "#0d1220", "accent_soft": "#1a2740",
    "ok": "#3ddc97", "ok_soft": "#12251f",
    "warn": "#fbbf24", "warn_soft": "#2a2113",
    "err": "#f87171", "err_soft": "#2b1717",
    "locked": "#4c5468",
}


def name() -> str:
    v = settings.get("ui/theme")
    return "dark" if str(v) == "dark" else "light"


def set_name(value: str) -> None:
    settings.put("ui/theme", "dark" if value == "dark" else "light")


def palette() -> dict:
    return DARK if name() == "dark" else LIGHT


def c(key: str) -> QColor:
    return QColor(palette()[key])


QSS = """
* { outline: none; }

QWidget {
    background: %(bg)s;
    color: %(fg)s;
    font-family: "Inter", "Segoe UI", "Ubuntu", system-ui, sans-serif;
    font-size: 13px;
}

QMainWindow::separator { background: %(line)s; width: 1px; height: 1px; }

/* ------------------------------------------------------------- barre haute */
#TopBar {
    background: %(bg2)s;
    border-bottom: 1px solid %(line)s;
}
#TopBar QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 13px;
    color: %(fg2)s;
    font-weight: 500;
}
#TopBar QToolButton:hover { background: %(bg3)s; color: %(fg)s; }
#TopBar QToolButton:checked {
    background: %(accent_soft)s; color: %(accent)s; font-weight: 600;
}
#Brand {
    font-size: 14px; font-weight: 700; color: %(fg)s;
    padding: 0 14px 0 4px; letter-spacing: -.01em;
}

/* -------------------------------------------------------------- recherche */
QLineEdit {
    background: %(bg)s;
    border: 1px solid %(line2)s;
    border-radius: 7px;
    padding: 6px 11px;
    selection-background-color: %(accent)s;
    selection-color: %(accent_fg)s;
}
QLineEdit:focus { border-color: %(accent)s; }
QLineEdit::placeholder { color: %(muted)s; }

QComboBox {
    background: %(bg)s;
    border: 1px solid %(line2)s;
    border-radius: 7px;
    padding: 5px 10px;
    min-height: 20px;
}
QComboBox:hover { border-color: %(accent)s; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow {
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid %(muted)s; margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: %(bg)s;
    border: 1px solid %(line2)s;
    border-radius: 7px;
    selection-background-color: %(accent_soft)s;
    selection-color: %(accent)s;
    padding: 4px;
    outline: none;
}

QSpinBox {
    background: %(bg)s; border: 1px solid %(line2)s; border-radius: 7px; padding: 4px 8px;
}

/* --------------------------------------------------------------- boutons */
QPushButton {
    background: %(bg2)s;
    border: 1px solid %(line2)s;
    border-radius: 7px;
    padding: 7px 15px;
    color: %(fg)s;
    font-weight: 500;
}
QPushButton:hover { border-color: %(accent)s; color: %(accent)s; }
QPushButton:pressed { background: %(bg3)s; }
QPushButton:disabled { color: %(muted)s; border-color: %(line)s; background: %(bg2)s; }
QPushButton[primary="true"] {
    background: %(accent)s; border-color: %(accent)s; color: %(accent_fg)s; font-weight: 600;
}
QPushButton[primary="true"]:hover { background: %(accent)s; color: %(accent_fg)s; }
QPushButton[primary="true"]:disabled { background: %(line2)s; border-color: %(line2)s; color: %(muted)s; }
QPushButton[flat="true"] {
    background: transparent; border-color: transparent; color: %(fg2)s; padding: 5px 9px;
}
QPushButton[flat="true"]:hover { background: %(bg3)s; color: %(fg)s; }

/* ----------------------------------------------------------------- listes */
QTreeWidget, QTreeView, QListWidget, QTableWidget {
    background: %(bg)s;
    border: none;
    alternate-background-color: %(bg2)s;
    selection-background-color: %(accent_soft)s;
    selection-color: %(fg)s;
    outline: none;
}
QTreeWidget::item, QListWidget::item {
    padding: 5px 4px;
    border-bottom: 1px solid %(line)s;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background: %(accent_soft)s; color: %(fg)s;
}
QTreeWidget::item:hover, QListWidget::item:hover { background: %(bg2)s; }
QHeaderView::section {
    background: %(bg2)s;
    color: %(muted)s;
    border: none;
    border-bottom: 1px solid %(line)s;
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .05em;
}

/* --------------------------------------------------------------- onglets */
QTabWidget::pane { border: none; border-top: 1px solid %(line)s; }
QTabBar::tab {
    background: transparent;
    color: %(muted)s;
    padding: 9px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
    margin-right: 2px;
}
QTabBar::tab:hover { color: %(fg)s; }
QTabBar::tab:selected {
    color: %(accent)s; border-bottom-color: %(accent)s; font-weight: 600;
}

/* ----------------------------------------------------------------- docks */
QDockWidget {
    titlebar-close-icon: none; titlebar-normal-icon: none;
    color: %(fg2)s; font-weight: 600;
}
QDockWidget::title {
    background: %(bg2)s;
    border-bottom: 1px solid %(line)s;
    padding: 8px 12px;
    text-align: left;
}

/* ------------------------------------------------------------ progression */
QProgressBar {
    background: %(bg3)s;
    border: none;
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: %(fg2)s;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 0; }
QScrollBar::handle:vertical {
    background: %(line2)s; border-radius: 5px; min-height: 32px; margin: 2px;
}
QScrollBar::handle:vertical:hover { background: %(muted)s; }
QScrollBar:horizontal { background: transparent; height: 11px; }
QScrollBar::handle:horizontal {
    background: %(line2)s; border-radius: 5px; min-width: 32px; margin: 2px;
}
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QSplitter::handle { background: %(line)s; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }

QStatusBar {
    background: %(bg2)s; border-top: 1px solid %(line)s; color: %(muted)s;
}
QStatusBar::item { border: none; }

QToolTip {
    background: %(bg3)s; color: %(fg)s;
    border: 1px solid %(line2)s; border-radius: 6px; padding: 5px 8px;
}

QPlainTextEdit, QTextEdit {
    background: %(bg)s;
    border: 1px solid %(line2)s;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: %(accent)s;
    selection-color: %(accent_fg)s;
}
QPlainTextEdit:focus, QTextEdit:focus { border-color: %(accent)s; }

QRadioButton, QCheckBox { spacing: 9px; padding: 3px 0; }
QRadioButton::indicator, QCheckBox::indicator { width: 16px; height: 16px; }
QRadioButton::indicator {
    border: 1.5px solid %(line2)s; border-radius: 9px; background: %(bg)s;
}
QRadioButton::indicator:hover { border-color: %(accent)s; }
QRadioButton::indicator:checked {
    border: 5px solid %(accent)s; background: %(bg)s;
}
QCheckBox::indicator {
    border: 1.5px solid %(line2)s; border-radius: 4px; background: %(bg)s;
}
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

QGroupBox {
    border: 1px solid %(line)s; border-radius: 9px; margin-top: 16px; padding: 14px 12px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 5px;
    color: %(muted)s; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: .06em;
}

QMenu {
    background: %(bg)s; border: 1px solid %(line2)s; border-radius: 8px; padding: 5px;
}
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 5px; }
QMenu::item:selected { background: %(accent_soft)s; color: %(accent)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 5px 8px; }

QScrollArea { border: none; background: %(bg)s; }

#Card {
    background: %(bg2)s;
    border: 1px solid %(line)s;
    border-radius: 11px;
}
/* Les conteneurs d'une carte ne repeignent pas le fond, mais les boutons
   gardent le leur : sinon un bouton principal devient invisible. */
#Card QWidget, #Card QLabel { background: transparent; }
#Card QPushButton { background: %(bg)s; }
#Card QPushButton:hover { background: %(bg)s; }
#Card QPushButton[primary="true"] {
    background: %(accent)s; border-color: %(accent)s; color: %(accent_fg)s;
}
#Card QPushButton[primary="true"]:hover { background: %(accent)s; color: %(accent_fg)s; }
#Card QPushButton[flat="true"] { background: transparent; }
#Card QPushButton[flat="true"]:hover { background: %(bg3)s; }
#Card QProgressBar { background: %(bg3)s; }
#Notice {
    background: %(warn_soft)s;
    border-bottom: 1px solid %(warn)s;
}
#Notice QLabel { color: %(fg)s; background: transparent; }
#Notice QPushButton {
    background: transparent; border: 1px solid %(warn)s; color: %(warn)s;
    border-radius: 7px; padding: 5px 12px; font-weight: 600;
}
#Notice QPushButton:hover { background: %(warn)s; color: %(bg)s; }
#Notice QPushButton[flat="true"] {
    border-color: transparent; color: %(muted)s; font-weight: 500;
}
#Notice QPushButton[flat="true"]:hover { background: transparent; color: %(fg)s; }
#Muted { color: %(muted)s; }
#H1 { font-size: 21px; font-weight: 700; letter-spacing: -.015em; }
#H2 { font-size: 15px; font-weight: 650; }
#Chip {
    background: %(bg3)s; color: %(fg2)s;
    border: 1px solid %(line)s; border-radius: 999px; padding: 3px 10px; font-size: 11.5px;
}
"""


def stylesheet() -> str:
    return QSS % palette()
