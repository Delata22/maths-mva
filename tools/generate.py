#!/usr/bin/env python3
"""Generation de cours en ligne de commande, sans interface.

  python tools/generate.py al-svd cd-hessienne
  python tools/generate.py --track mva-optimisation
  python tools/generate.py --path opt-dualite-kkt      # le cours et ses prerequis
  python tools/generate.py --list
"""
from __future__ import annotations

import argparse
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import content, settings  # noqa: E402
from mathsapp.generation import pipeline  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402


def show(label: str, frac: float) -> None:
    width = 34
    filled = int(width * frac)
    sys.stdout.write("\r  [%s%s] %3d%%  %-46s"
                     % ("#" * filled, "." * (width - filled), int(frac * 100), label[:46]))
    sys.stdout.flush()


def main() -> int:
    syl = load()
    parser = argparse.ArgumentParser(description="Generer des cours sans lancer l'application.")
    parser.add_argument("ids", nargs="*", help="identifiants de cours")
    parser.add_argument("--track", help="generer tout un parcours MVA")
    parser.add_argument("--path", help="generer un cours et tous ses prerequis")
    parser.add_argument("--list", action="store_true", help="lister les cours")
    parser.add_argument("--resume", action="store_true",
                        help="reprendre toutes les generations interrompues")
    parser.add_argument("--force", action="store_true", help="regenerer meme si deja present")
    parser.add_argument("--model",
                        help="modele pour les cours, pour cette execution seulement "
                             "(par defaut : la preference enregistree dans l'app)")
    args = parser.parse_args()

    if args.list:
        for course in syl.all():
            state = content.generation_state(course.id)
            mark = ("x" if state["complete"]
                    else ("~" if state["partial"] else " "))
            extra = ("  (%d/%d sections)" % (state["sections_done"], state["sections_total"])
                     if state["partial"] else "")
            print("[%s] %-30s niv.%d  %s%s"
                  % (mark, course.id, course.level, course.title, extra))
        print("\n  x terminé   ~ interrompu   (vide) pas commencé")
        return 0

    ids = list(args.ids)
    if args.resume:
        interrupted = [c.id for c in syl.all() if content.generation_state(c.id)["partial"]]
        if not interrupted:
            print("Aucune génération interrompue.")
            return 0
        print("Reprise de %d génération(s) interrompue(s).\n" % len(interrupted))
        ids += interrupted
    if args.track:
        if args.track not in syl.tracks:
            print("Parcours inconnu. Disponibles : %s" % ", ".join(syl.tracks))
            return 2
        ids += syl.track_path(args.track)
    if args.path:
        ids += syl.path_to(args.path)
    if not ids:
        parser.print_help()
        return 2

    seen, todo = set(), []
    for cid in ids:
        if cid in seen:
            continue
        seen.add(cid)
        if cid not in syl.courses:
            print("Cours inconnu : %s" % cid)
            return 2
        if content.is_complete(cid) and not args.force:
            continue
        todo.append(cid)

    if not todo:
        print("Rien a generer (utilisez --force pour regenerer).")
        return 0

    if args.force:
        for cid in todo:
            content.delete_course(cid)
    resumed = sum(1 for cid in todo if content.generation_state(cid)["partial"])
    print("%d cours à générer%s, modèle %s\n"
          % (len(todo), " (dont %d repris)" % resumed if resumed else "",
             args.model or settings.get("model/course")))
    total_cost, started = 0.0, time.time()
    for i, cid in enumerate(todo, 1):
        print("(%d/%d) %s" % (i, len(todo), syl.title(cid)))
        try:
            meta = pipeline.generate_course(cid, show, syl=syl, model_course=args.model)
        except KeyboardInterrupt:
            print("\n\n  Interrompu. Les sections écrites sont conservées : "
                  "relancez avec --resume pour reprendre.")
            return 1
        except Exception as exc:  # noqa: BLE001
            from mathsapp.generation.claude_cli import connectivity_hint
            hint = connectivity_hint(str(exc))
            print("\n  ECHEC : %s" % exc)
            if hint:
                print("  %s" % hint)
            print("  Relancez avec : python tools/generate.py --resume\n")
            continue
        total_cost += meta["cost_usd"]
        print("\r  termine en %.0fs, %.2f $, %d sections%s\n"
              % (meta["duration_s"], meta["cost_usd"], len(meta["sections"]), " " * 30))
    print("Total : %.2f $ en %.0f min" % (total_cost, (time.time() - started) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
