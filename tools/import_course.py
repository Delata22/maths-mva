#!/usr/bin/env python3
"""Importer un cours magistral en PDF.

  python tools/import_course.py run ~/cours.pdf     lire, inscrire, rédiger, corriger
  python tools/import_course.py resume <id>        reprendre là où ça s'est arrêté
  python tools/import_course.py list               cours importés et avancement
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import content, course_import, td as td_mod  # noqa: E402
from mathsapp.generation import pipeline  # noqa: E402


def show(label: str, frac: float) -> None:
    width = 30
    filled = int(width * max(0.0, min(1.0, frac)))
    sys.stdout.write("\r  [%s%s] %3d%%  %-80s"
                     % ("#" * filled, "." * (width - filled), int(frac * 100), label[:80]))
    sys.stdout.flush()


def describe(doc: str) -> str:
    cid = course_import.course_of(doc)
    if course_import.read_import(doc) is None:
        return "document pas encore lu"
    if not cid:
        return "lu, pas encore inscrit"
    st = content.generation_state(cid)
    ex = td_mod.state(doc)
    return "%s · sections %d/%d · exercices corrigés %d/%d" % (
        cid, st["sections_done"], st["sections_total"], ex["corrected"], ex["total"])


def run(doc: str) -> int:
    started = time.time()
    print("Document : %s" % doc)
    try:
        result = pipeline.run_course_import(doc, show)
    except KeyboardInterrupt:
        print("\n\nInterrompu. Relancez « resume %s » pour reprendre." % doc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("\n\nÉCHEC : %s\nRelancez « resume %s » pour reprendre." % (exc, doc))
        return 1
    print("\r  Cours « %s » (%s) : %d sections, %d exercices corrigés, %.2f $, %.0f min%s"
          % (result["title"], result["course_id"], result["sections"], result["exercises"],
             result["cost"], (time.time() - started) / 60, " " * 20))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("pdf")
    p_res = sub.add_parser("resume")
    p_res.add_argument("doc")
    sub.add_parser("list")
    args = parser.parse_args()
    if args.cmd == "list":
        for doc in course_import.list_ids():
            print("  %-28s %s" % (doc, describe(doc)))
        return 0
    if args.cmd == "run":
        return run(course_import.import_pdf(args.pdf))
    return run(args.doc)


if __name__ == "__main__":
    sys.exit(main())
