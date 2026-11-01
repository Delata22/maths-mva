#!/usr/bin/env python3
"""Gérer le cursus depuis un terminal : packs, profil, nouveau cursus.

  python tools/curriculum.py list
  python tools/curriculum.py enable physique-quantique
  python tools/curriculum.py disable ml-mva
  python tools/curriculum.py profile --title "Physique" --start "fin de lycée"
  python tools/curriculum.py new "Physique quantique" \\
      --goals "comprendre la QM jusqu'à l'intrication" --size 40 [--save]
  python tools/curriculum.py export physique-quantique ~/physique.json
  python tools/curriculum.py import ~/physique.json

`new` sans --save écrit la proposition dans un fichier JSON à relire, qu'on
enregistre ensuite avec `import`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import content, curriculum, curriculum_gen  # noqa: E402
from mathsapp.syllabus import reload as reload_syllabus  # noqa: E402


def cmd_list(_args) -> None:
    active = set(curriculum.active_ids())
    for pid, pack in curriculum.available().items():
        ids = [c["id"] for c in pack["courses"]]
        done = sum(1 for cid in ids if content.is_complete(cid))
        print("%s %-22s %3d cours (%d rédigés)  %s%s"
              % ("[x]" if pid in active else "[ ]", pid, len(ids), done, pack["title"],
                 "" if pack["builtin"] else "  — perso"))
    prof = curriculum.profile()
    print("\nprofil : %s — départ : %s" % (prof["title"], prof["start_level"]))


def cmd_enable(args) -> None:
    unknown = [p for p in args.packs if p not in curriculum.available()]
    if unknown:
        sys.exit("pack inconnu : %s" % ", ".join(unknown))
    print("actifs :", ", ".join(curriculum.set_active(curriculum.active_ids() + args.packs)))


def cmd_disable(args) -> None:
    drop = set(args.packs)
    for p in args.packs:
        drop |= set(curriculum.dependents_of(p))
    drop.discard(curriculum.BASE_PACK)
    print("actifs :", ", ".join(curriculum.set_active(
        [p for p in curriculum.active_ids() if p not in drop])))


def cmd_profile(args) -> None:
    fields = {k: v for k, v in (("title", args.title), ("start_level", args.start),
                                ("about", args.about)) if v is not None}
    if fields:
        curriculum.set_profile(**fields)
    print(json.dumps(curriculum.profile(), ensure_ascii=False, indent=1))


def cmd_new(args) -> None:
    from mathsapp.generation import pipeline
    brief = {"subject": args.subject, "goals": args.goals or "",
             "start_level": args.start or curriculum.profile()["start_level"],
             "target_level": args.target or "", "notes": args.notes or ""}
    syl = reload_syllabus()

    def progress(label: str, frac: float) -> None:
        print("\r%3d %%  %-70s" % (int(frac * 100), label[:70]), end="", flush=True)

    pack, notes, cost = pipeline.design_curriculum(brief, args.size, model=args.model,
                                                   on_progress=progress, syl=syl)
    print()
    s = curriculum_gen.summary(pack)
    print("« %s » : %d domaines, %d cours, %d parcours, %.2f $"
          % (pack["title"], s["domains"], s["courses"], s["tracks"], cost))
    for d in pack["domains"]:
        courses = [c for c in pack["courses"] if c["domain"] == d["id"]]
        print("\n  %s (%d)" % (d["name"], len(courses)))
        for c in courses:
            print("    niv.%d  %-34s %s" % (c["level"], c["id"], c["title"]))
    for n in notes:
        print("  corrigé :", n)
    errors = curriculum_gen.check(pack, curriculum.merged_base())
    if errors:
        sys.exit("\n".join(errors))
    if args.save:
        pid = curriculum.save_pack(pack)
        curriculum.set_active(curriculum.active_ids() + [pid])
        print("\nenregistré et activé :", pid)
    else:
        out = pathlib.Path(args.out or "%s.json" % pack["id"])
        out.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nproposition écrite dans %s ; pour l'enregistrer :\n"
              "  python tools/curriculum.py import %s" % (out, out))


def cmd_export(args) -> None:
    if args.pack not in curriculum.available():
        sys.exit("pack inconnu : %s" % args.pack)
    curriculum.export_pack(args.pack, args.path)
    print("exporté :", args.path)


def cmd_import(args) -> None:
    pid = curriculum.import_pack(args.path)
    curriculum.set_active(curriculum.active_ids() + [pid])
    print("importé et activé :", pid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("enable")
    p.add_argument("packs", nargs="+")
    p.set_defaults(fn=cmd_enable)
    p = sub.add_parser("disable")
    p.add_argument("packs", nargs="+")
    p.set_defaults(fn=cmd_disable)
    p = sub.add_parser("profile")
    p.add_argument("--title")
    p.add_argument("--start", help="niveau de départ")
    p.add_argument("--about")
    p.set_defaults(fn=cmd_profile)
    p = sub.add_parser("new", help="concevoir un nouveau cursus")
    p.add_argument("subject")
    p.add_argument("--goals")
    p.add_argument("--start", help="niveau de départ (défaut : celui du profil)")
    p.add_argument("--target", help="niveau visé, en clair")
    p.add_argument("--notes")
    p.add_argument("--size", type=int, default=40, help="nombre de cours visé")
    p.add_argument("--model", help="modèle (défaut : celui des cours)")
    p.add_argument("--save", action="store_true", help="enregistrer et activer directement")
    p.add_argument("--out", help="fichier de la proposition (sans --save)")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("export")
    p.add_argument("pack")
    p.add_argument("path")
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("import")
    p.add_argument("path")
    p.set_defaults(fn=cmd_import)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
