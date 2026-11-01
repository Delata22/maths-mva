"""Cours importés : un cours magistral en PDF devient un cours de l'application.

Le document est rangé comme un sujet de TD (library/_td/<id>, type « course ») :
on réutilise ainsi la copie, la lecture des exercices et leur correction. Ce
module ajoute ce qui est propre aux cours :
- la transcription du document en plan (import.json) ;
- l'inscription du cours dans le syllabus, domaine « Cours importés » ;
- un plan de génération qui garde la source : chaque section relit ses pages ;
- la page de l'onglet Exercices du cours.
"""
from __future__ import annotations

import html as html_mod
import json
import re
from typing import Dict, List, Optional

from . import content, syllabus_extra, td as td_mod
from .syllabus import Syllabus

KIND = "course"
IMPORT = "import.json"
DOMAIN = {
    "id": "mva-cours",          # identifiant historique, gardé pour les imports existants
    "name": "Cours importés",
    "description": "Cours magistraux importés en PDF : réécrits avec des "
                   "intuitions, reliés au cursus, exercices corrigés.",
    "color": "#0ea5e9",
}


# ------------------------------------------------------------------ stockage
def import_pdf(path: str) -> str:
    doc = td_mod.import_pdf(path)
    meta = td_mod.read_meta(doc)
    if meta.get("kind", "td") != KIND:
        if td_mod.read_structure(doc) is not None:
            raise ValueError("Ce PDF est déjà importé comme sujet de TD.")
        td_mod.update_meta(doc, kind=KIND)
    return doc


def list_ids() -> List[str]:
    return td_mod.list_ids(KIND)


def read_import(doc: str) -> Optional[dict]:
    path = td_mod.td_dir(doc) / IMPORT
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_import(doc: str, data: dict) -> None:
    (td_mod.td_dir(doc) / IMPORT).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def course_of(doc: str) -> Optional[str]:
    return td_mod.read_meta(doc).get("course_id")


def doc_for_course(course_id: str) -> Optional[str]:
    for doc in list_ids():
        if course_of(doc) == course_id:
            return doc
    return None


# --------------------------------------------------------------- normalisation
def _strings(values, limit: int) -> List[str]:
    out = []
    for v in values or []:
        v = str(v).strip()
        if v and v not in out:
            out.append(v)
    return out[:limit]


def _ids(values, syl: Syllabus, limit: int) -> List[str]:
    return [cid for cid in _strings(values, 50) if cid in syl.courses][:limit]


def normalize_import(raw: dict, syl: Syllabus) -> dict:
    """Nettoie la transcription du document : identifiants inconnus retirés, bornes."""
    try:
        level = max(1, min(5, int(raw.get("level") or 4)))
    except (TypeError, ValueError):
        level = 4
    exercises = []
    for i, ex in enumerate(raw.get("exercises") or []):
        statement = str(ex.get("statement") or "").strip()
        if not statement:
            continue
        number = str(ex.get("number") or i + 1).strip()
        try:
            difficulty = max(1, min(5, int(ex.get("difficulty") or 3)))
        except (TypeError, ValueError):
            difficulty = 3
        exercises.append({
            "number": number,
            "title": str(ex.get("title") or "").strip() or "Exercice %s" % number,
            "pages": str(ex.get("pages") or "").strip(),
            "statement": content.clean_html(statement),
            "courses": _ids(ex.get("courses"), syl, 4),
            "key_results": _strings(ex.get("key_results"), 8),
            "difficulty": difficulty,
        })
    numbers = {e["number"] for e in exercises}
    sections = []
    for i, s in enumerate(raw.get("sections") or []):
        title = str(s.get("title") or "").strip()
        if not title:
            continue
        sections.append({
            "id": "s%d" % (len(sections) + 1),
            "title": title,
            "pages": str(s.get("pages") or "").strip(),
            "goal": str(s.get("goal") or "").strip(),
            "content": str(s.get("content") or "").strip(),
            "intuitions": _strings(s.get("intuitions"), 8),
            "proofs": _strings(s.get("proofs"), 8),
            "exercises": [n for n in _strings(s.get("exercises"), 10) if n in numbers],
        })
    return {
        "title": str(raw.get("title") or "").strip() or "Cours importé",
        "original_title": str(raw.get("original_title") or "").strip(),
        "author": str(raw.get("author") or "").strip(),
        "language": str(raw.get("language") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "level": level,
        "keywords": _strings(raw.get("keywords"), 12),
        "objectives": _strings(raw.get("objectives"), 8),
        "prereqs": _ids(raw.get("prereqs"), syl, 6),
        "related": _ids(raw.get("related"), syl, 12),
        "sections": sections,
        "exercises": exercises,
    }


def course_entry(data: dict, suffix: str = "") -> dict:
    title = data["title"] + suffix
    return {
        "id": syllabus_extra.slugify(title, prefix="imp"),
        "title": title,
        "domain": DOMAIN["id"],
        "level": data["level"],
        "prereqs": list(data["prereqs"]),
        "summary": data["summary"],
        "objectives": list(data["objectives"]),
        "keywords": list(data["keywords"]),
    }


def build_plan(data: dict, doc: str, syl: Syllabus) -> dict:
    """Plan de génération : celui du document, plus de quoi relire la source."""
    titles = {e["number"]: e["title"] for e in data["exercises"]}
    return {
        "hook": data["summary"],
        "sections": [{
            "id": s["id"], "title": s["title"], "goal": s["goal"], "content": s["content"],
            "figures": [], "proofs": s["proofs"], "pages": s["pages"],
            "intuitions": s["intuitions"],
            "exercises": [{"number": n, "title": titles[n]} for n in s["exercises"]],
        } for s in data["sections"]],
        "proved_in_course": [],
        "left_as_exercise": [],
        "source": {
            "doc_id": doc,
            "pdf": str(td_mod.source_path(doc)),
            "original_title": data["original_title"],
            "author": data["author"],
            "related": [{"id": cid, "title": syl.title(cid)} for cid in data["related"]],
        },
    }


# ---------------------------------------------------------------- inscription
def register(doc: str, syl: Syllabus) -> str:
    """Inscrit le cours au syllabus, écrit son plan et la liste de ses exercices."""
    from .syllabus import reload
    meta = td_mod.read_meta(doc)
    data = read_import(doc)
    if data is None:
        raise ValueError("Le document doit être lu avant d'être inscrit.")
    cid = meta.get("course_id")
    if not (cid and cid in syl.courses):
        batch = None
        for suffix in ("", " (importé)", " — %s" % doc):
            entry = course_entry(data, suffix)
            candidate, _notes = syllabus_extra.normalize(
                {"domains": [DOMAIN], "courses": [entry], "tracks": []})
            if candidate["courses"]:
                batch = candidate
                break
        if batch is None:
            raise ValueError("Impossible d'inscrire « %s » au syllabus." % data["title"])
        errors = syllabus_extra.add(batch)
        if errors:
            raise ValueError("; ".join(errors))
        cid = batch["courses"][0]["id"]
        syl = reload()

    if not content.read_plan(cid):
        content.write_json(cid, content.PLAN, build_plan(data, doc, syl))
    td_mod.write_structure(doc, {
        "title": data["title"],
        "subject": "Exercices du cours",
        "exercises": [dict(e, courses=[cid] + [c for c in e["courses"] if c != cid][:4])
                      for e in data["exercises"]],
    })
    td_mod.update_meta(doc, course_id=cid, title=data["title"])
    return cid


# ------------------------------------------------------------ onglet Exercices
def exercises_body(doc: str) -> str:
    items = td_mod.exercises(doc)
    if not items:
        return "<p class=\"lead\">Ce cours ne contient pas d'exercice.</p>"
    parts = ["<h1>Exercices du cours</h1>",
             "<p class=\"lead\">Les exercices du document, avec une correction commentée. "
             "Cherchez d'abord : la correction se déplie.</p>"]
    for i, ex in enumerate(items):
        number = html_mod.escape(str(ex.get("number", i + 1)))
        parts.append('<h2 id="exercice-%s">Exercice %s — %s</h2>'
                     % (number, number, html_mod.escape(ex.get("title", ""))))
        parts.append('<div class="box exercise"><span class="box-title">Énoncé</span>%s</div>'
                     % ex.get("statement", ""))
        correction = td_mod.read_correction(doc, i, td_mod.exercise_fingerprint(ex))
        if correction:
            correction = re.sub(r"^\s*<h2\b.*?</h2>", "", correction, count=1, flags=re.S)
            # les titres internes d'une correction repliee n'ont rien a faire au sommaire
            correction = re.sub(r"<(/?)h[23]\b", r"<\1h4", correction)
            parts.append('<details class="exo-solution"><summary>Voir la correction</summary>'
                         '<div class="exo-solution-body">%s</div></details>' % correction)
        else:
            parts.append("<p><em>Correction pas encore produite.</em></p>")
    return "\n".join(parts)
