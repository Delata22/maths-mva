#!/usr/bin/env python3
"""Capture une page de cours en image, pour verifier le rendu sans ouvrir l'app.

  python tools/shot.py log-propositions            -> /tmp/log-propositions.png
  python tools/shot.py log-propositions --scroll 2 --theme dark
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-logging --no-sandbox --single-process")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mathsapp import content  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402
from mathsapp.ui.webview import WebView  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("course_id")
    parser.add_argument("--out", default=None)
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    parser.add_argument("--view", default="course", choices=["course", "quiz", "proofs"])
    parser.add_argument("--scroll", type=float, default=0.0,
                        help="nombre d'ecrans a faire defiler avant la capture")
    parser.add_argument("--anchor", default=None,
                        help="id d'un element vers lequel defiler (ex : fig-tables)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--wait", type=int, default=3500, help="ms d'attente apres chargement")
    args = parser.parse_args()

    syl = load()
    course = syl.get(args.course_id)
    if course is None or not content.has_course(args.course_id):
        print("Cours absent ou non genere : %s" % args.course_id)
        return 2

    app = QApplication(sys.argv)
    view = WebView(with_bridge=False)
    view.resize(args.width, args.height)
    view.show()

    out = pathlib.Path(args.out or ("/tmp/%s.png" % args.course_id))
    if args.view == "course":
        path = content.render_course_page(args.course_id, course.title, args.theme)
    else:
        import json
        from mathsapp import store
        from mathsapp.paths import ASSETS_DIR, library_dir
        data = content.read_exercises(args.course_id) or {}
        tpl = (ASSETS_DIR / ("%s.html" % args.view)).read_text(encoding="utf-8")
        page = (tpl.replace("__THEME__", args.theme)
                   .replace("__ASSETS__", content.assets_url())
                   .replace("__DATA__", json.dumps(data, ensure_ascii=False))
                   .replace("__STATUS__", json.dumps(store.proof_statuses(args.course_id))))
        d = library_dir() / "_views"
        d.mkdir(parents=True, exist_ok=True)
        path = d / ("shot_%s_%s.html" % (args.view, args.course_id))
        path.write_text(page, encoding="utf-8")

    def after_load(ok: bool) -> None:
        if not ok:
            print("chargement echoue")
            app.exit(1)
            return

        def shoot() -> None:
            view.grab().save(str(out))
            print("%s  (%d x %d)" % (out, args.width, args.height))
            app.quit()

        if args.anchor:
            view.run_js(
                "var e=document.getElementById(%r);"
                "if(e) window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 60);"
                % args.anchor)
        elif args.scroll:
            view.run_js("window.scrollTo(0, window.innerHeight * %f);" % args.scroll)
        QTimer.singleShot(args.wait, shoot)

    view.loadFinished.connect(after_load)
    view.load(QUrl.fromLocalFile(str(path)))
    QTimer.singleShot(45000, lambda: app.exit(3))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
