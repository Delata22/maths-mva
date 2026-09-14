#!/usr/bin/env python3
"""Sujets de TD en ligne de commande.

  python tools/td.py run ~/TD1.pdf          importer, lire et corriger d'un coup
  python tools/td.py add ~/TD1.pdf          importer seulement
  python tools/td.py correct td-mva-2026    lire (si besoin) puis corriger
  python tools/td.py list                   TD importés et leur avancement
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import settings, td as td_mod  # noqa: E402
from mathsapp.generation import pipeline  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402


def show(label: str, frac: float) -> None:
    width = 30
    filled = int(width * frac)
    sys.stdout.write("\r  [%s%s] %3d%%  %-70s"
                     % ("#" * filled, "." * (width - filled), int(frac * 100), label[:70]))
    sys.stdout.flush()


def describe(td_id: str) -> str:
    st = td_mod.state(td_id)
    if not st["structured"]:
        return "sujet pas encore lu"
    return "%d/%d exercices corrigés" % (st["corrected"], st["total"])


def correct(td_id: str) -> int:
    syl = load()
    started = time.time()
    print("TD : %s  (modèle de correction : %s)" % (td_id, settings.get("model/course")))
    try:
        result = pipeline.run_td(td_id, show, syl=syl)
    except KeyboardInterrupt:
        print("\n\nInterrompu. Les corrections écrites sont conservées : relancez pour reprendre.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print("\n\nÉCHEC : %s\nRelancez la même commande pour reprendre." % exc)
        return 1
    print("\r  %d exercices, %d corrigés à l'instant, %.2f $, %.0f min%s\n"
          % (result["exercises"], result["corrected"], result["cost"],
             (time.time() - started) / 60, " " * 30))
    print("Titre : %s" % td_mod.title(td_id))
    print("État  : %s" % describe(td_id))
    return 0 if result["complete"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="importer un sujet PDF")
    p_add.add_argument("pdf")
    p_run = sub.add_parser("run", help="importer, lire et corriger")
    p_run.add_argument("pdf")
    p_cor = sub.add_parser("correct", help="lire si besoin, puis corriger")
    p_cor.add_argument("td_id")
    sub.add_parser("list", help="lister les TD importés")
    args = parser.parse_args()

    if args.cmd == "list":
        ids = td_mod.list_ids()
        if not ids:
            print("Aucun TD importé.")
        for td_id in ids:
            print("  %-28s %-40s %s" % (td_id, td_mod.title(td_id)[:40], describe(td_id)))
        return 0
    if args.cmd == "add":
        td_id = td_mod.import_pdf(args.pdf)
        print("Importé : %s" % td_id)
        return 0
    if args.cmd == "run":
        td_id = td_mod.import_pdf(args.pdf)
        print("Importé : %s" % td_id)
        return correct(td_id)
    return correct(args.td_id)


if __name__ == "__main__":
    sys.exit(main())
