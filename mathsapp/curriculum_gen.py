"""Concevoir un nouveau cursus (un pack) à partir d'objectifs.

Trois temps (voir les fonctions curriculum_*_prompt du module des prompts) :
  1. l'architecture : le pack, ses domaines dans l'ordre, ce que chacun couvre ;
  2. les cours, domaine par domaine, câblés sur les cours déjà présents et sur
     ceux des domaines précédents ;
  3. les parcours.

Chaque réponse du modèle est nettoyée comme une extension de syllabus
(syllabus_extra.normalize) : identifiants recalculés, doublons écartés,
prérequis inventés retirés. Rien n'est enregistré ici : le résultat est
présenté à l'utilisateur, qui l'enregistre (curriculum.save_pack).
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from . import curriculum, syllabus_extra

# couleurs de repli, lisibles sur fond clair et sombre
PALETTE = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#0891b2",
           "#ca8a04", "#dc2626", "#4f46e5", "#0d9488", "#9333ea", "#65a30d"]
DOMAIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,30}$")
MAX_PER_DOMAIN = 24

ProgressCb = Callable[[str, float], None]
CancelCb = Callable[[], bool]
# runner(prompt, system, schema, label, frac0, frac1) -> dict JSON ; et coût
Runner = Callable[..., Tuple[dict, float]]


def _domain_id(raw: str, name: str, taken: set) -> str:
    did = (raw or "").strip().lower().replace("-", "_")
    if not DOMAIN_ID_RE.match(did):
        did = syllabus_extra.slugify(raw or name or "domaine").replace("-", "_")[:24].strip("_")
    base, n = did or "domaine", 2
    while did in taken or not did:
        did = "%s_%d" % (base, n)
        n += 1
    return did


def normalize_outline(raw: dict, base: dict, size: int) -> Tuple[dict, List[str]]:
    notes: List[str] = []
    pack = dict(raw.get("pack") or {})
    pack["title"] = (pack.get("title") or "Nouveau cursus").strip()
    pack["description"] = (pack.get("description") or "").strip()
    pack["discipline"] = (pack.get("discipline") or "sciences").strip().lower()
    pack["goal"] = (pack.get("goal") or "").strip().rstrip(".")
    pack["style"] = [s.strip() for s in (pack.get("style") or []) if s and s.strip()][:8]

    taken = {d["id"] for d in base["domains"]}
    domains: List[dict] = []
    for i, d in enumerate(raw.get("domains") or []):
        name = (d.get("name") or "").strip()
        if not name:
            continue
        did = _domain_id(d.get("id", ""), name, taken)
        if d.get("id") and did != d.get("id"):
            notes.append("domaine « %s » : identifiant %s" % (name, did))
        taken.add(did)
        color = d.get("color") or ""
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            color = PALETTE[i % len(PALETTE)]
        try:
            count = int(d.get("count") or 6)
        except (TypeError, ValueError):
            count = 6
        domains.append({
            "id": did, "name": name,
            "description": (d.get("description") or "").strip(),
            "color": color,
            "scope": (d.get("scope") or "").strip(),
            "count": max(2, min(MAX_PER_DOMAIN, count)),
        })
    if not domains:
        raise ValueError("le modèle n'a proposé aucun domaine")
    # on ramène le total vers la taille demandée, sans descendre sous 2 par domaine
    total = sum(d["count"] for d in domains)
    if total > size * 1.4:
        for d in domains:
            d["count"] = max(2, round(d["count"] * size / total))
    return {"pack": pack, "domains": domains, "notes": (raw.get("notes") or "").strip()}, notes


def _base_plus(base: dict, domains: List[dict], courses: List[dict]) -> dict:
    data = dict(base)
    data["domains"] = list(base["domains"]) + [
        {k: d[k] for k in ("id", "name", "description", "color")} for d in domains]
    data["courses"] = list(base["courses"]) + list(courses)
    return data


def normalize_courses(raw: dict, domain: dict, base: dict, outline: dict,
                      produced: List[dict]) -> Tuple[List[dict], List[str]]:
    batch = {"courses": []}
    for c in (raw.get("courses") or [])[:MAX_PER_DOMAIN + 4]:
        c = dict(c)
        c["domain"] = domain["id"]
        batch["courses"].append(c)
    clean, notes = syllabus_extra.normalize(
        batch, base=_base_plus(base, outline["domains"], produced),
        extra={"domains": [], "courses": [], "tracks": []})
    return clean["courses"], notes


def normalize_tracks(raw: dict, pack_id: str, courses: List[dict]) -> List[dict]:
    ids = {c["id"] for c in courses}
    tracks, seen = [], set()
    for t in (raw.get("tracks") or [])[:8]:
        goal = t.get("goal")
        if goal not in ids:
            continue
        tid = syllabus_extra.slugify(t.get("id") or t.get("title") or goal)
        if not tid.startswith(pack_id + "-"):
            tid = "%s-%s" % (pack_id, tid)
        tid = tid[:60].strip("-")
        if tid in seen:
            continue
        seen.add(tid)
        tracks.append({
            "id": tid,
            "title": (t.get("title") or goal).strip(),
            "goal": goal,
            "extra": [e for e in (t.get("extra") or []) if e in ids and e != goal][:6],
            "group": pack_id,
        })
    if not tracks and courses:
        last = max(courses, key=lambda c: c["level"])
        tracks.append({"id": "%s-complet" % pack_id, "title": "Tout le cursus",
                       "goal": last["id"], "extra": [], "group": pack_id})
    return tracks


def assemble(outline: dict, courses: List[dict], tracks: List[dict], brief: dict,
             base: dict, pack_id: str) -> dict:
    """Le pack prêt à enregistrer."""
    by_id = {c["id"]: c for c in base["courses"]}
    requires = [curriculum.BASE_PACK]
    for c in courses:
        for p in c["prereqs"]:
            owner = by_id.get(p, {}).get("pack")
            if owner and owner not in requires and owner != curriculum.CUSTOM_PACK:
                requires.append(owner)
    used = {c["domain"] for c in courses}
    pack = outline["pack"]
    return {
        "version": 1,
        "id": pack_id,
        "title": pack["title"],
        "description": pack["description"],
        "discipline": pack["discipline"],
        "requires": requires,
        "goal": pack["goal"],
        "style": pack["style"],
        "brief": {k: brief.get(k, "") for k in
                  ("subject", "goals", "start_level", "target_level", "notes")},
        "domains": [{k: d[k] for k in ("id", "name", "description", "color")}
                    for d in outline["domains"] if d["id"] in used],
        "track_groups": [{"id": pack_id, "name": pack["title"],
                          "description": pack["description"] or pack["goal"]}],
        "tracks": tracks,
        "track_overrides": {},
        "courses": courses,
    }


def check(pack: dict, base: dict) -> List[str]:
    """Erreurs bloquantes : pas de cours, ou un cycle de prérequis."""
    if not pack.get("courses"):
        return ["Aucun cours exploitable dans la proposition."]
    cycle = syllabus_extra._has_cycle(base["courses"] + pack["courses"])
    if cycle:
        return ["Le graphe de prérequis contiendrait un cycle : %s" % " → ".join(cycle)]
    return []


def design(brief: dict, size: int, runner: Runner, syl, base: Optional[dict] = None,
           on_progress: ProgressCb = lambda *_: None,
           cancel: CancelCb = lambda: False) -> Tuple[dict, List[str], float]:
    """Conçoit le pack. `runner` appelle le modèle (injecté pour les tests).

    Retourne (pack, remarques, coût)."""
    from .generation import prompts
    base = base if base is not None else syllabus_extra.merged()
    notes: List[str] = []
    cost = 0.0
    system = ("Vous concevez des cursus universitaires complets et cohérents. "
              "Vous répondez uniquement en JSON valide.")

    raw, c = runner(prompts.curriculum_outline_prompt(syl, brief, size), system,
                    prompts.CURRICULUM_OUTLINE_SCHEMA, "Architecture du cursus", 0.02, 0.15)
    cost += c
    outline, n = normalize_outline(raw, base, size)
    notes += n

    produced: List[dict] = []
    total = len(outline["domains"])
    for i, domain in enumerate(outline["domains"]):
        if cancel():
            raise InterruptedError("annulé")
        lo = 0.15 + 0.75 * i / total
        hi = 0.15 + 0.75 * (i + 1) / total
        raw, c = runner(prompts.curriculum_courses_prompt(syl, brief, outline, domain, produced),
                        system, prompts.CURRICULUM_COURSES_SCHEMA,
                        "Cours — %s (%d/%d)" % (domain["name"], i + 1, total), lo, hi)
        cost += c
        courses, n = normalize_courses(raw, domain, base, outline, produced)
        notes += n
        produced += courses

    if cancel():
        raise InterruptedError("annulé")
    pack_id = curriculum.free_pack_id(
        syllabus_extra.slugify(outline["pack"]["title"])[:32].strip("-") or "cursus")
    raw, c = runner(prompts.curriculum_tracks_prompt(brief, outline, produced), system,
                    prompts.CURRICULUM_TRACKS_SCHEMA, "Parcours", 0.9, 0.98)
    cost += c
    tracks = normalize_tracks(raw, pack_id, produced)
    pack = assemble(outline, produced, tracks, brief, base, pack_id)
    if outline.get("notes"):
        pack["notes"] = outline["notes"]
    return pack, notes, cost


def summary(pack: dict) -> Dict[str, int]:
    return {"domains": len(pack.get("domains", [])), "courses": len(pack.get("courses", [])),
            "tracks": len(pack.get("tracks", []))}
