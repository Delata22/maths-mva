#!/usr/bin/env python3
"""Capture les vues natives de l'application (bibliotheque, graphe, accueil)."""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-logging --no-sandbox")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mathsapp.ui import theme  # noqa: E402
from mathsapp.ui.main_window import (  # noqa: E402
    MainWindow, PAGE_GRAPH, PAGE_HOME, PAGE_LIBRARY,
)

PAGES = {"accueil": PAGE_HOME, "bibliotheque": PAGE_LIBRARY, "graphe": PAGE_GRAPH}


def main() -> int:
    page = sys.argv[1] if len(sys.argv) > 1 else "accueil"
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/app-%s.png" % page
    want_theme = sys.argv[3] if len(sys.argv) > 3 else theme.name()
    size = sys.argv[4] if len(sys.argv) > 4 else "1600x980"
    width, height = (int(v) for v in size.split("x"))
    scroll = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])
    theme.set_name(want_theme)
    app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(width, height)
    window.show()

    def shoot() -> None:
        window.go(PAGES[page])
        if scroll and page == "accueil":
            bar = window.dashboard.area.verticalScrollBar()
            bar.setValue(int(bar.maximum() * scroll))
        QTimer.singleShot(900, lambda: (window.grab().save(out), print(out), app.quit()))

    QTimer.singleShot(1200, shoot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
