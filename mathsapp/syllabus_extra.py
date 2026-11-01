"""Extensions du syllabus créées depuis l'application.

Le syllabus de base est formé par les packs actifs (voir `curriculum.py`).
Les cours ajoutés un par un depuis l'app vivent à part, dans
`library/syllabus_extra.json`, à côté du contenu généré. Les deux sont
fusionnés au chargement, de sorte qu'une mise à jour des packs n'efface jamais
ce que l'utilisateur a ajouté.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from . import curriculum
from .paths import library_dir

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")
EMPTY: Dict[str, list] = {"domains": [], "courses": [], "tracks": []}


def extra_file():
    return library_dir() / "syllabus_extra.json"


def slugify(text: str, prefix: str = "") -> str:
    """Identifiant ASCII à partir d'un titre (les ids servent de noms de dossiers)."""
    plain = "".join(c for c in unicodedata.normalize("NFD", text)
                    if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)[:56].strip("-")
    if prefix and not slug.startswith(prefix + "-"):
        slug = "%s-%s" % (prefix, slug)
    return slug or "cours"


# --------------------------------------------------------------------- accès
def read_base() -> dict:
    """Syllabus des packs actifs."""
    return curriculum.merged_base()


def read_extra() -> dict:
    path = extra_file()
    if not path.exists():
        return {k: list(v) for k, v in EMPTY.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {k: list(v) for k, v in EMPTY.items()}
    for key in EMPTY:
        data.setdefault(key, [])
    return data


def write_extra(data: dict) -> None:
    extra_file().write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")


def merged() -> dict:
    """Syllabus complet : base + ajouts de l'utilisateur."""
    base = read_base()
    extra = read_extra()
    if not (extra["domains"] or extra["courses"] or extra["tracks"]):
        return base

    data = dict(base)
    data["packs"] = list(base.get("packs", [])) + [{
        "id": curriculum.CUSTOM_PACK, "title": "Mes ajouts", "description": "",
        "discipline": "", "requires": [], "goal": "", "style": [], "builtin": False}]
    known_domains = {d["id"] for d in base["domains"]}
    data["domains"] = list(base["domains"]) + [
        dict(d, custom=True) for d in extra["domains"] if d["id"] not in known_domains]

    known_courses = {c["id"] for c in base["courses"]}
    data["courses"] = list(base["courses"]) + [
        dict(c, custom=True, pack=curriculum.CUSTOM_PACK)
        for c in extra["courses"] if c["id"] not in known_courses]

    known_tracks = {t["id"] for t in base.get("tracks", [])}
    data["tracks"] = list(base.get("tracks", [])) + [
        dict(t, custom=True) for t in extra["tracks"] if t["id"] not in known_tracks]
    return data


def custom_ids() -> Dict[str, set]:
    extra = read_extra()
    return {
        "domains": {d["id"] for d in extra["domains"]},
        "courses": {c["id"] for c in extra["courses"]},
        "tracks": {t["id"] for t in extra["tracks"]},
    }


# ---------------------------------------------------------------- validation
def _has_cycle(courses: List[dict]) -> Optional[List[str]]:
    prereqs = {c["id"]: list(c.get("prereqs", [])) for c in courses}
    color: Dict[str, int] = {}

    def visit(node: str, stack: List[str]) -> Optional[List[str]]:
        state = color.get(node, 0)
        if state == 1:
            return stack + [node]
        if state == 2:
            return None
        color[node] = 1
        for parent in prereqs.get(node, []):
            if parent in prereqs:
                found = visit(parent, stack + [node])
                if found:
                    return found
        color[node] = 2
        return None

    for cid in prereqs:
        found = visit(cid, [])
        if found:
            return found
    return None


def normalize(batch: dict, base: Optional[dict] = None,
              extra: Optional[dict] = None) -> Tuple[dict, List[str]]:
    """Nettoie une proposition de syllabus et signale ce qui a été corrigé.

    On répare plutôt que de rejeter : un prérequis inventé est retiré, un
    identifiant mal formé est recalculé. On ne refuse que ce qui rendrait le
    syllabus incohérent (doublon, cycle).
    """
    base = base if base is not None else read_base()
    extra = extra if extra is not None else read_extra()
    notes: List[str] = []

    existing_courses = {c["id"] for c in base["courses"]} | {c["id"] for c in extra["courses"]}
    existing_domains = {d["id"] for d in base["domains"]} | {d["id"] for d in extra["domains"]}
    existing_titles = {c["title"].strip().lower() for c in base["courses"]}

    # ---- domaines proposés
    domains: List[dict] = []
    for d in batch.get("domains", []) or []:
        did = d.get("id") or slugify(d.get("name", ""))
        if not ID_RE.match(did):
            did = slugify(did)
        if did in existing_domains:
            continue
        domains.append({
            "id": did,
            "name": (d.get("name") or did).strip(),
            "description": (d.get("description") or "").strip(),
            "color": d.get("color") if re.match(r"^#[0-9a-fA-F]{6}$", d.get("color") or "")
            else "#64748b",
        })
        existing_domains.add(did)

    # ---- cours proposés
    courses: List[dict] = []
    seen: Dict[str, str] = {}
    for c in batch.get("courses", []) or []:
        title = (c.get("title") or "").strip()
        if not title:
            continue
        cid = (c.get("id") or "").strip()
        if not ID_RE.match(cid):
            cid = slugify(cid or title)
            notes.append("identifiant recalculé pour « %s » : %s" % (title, cid))
        if cid in existing_courses or cid in seen:
            notes.append("« %s » ignoré : l'identifiant %s existe déjà" % (title, cid))
            continue
        if title.lower() in existing_titles:
            notes.append("« %s » ignoré : ce cours existe déjà" % title)
            continue
        domain = c.get("domain")
        if domain not in existing_domains:
            fallback = domains[0]["id"] if domains else base["domains"][-1]["id"]
            notes.append("domaine inconnu « %s » pour « %s », rattaché à %s"
                         % (domain, title, fallback))
            domain = fallback
        try:
            level = int(c.get("level", 3))
        except (TypeError, ValueError):
            level = 3
        level = max(1, min(5, level))
        courses.append({
            "id": cid,
            "title": title,
            "domain": domain,
            "level": level,
            "prereqs": [p for p in (c.get("prereqs") or []) if isinstance(p, str)],
            "summary": (c.get("summary") or "").strip(),
            "objectives": [o.strip() for o in (c.get("objectives") or []) if o and o.strip()],
            "keywords": [k.strip() for k in (c.get("keywords") or []) if k and k.strip()],
        })
        seen[cid] = title
        existing_courses.add(cid)

    # ---- prérequis : on ne garde que ceux qui existent
    valid = existing_courses
    for c in courses:
        kept, dropped = [], []
        for p in c["prereqs"]:
            (kept if p in valid and p != c["id"] else dropped).append(p)
        if dropped:
            notes.append("prérequis inconnus retirés de « %s » : %s"
                         % (c["title"], ", ".join(dropped)))
        c["prereqs"] = kept

    # ---- parcours proposés
    tracks: List[dict] = []
    groups = {g["id"] for g in base.get("track_groups", [])}
    existing_tracks = {t["id"] for t in base.get("tracks", [])} | {t["id"] for t in extra["tracks"]}
    for t in batch.get("tracks", []) or []:
        tid = t.get("id") or slugify(t.get("title", ""))
        if not ID_RE.match(tid) or tid in existing_tracks:
            continue
        goal = t.get("goal")
        if goal not in valid:
            continue
        tracks.append({
            "id": tid,
            "title": (t.get("title") or tid).strip(),
            "goal": goal,
            "extra": [e for e in (t.get("extra") or []) if e in valid and e != goal],
            "group": t.get("group") if t.get("group") in groups else curriculum.CUSTOM_GROUP,
        })
        existing_tracks.add(tid)

    return {"domains": domains, "courses": courses, "tracks": tracks}, notes


def check(batch: dict, base: Optional[dict] = None,
          extra: Optional[dict] = None) -> List[str]:
    """Erreurs bloquantes d'une proposition déjà normalisée."""
    base = base if base is not None else read_base()
    extra = extra if extra is not None else read_extra()
    errors: List[str] = []
    if not batch.get("courses"):
        errors.append("Aucun cours exploitable dans la proposition.")
        return errors
    all_courses = base["courses"] + extra["courses"] + batch["courses"]
    cycle = _has_cycle(all_courses)
    if cycle:
        errors.append("Le graphe de prérequis contiendrait un cycle : %s"
                      % " → ".join(cycle))
    return errors


# ------------------------------------------------------------------- édition
def add(batch: dict) -> List[str]:
    """Fusionne une proposition normalisée. Retourne les erreurs bloquantes."""
    extra = read_extra()
    errors = check(batch, extra=extra)
    if errors:
        return errors
    known_domains = {d["id"] for d in extra["domains"]}
    extra["domains"] += [d for d in batch["domains"] if d["id"] not in known_domains]
    known_courses = {c["id"] for c in extra["courses"]}
    extra["courses"] += [c for c in batch["courses"] if c["id"] not in known_courses]
    known_tracks = {t["id"] for t in extra["tracks"]}
    extra["tracks"] += [t for t in batch["tracks"] if t["id"] not in known_tracks]
    write_extra(extra)
    return []


def remove_courses(ids) -> int:
    """Retire des cours ajoutés, ainsi que les références qui pointent vers eux."""
    ids = set(ids)
    extra = read_extra()
    before = len(extra["courses"])
    extra["courses"] = [c for c in extra["courses"] if c["id"] not in ids]
    for c in extra["courses"]:
        c["prereqs"] = [p for p in c["prereqs"] if p not in ids]
    for t in extra["tracks"]:
        t["extra"] = [e for e in t.get("extra", []) if e not in ids]
        if t.get("courses"):
            t["courses"] = [c for c in t["courses"] if c not in ids]
            if t.get("goal") in ids:
                t["goal"] = t["courses"][-1] if t["courses"] else t["goal"]
    extra["tracks"] = [t for t in extra["tracks"]
                       if t.get("goal") not in ids]
    used = {c["domain"] for c in extra["courses"]}
    extra["domains"] = [d for d in extra["domains"] if d["id"] in used]
    write_extra(extra)
    return before - len(extra["courses"])
