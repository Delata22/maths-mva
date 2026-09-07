#!/usr/bin/env python3
"""Exporte des fiches de révision en PDF, sans ouvrir l'application.

  python tools/sheet_pdf.py log-propositions
  python tools/sheet_pdf.py --all --out ~/fiches
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-logging --no-sandbox")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mathsapp import content  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402
from mathsapp.ui.pdf_export import PdfExporter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--all", action="store_true", help="toutes les fiches existantes")
    parser.add_argument("--out", default=".", help="dossier de destination")
    args = parser.parse_args()

    syl = load()
    ids = list(args.ids)
    if args.all:
        ids = [c.id for c in syl.all() if content.has_sheet(c.id)]
    if not ids:
        parser.print_help()
        return 2

    out_dir = pathlib.Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication([])
    failures = 0

    for cid in ids:
        course = syl.get(cid)
        if course is None or not content.has_sheet(cid):
            print("  fiche absente : %s" % cid)
            failures += 1
            continue
        target = out_dir / ("%s.pdf" % cid)
        loop = QEventLoop()
        result = {}
        exporter = PdfExporter()
        exporter.finished.connect(lambda ok, msg: (result.update(ok=ok, msg=msg), loop.quit()))
        exporter.export(cid, course.title, target)
        QTimer.singleShot(60000, loop.quit)
        loop.exec()
        if result.get("ok"):
            size = target.stat().st_size // 1024
            print("  %-28s -> %s  (%d ko)" % (cid, target, size))
        else:
            print("  %-28s ECHEC : %s" % (cid, result.get("msg", "délai dépassé")))
            failures += 1
        # la vue est detruite par deleteLater : il faut laisser tourner la
        # boucle, sinon le moteur de rendu est libere avec des pages vivantes
        exporter.deleteLater()
        app.processEvents()
        QTimer.singleShot(0, loop.quit)
        loop.exec()

    app.processEvents()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
