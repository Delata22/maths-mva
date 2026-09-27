"""Texte d'un PDF, pour les moteurs qui ne savent pas lire un PDF.

`claude` lit le PDF lui-même avec son outil Read, formules comprises. Les autres
moteurs reçoivent le texte extrait ici, page par page si besoin. L'extraction
passe par `pdftotext` (paquet poppler-utils), présent sur la plupart des Linux.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Optional, Tuple

MISSING = ("L'outil `pdftotext` est introuvable : il sert à lire les PDF quand le "
           "moteur ne sait pas le faire lui-même. Installez-le "
           "(Debian/Ubuntu : sudo apt install poppler-utils) ou passez au moteur "
           "claude dans Préférences.")


def available() -> bool:
    return shutil.which("pdftotext") is not None


def page_range(pages: str) -> Tuple[Optional[int], Optional[int]]:
    """« 5-18 » ou « 42 » ou « » → (premiere, derniere) pages, None si libre."""
    found = [int(n) for n in re.findall(r"\d+", str(pages or ""))]
    if not found:
        return None, None
    if len(found) == 1:
        return found[0], found[0]
    return min(found), max(found)


def extract(path, pages: str = "", limit: int = 120000) -> str:
    """Texte du PDF (ou des pages demandées), mise en page conservée."""
    if not available():
        raise RuntimeError(MISSING)
    first, last = page_range(pages)
    cmd = ["pdftotext", "-layout"]
    if first:
        cmd += ["-f", str(first)]
    if last:
        cmd += ["-l", str(last)]
    cmd += [str(path), "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Lecture du PDF impossible : %s" % exc) from exc
    if out.returncode != 0:
        raise RuntimeError("Lecture du PDF impossible : %s" % (out.stderr or "")[:300])
    text = re.sub(r"\n{3,}", "\n\n", out.stdout).strip()
    if len(text) > limit:
        text = text[:limit] + "\n\n[… document tronqué ici …]"
    return text
