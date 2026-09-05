"""Emplacements de fichiers de l'application."""
from __future__ import annotations

import os
import pathlib

PKG_DIR = pathlib.Path(__file__).resolve().parent
ASSETS_DIR = PKG_DIR / "assets"
VENDOR_DIR = ASSETS_DIR / "vendor"
DATA_DIR = PKG_DIR / "data"
SYLLABUS_FILE = DATA_DIR / "syllabus.json"

PROJECT_ROOT = PKG_DIR.parent


def library_dir() -> pathlib.Path:
    """Dossier ou sont stockes les cours generes."""
    env = os.environ.get("MATHSAPP_LIBRARY")
    d = pathlib.Path(env).expanduser() if env else PROJECT_ROOT / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def course_dir(course_id: str, create: bool = False) -> pathlib.Path:
    """Dossier d'un cours. `create=True` uniquement avant une ecriture :
    une simple lecture ne doit pas semer des dossiers vides."""
    d = library_dir() / course_id
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def db_file() -> pathlib.Path:
    return library_dir() / "progress.db"


def logs_dir() -> pathlib.Path:
    d = library_dir() / "_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
