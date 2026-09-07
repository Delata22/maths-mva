#!/usr/bin/env python3
"""Rééquilibre les QCM déjà générés.

Deux défauts mesurables sur les premiers cours produits : la bonne réponse est
la plus longue une fois sur deux, et elle tombe presque toujours en A ou en B.
Les deux permettent de répondre sans connaître le cours.

  python tools/fix_qcm.py --dry-run     # mesurer sans rien changer
  python tools/fix_qcm.py               # corriger tous les cours
  python tools/fix_qcm.py al-espaces    # un cours précis
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import content, settings  # noqa: E402
from mathsapp.generation import pipeline  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402


def stats(qcm: list) -> dict:
    positions = collections.Counter()
    longest, ratios = 0, []
    for q in qcm:
        lengths = [len(pipeline._plain(c)) for c in q["choices"]]
        a = q["answer"]
        positions[a] += 1
        others = [l for i, l in enumerate(lengths) if i != a] or [1]
        ratios.append(lengths[a] / max(1, statistics.median(others)))
        if lengths[a] == max(lengths):
            longest += 1
    return {"n": len(qcm), "positions": positions, "longest": longest,
            "ratio": statistics.median(ratios) if ratios else 1.0}


def line(label: str, s: dict) -> str:
    pos = " ".join("%s:%d" % ("ABCD"[i], s["positions"].get(i, 0)) for i in range(4))
    return ("  %-24s %2d questions · bonne réponse la plus longue %2d fois (%2.0f %%) "
            "· rapport %.2f · positions %s"
            % (label, s["n"], s["longest"], 100 * s["longest"] / max(1, s["n"]),
               s["ratio"], pos))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--dry-run", action="store_true", help="mesurer sans corriger")
    args = parser.parse_args()

    syl = load()
    ids = args.ids or [c.id for c in syl.all() if content.has_exercises(c.id)]
    ids = [c for c in ids if content.has_exercises(c)]
    if not ids:
        print("Aucun QCM à traiter.")
        return 0

    model = str(settings.get("model/exercises"))
    before_all, after_all = [], []
    total_cost = 0.0

    for cid in ids:
        data = content.read_exercises(cid)
        qcm = data.get("qcm") or []
        if not qcm:
            continue
        before = stats(qcm)
        before_all.extend(qcm)
        print(line(cid, before))
        if args.dry_run:
            continue

        fixed, cost = pipeline.repair_qcm_balance(syl, cid, qcm, model)
        total_cost += cost
        moved = pipeline.rebalance_positions(qcm, seed=abs(hash(cid)) % 10000)
        data["qcm"] = qcm
        content.write_json(cid, content.EXOS, data)
        after = stats(qcm)
        after_all.extend(qcm)
        print(line("  -> corrigé", after) + "   (%d réécrites, %d déplacées)" % (fixed, moved))

    print()
    print("AVANT :" if args.dry_run else "BILAN AVANT :")
    print(line("ensemble", stats(before_all)))
    if not args.dry_run and after_all:
        print("APRÈS :")
        print(line("ensemble", stats(after_all)))
        print()
        print("Coût : %.2f $" % total_cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
