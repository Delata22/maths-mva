#!/usr/bin/env python3
"""Est-ce que ça génère, ou est-ce que c'est planté ?

  python tools/status.py            # état à l'instant t
  python tools/status.py --watch    # rafraîchi toutes les 5 s

Marche que la génération vienne de l'application ou de la ligne de commande :
on regarde les appels `claude` en cours et les fichiers réellement écrits.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mathsapp import content  # noqa: E402
from mathsapp.paths import library_dir  # noqa: E402
from mathsapp.syllabus import load  # noqa: E402

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, ORANGE, RED, BLUE = "\033[32m", "\033[33m", "\033[31m", "\033[34m"

COURSE_RE = re.compile(r"COURS A ECRIRE : (.+?) Domaine :")
TASK_RE = re.compile(r"TACHE : rediger la section (\d+)/(\d+)")
MODEL_RE = re.compile(r"--model (\S+)")


def age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "%d s" % seconds
    if seconds < 3600:
        return "%d min %02d" % (seconds // 60, seconds % 60)
    return "%d h %02d" % (seconds // 3600, (seconds % 3600) // 60)


def running_calls() -> list:
    """Appels `claude` en cours, avec leur âge et ce sur quoi ils portent."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    calls = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        pid, elapsed, args = parts[0], int(parts[1]), parts[2]
        # On exige que le programme lance soit bien `claude` : sans cela, toute
        # commande citant ces motifs (un editeur, un grep) serait comptee.
        program = args.split(None, 1)[0]
        if not (program == "claude" or program.endswith("/claude")):
            continue
        if " -p " not in args and not args.endswith(" -p"):
            continue
        course = COURSE_RE.search(args)
        task = TASK_RE.search(args)
        model = MODEL_RE.search(args)
        if "exercises_prompt" in args or "QCM" in args:
            what = "exercices"
        elif task:
            what = "section %s/%s" % (task.group(1), task.group(2))
        elif "plan detaille" in args or "concevoir le plan" in args:
            what = "plan"
        elif "EXTENSION DE SYLLABUS" in args:
            what = "syllabus"
        else:
            what = "génération"
        calls.append({
            "pid": pid, "elapsed": elapsed,
            "course": course.group(1).strip() if course else "?",
            "what": what, "model": model.group(1) if model else "?",
        })
    return calls


def last_write() -> tuple:
    """Fichier de contenu écrit le plus récemment, et son âge."""
    newest, when = None, 0.0
    for path in library_dir().rglob("*"):
        if not path.is_file() or path.suffix not in (".html", ".json"):
            continue
        if path.name == "_render.html" or "_views" in path.parts:
            continue
        mtime = path.stat().st_mtime
        if mtime > when:
            newest, when = path, mtime
    return newest, when


def report(colour: bool = True) -> int:
    def c(code: str, text: str) -> str:
        return "%s%s%s" % (code, text, RESET) if colour else text

    syl = load()
    calls = running_calls()
    newest, when = last_write()
    silence = time.time() - when if when else None

    print(c(BOLD, "Générations en cours"))
    if not calls:
        print("  aucun appel au modèle en cours")
    for call in calls:
        marker, colour_code = ("●", GREEN) if call["elapsed"] < 420 else ("▲", ORANGE)
        print("  %s %-34s %-14s %-7s depuis %s"
              % (c(colour_code, marker), call["course"][:34], call["what"],
                 call["model"], age(call["elapsed"])))

    print()
    print(c(BOLD, "Dernière écriture sur le disque"))
    if newest is None:
        print("  rien dans library/")
    else:
        rel = newest.relative_to(library_dir())
        state = GREEN if silence < 480 else (ORANGE if silence < 900 else RED)
        print("  %s  il y a %s   %s"
              % (c(state, "●"), age(silence), c(DIM, str(rel))))

    incomplete = []
    for course in syl.all():
        st = content.generation_state(course.id)
        if st["partial"]:
            incomplete.append((course, st))
    if incomplete:
        print()
        print(c(BOLD, "Cours incomplets"))
        for course, st in incomplete:
            print("  %-34s %d/%d sections%s"
                  % (course.title[:34], st["sections_done"], st["sections_total"],
                     "" if st["has_exercises"] else ", exercices manquants"))

    print()
    if calls and silence is not None and silence < 480:
        verdict = c(GREEN, "Ça avance.") + " Un appel est en cours et le disque bouge."
    elif calls and (silence is None or silence >= 480):
        verdict = (c(ORANGE, "Un appel tourne mais rien n'a été écrit depuis %s.") % age(silence)
                   + " Une section longue peut prendre 8 min ; au-delà de 15 min, "
                     "l'appel sera interrompu et relancé automatiquement.")
    elif not calls and incomplete:
        verdict = (c(RED, "Rien ne tourne, et il reste des cours incomplets.")
                   + "\n  Reprenez avec : python tools/generate.py --resume")
    elif not calls:
        verdict = c(GREEN, "Rien en cours, rien d'inachevé.")
    else:
        verdict = "État indéterminé."
    print(c(BOLD, "Verdict : ") + verdict)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true", help="rafraîchir toutes les 5 s")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()
    if not args.watch:
        return report(not args.no_color)
    try:
        while True:
            print("\033[2J\033[H", end="")
            print(time.strftime("%H:%M:%S"))
            print()
            report(not args.no_color)
            time.sleep(5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
