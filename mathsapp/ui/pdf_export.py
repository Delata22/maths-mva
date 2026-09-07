"""Export d'une fiche de révision en PDF, via le moteur de rendu embarqué."""
from __future__ import annotations

import pathlib
from typing import Callable, Optional

from PySide6.QtCore import QMarginsF, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QPageLayout, QPageSize

from .. import content
from .webview import WebView


class PdfExporter(QObject):
    """Charge la fiche dans une vue hors écran, puis l'imprime en PDF.

    La vue doit rester vivante jusqu'à la fin de l'impression : on garde donc
    une référence sur l'exporteur tant que le signal `finished` n'a pas été
    émis.
    """

    finished = Signal(bool, str)   # succès, chemin ou message d'erreur

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view: Optional[WebView] = None
        self._out = ""

    def export(self, course_id: str, title: str, out_path: pathlib.Path,
               settle_ms: int = 700) -> None:
        self._out = str(out_path)
        try:
            page_path = content.render_sheet_page(course_id, title, "light", for_print=True)
        except OSError as exc:
            self.finished.emit(False, str(exc))
            return

        self.view = WebView()
        self.view.resize(820, 1160)          # proportions A4, pour les figures
        self.view.page().pdfPrintingFinished.connect(self._on_printed)
        self.view.loadFinished.connect(
            lambda ok: QTimer.singleShot(settle_ms, lambda: self._print(ok)))
        self.view.load(QUrl.fromLocalFile(str(page_path)))

    def _print(self, loaded: bool) -> None:
        if not loaded or self.view is None:
            self.finished.emit(False, "La fiche n'a pas pu être chargée.")
            return
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),           # les marges sont dans @page
            QPageLayout.Unit.Millimeter,
        )
        self.view.page().printToPdf(self._out, layout)

    def _on_printed(self, path: str, success: bool) -> None:
        if self.view is not None:
            self.view.deleteLater()
            self.view = None
        self.finished.emit(bool(success),
                           path if success else "L'impression a échoué.")
