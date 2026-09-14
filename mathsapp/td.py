"""Sujets de TD importés et leurs corrections.

Un TD vit dans library/_td/<identifiant>/ :

    source.pdf         le sujet tel qu'importé
    td.json            sa structure : titre, exercices, énoncés en LaTeX,
                       cours du syllabus rattachés à chaque exercice
    corrections/NN.html
                       la correction de chaque exercice, en cache : une
                       correction interrompue reprend là où elle s'était arrêtée
    meta.json          coûts, durées, modèles
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import time
import unicodedata
from typing import List, Optional

from .paths import library_dir

SOURCE = "source.pdf"
STRUCTURE = "td.json"
META = "meta.json"
CORRECTIONS = "corrections"


def root() -> pathlib.Path:
    d = library_dir() / "_td"
    d.mkdir(parents=True, exist_ok=True)
    return d


def td_dir(td_id: str) -> pathlib.Path:
    d = root() / td_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", text)
                    if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()
    return re.sub(r"-{2,}", "-", slug)[:48].strip("-") or "td"


# ------------------------------------------------------------------ import
def import_pdf(path: str, name: Optional[str] = None) -> str:
    """Copie un sujet dans la bibliothèque et retourne son identifiant."""
    src = pathlib.Path(path).expanduser()
    if not src.exists() or src.suffix.lower() != ".pdf":
        raise ValueError("Un sujet de TD doit être un fichier PDF existant : %s" % src)
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:8]
    # le meme fichier importe deux fois retombe sur le meme TD
    for existing in list_ids():
        meta = read_meta(existing)
        if meta.get("sha1") == digest:
            return existing
    base = slugify(name or src.stem)
    td_id, n = base, 2
    while (root() / td_id).exists():
        td_id = "%s-%d" % (base, n)
        n += 1
    target = td_dir(td_id)
    shutil.copyfile(src, target / SOURCE)
    write_meta(td_id, {"id": td_id, "imported_at": time.time(), "sha1": digest,
                       "original_name": src.name})
    return td_id


def list_ids() -> List[str]:
    return sorted((d.name for d in root().iterdir()
                   if d.is_dir() and (d / SOURCE).exists()),
                  key=lambda i: read_meta(i).get("imported_at", 0), reverse=True)


def source_path(td_id: str) -> pathlib.Path:
    return td_dir(td_id) / SOURCE


def delete(td_id: str) -> None:
    d = root() / td_id
    if d.is_dir():
        shutil.rmtree(d)


# --------------------------------------------------------------- lecture
def _read_json(td_id: str, name: str) -> Optional[dict]:
    p = td_dir(td_id) / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_json(td_id: str, name: str, data: dict) -> None:
    (td_dir(td_id) / name).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                      encoding="utf-8")


def read_meta(td_id: str) -> dict:
    return _read_json(td_id, META) or {}


def write_meta(td_id: str, data: dict) -> None:
    _write_json(td_id, META, data)


def update_meta(td_id: str, **fields) -> None:
    meta = read_meta(td_id)
    meta.update(fields)
    write_meta(td_id, meta)


def read_structure(td_id: str) -> Optional[dict]:
    return _read_json(td_id, STRUCTURE)


def write_structure(td_id: str, data: dict) -> None:
    _write_json(td_id, STRUCTURE, data)


def exercises(td_id: str) -> List[dict]:
    data = read_structure(td_id) or {}
    return data.get("exercises") or []


def title(td_id: str) -> str:
    data = read_structure(td_id) or {}
    return data.get("title") or read_meta(td_id).get("original_name") or td_id


# ------------------------------------------------------------ corrections
def exercise_fingerprint(exercise: dict) -> str:
    """Identifie un exercice par ce qui détermine sa correction."""
    payload = json.dumps([exercise.get("statement"), exercise.get("courses"),
                          exercise.get("key_results")], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _correction_path(td_id: str, index: int) -> pathlib.Path:
    d = td_dir(td_id) / CORRECTIONS
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%02d.html" % index)


def read_correction(td_id: str, index: int, fingerprint: Optional[str] = None) -> Optional[str]:
    p = _correction_path(td_id, index)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    head, _, body = text.partition("\n")
    if fingerprint is not None and head.strip() != "<!--%s-->" % fingerprint:
        return None
    body = body.strip()
    return body if len(body) > 200 else None


def write_correction(td_id: str, index: int, fingerprint: str, html_text: str) -> None:
    _correction_path(td_id, index).write_text("<!--%s-->\n%s" % (fingerprint, html_text),
                                              encoding="utf-8")


def state(td_id: str) -> dict:
    """Où en est un TD : structuré ? combien d'exercices corrigés ?"""
    items = exercises(td_id)
    done = sum(1 for i, ex in enumerate(items)
               if read_correction(td_id, i, exercise_fingerprint(ex)) is not None)
    return {"structured": bool(items), "total": len(items), "corrected": done,
            "complete": bool(items) and done == len(items)}
