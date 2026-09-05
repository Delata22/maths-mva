"""Point d'entree : python -m mathsapp"""
from __future__ import annotations

import os
import sys

# QtWebEngine doit etre initialise avant la creation de QApplication.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-logging")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .ui import theme  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Maths MVA")
    app.setOrganizationName("maths-mva")
    app.setDesktopFileName("maths-mva")
    from .paths import ASSETS_DIR
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.svg")))

    font = QFont()
    font.setPointSizeF(10.0)
    app.setFont(font)
    app.setStyleSheet(theme.stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
