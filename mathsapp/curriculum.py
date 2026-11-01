"""Le cursus : les packs de cours actifs et le profil de l'apprenant.

Un *pack* est un morceau de syllabus autonome : ses domaines, ses cours, ses
parcours, et quelques métadonnées qui orientent la génération (la discipline,
l'objectif visé, des consignes de style propres à la discipline).

- Les packs intégrés vivent dans `mathsapp/data/packs/` et sont versionnés.
  `maths` est le socle : toujours actif, les autres s'appuient dessus.
- Les packs créés depuis l'application (« Nouveau cursus ») vivent dans
  `library/packs/`, à côté du contenu généré. Ils s'exportent et s'importent
  comme un simple fichier JSON, pour les partager.

Le choix des packs actifs et le profil (niveau de départ, nom affiché) sont
dans `library/curriculum.json`.
"""
from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from typing import Dict, List, Optional

from .paths import DATA_DIR, library_dir

BUILTIN_DIR = DATA_DIR / "packs"
BASE_PACK = "maths"
CUSTOM_PACK = "perso"          # cours ajoutés un par un (syllabus_extra)
CUSTOM_GROUP = "perso"         # parcours sans groupe connu
BUILTIN_ORDER = ["maths", "ml-mva"]
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")

DEFAULT_LEVELS = [
    {"value": 1, "name": "Fondations"},
    {"value": 2, "name": "Licence 1-2"},
    {"value": 3, "name": "Licence 3"},
    {"value": 4, "name": "Master 1"},
    {"value": 5, "name": "Master 2 / recherche"},
]

DEFAULT_PROFILE = {
    "title": "Mon cursus",
    "start_level": ("fin de lycée scientifique (spécialité mathématiques), "
                    "sans notion post-bac"),
    "about": "",
}

# Profil d'origine de l'application : celui qu'on reprend pour une
# bibliothèque créée avant l'arrivée des packs.
LEGACY_PROFILE = {
    "title": "Maths MVA",
    "start_level": ("terminale option maths expertes, solide mais sans aucune "
                    "notion post-bac"),
    "about": "",
}

PACK_DEFAULTS = {
    "title": "",
    "description": "",
    "discipline": "sciences",
    "requires": [],
    "goal": "",
    "style": [],
    "domains": [],
    "levels": [],
    "track_groups": [],
    "tracks": [],
    "track_overrides": {},
    "courses": [],
}


# ----------------------------------------------------------------- fichiers
def user_packs_dir():
    d = library_dir() / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file():
    return library_dir() / "curriculum.json"


def _read_json(path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _with_defaults(data: dict, builtin: bool) -> dict:
    out = {k: (json.loads(json.dumps(v)) if isinstance(v, (list, dict)) else v)
           for k, v in PACK_DEFAULTS.items()}
    out.update(data)
    out["builtin"] = builtin
    out["title"] = out["title"] or out["id"]
    return out


# -------------------------------------------------------------------- packs
@lru_cache(maxsize=1)
def available() -> Dict[str, dict]:
    """Tous les packs connus, intégrés d'abord, par identifiant."""
    packs: Dict[str, dict] = {}
    builtin = sorted(BUILTIN_DIR.glob("*.json"),
                     key=lambda p: (BUILTIN_ORDER.index(p.stem)
                                    if p.stem in BUILTIN_ORDER else 99, p.stem))
    for path in builtin:
        data = _read_json(path)
        if data and data.get("id"):
            packs[data["id"]] = _with_defaults(data, True)
    for path in sorted(user_packs_dir().glob("*.json")):
        data = _read_json(path)
        if not data or not PACK_ID_RE.match(str(data.get("id", ""))):
            continue
        if data["id"] in packs:      # un pack perso ne remplace pas un pack intégré
            continue
        packs[data["id"]] = _with_defaults(data, False)
    return packs


def get_pack(pid: str) -> Optional[dict]:
    return available().get(pid)


def _legacy_library() -> bool:
    """Bibliothèque antérieure aux packs : du contenu déjà généré pour un cours
    intégré, ou des ajouts au syllabus."""
    lib = library_dir()
    if (lib / "syllabus_extra.json").exists():
        return True
    ids = {c["id"] for p in available().values() if p["builtin"] for c in p["courses"]}
    return any((lib / cid).is_dir() for cid in ids)


@lru_cache(maxsize=1)
def config() -> dict:
    """Packs actifs et profil. Créé au premier appel, puis figé sur le disque."""
    data = _read_json(config_file())
    if data is None:
        if _legacy_library():
            data = {"packs": list(BUILTIN_ORDER), "profile": dict(LEGACY_PROFILE)}
        else:
            data = {"packs": [BASE_PACK], "profile": dict(DEFAULT_PROFILE)}
        data["version"] = 1
        _write_config(data)
    data.setdefault("packs", [BASE_PACK])
    profile = dict(DEFAULT_PROFILE)
    profile.update({k: v for k, v in (data.get("profile") or {}).items() if v is not None})
    data["profile"] = profile
    return data


def _write_config(data: dict) -> None:
    config_file().write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")


def reload() -> None:
    """À appeler après une modification des packs ou du profil."""
    available.cache_clear()
    config.cache_clear()


def profile() -> dict:
    return dict(config()["profile"])


def set_profile(**fields) -> None:
    data = dict(config())
    prof = dict(data["profile"])
    prof.update({k: (v or "").strip() for k, v in fields.items() if k in DEFAULT_PROFILE})
    data["profile"] = prof
    _write_config(data)
    reload()


def _with_requirements(ids: List[str]) -> List[str]:
    """Ajoute les packs requis et ordonne : un pack vient après ce qu'il requiert."""
    packs = available()
    ordered: List[str] = []
    visiting = set()

    def visit(pid: str) -> None:
        if pid in ordered or pid not in packs or pid in visiting:
            return
        visiting.add(pid)
        for req in packs[pid]["requires"]:
            visit(req)
        visiting.discard(pid)
        ordered.append(pid)

    visit(BASE_PACK)
    for pid in ids:
        visit(pid)
    return ordered


def active_ids() -> List[str]:
    return _with_requirements(list(config()["packs"]))


def set_active(ids: List[str]) -> List[str]:
    """Active exactement ces packs (plus le socle et leurs prérequis)."""
    data = dict(config())
    data["packs"] = _with_requirements(list(ids))
    _write_config(data)
    reload()
    return data["packs"]


def dependents_of(pid: str) -> List[str]:
    """Packs actifs qui requièrent `pid`, directement ou non."""
    active = active_ids()
    packs = available()
    out: List[str] = []
    changed = True
    targets = {pid}
    while changed:
        changed = False
        for other in active:
            if other not in out and other not in targets and \
                    set(packs[other]["requires"]) & (targets | set(out)):
                out.append(other)
                changed = True
    return out


# ------------------------------------------------------------------ fusion
def merged_base(ids: Optional[List[str]] = None) -> dict:
    """Le syllabus formé par les packs actifs (sans les ajouts un par un)."""
    packs = available()
    ids = _with_requirements(ids) if ids is not None else active_ids()
    data = {"version": 1, "packs": [], "domains": [], "levels": [],
            "track_groups": [], "tracks": [], "courses": []}
    seen_domains, seen_courses, seen_groups, seen_tracks = set(), set(), set(), set()
    overrides: Dict[str, dict] = {}
    for pid in ids:
        pack = packs[pid]
        data["packs"].append({k: pack[k] for k in (
            "id", "title", "description", "discipline", "requires", "goal",
            "style", "builtin")})
        if pack["levels"] and not data["levels"]:
            data["levels"] = list(pack["levels"])
        for d in pack["domains"]:
            if d.get("id") and d["id"] not in seen_domains:
                seen_domains.add(d["id"])
                data["domains"].append(dict(d, pack=pid))
        for c in pack["courses"]:
            if c.get("id") and c["id"] not in seen_courses:
                seen_courses.add(c["id"])
                data["courses"].append(dict(c, pack=pid))
        for g in pack["track_groups"]:
            if g.get("id") and g["id"] not in seen_groups:
                seen_groups.add(g["id"])
                data["track_groups"].append(dict(g, pack=pid))
        for t in pack["tracks"]:
            if t.get("id") and t["id"] not in seen_tracks:
                seen_tracks.add(t["id"])
                data["tracks"].append(dict(t, pack=pid))
        for tid, o in (pack["track_overrides"] or {}).items():
            overrides[tid] = dict(overrides.get(tid, {}), **o)
    for t in data["tracks"]:
        if t["id"] in overrides:
            t.update({k: v for k, v in overrides[t["id"]].items()
                      if k in ("group", "title", "featured")})
    if not data["levels"]:
        data["levels"] = list(DEFAULT_LEVELS)
    return data


# ---------------------------------------------------------- packs de l'usager
def user_pack_path(pid: str):
    return user_packs_dir() / ("%s.json" % pid)


def save_pack(pack: dict) -> str:
    """Enregistre un pack créé par l'utilisateur. Retourne son identifiant."""
    pid = pack.get("id", "")
    if not PACK_ID_RE.match(pid):
        raise ValueError("identifiant de pack invalide : %r" % pid)
    existing = available().get(pid)
    if existing and existing["builtin"]:
        raise ValueError("« %s » est un pack intégré" % pid)
    clean = {k: v for k, v in pack.items() if k != "builtin"}
    clean.setdefault("version", 1)
    clean.setdefault("created", time.strftime("%Y-%m-%d"))
    user_pack_path(pid).write_text(json.dumps(clean, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    reload()
    return pid


def delete_pack(pid: str) -> None:
    pack = available().get(pid)
    if not pack or pack["builtin"]:
        raise ValueError("seul un pack créé depuis l'application peut être supprimé")
    user_pack_path(pid).unlink(missing_ok=True)
    data = dict(config())
    data["packs"] = [p for p in data["packs"] if p != pid]
    _write_config(data)
    reload()


def free_pack_id(base: str) -> str:
    packs = available()
    pid, n = base, 2
    while pid in packs:
        pid = "%s-%d" % (base, n)
        n += 1
    return pid


def import_pack(path) -> str:
    """Importe un pack partagé (fichier JSON). Retourne son identifiant."""
    import pathlib
    data = _read_json(pathlib.Path(path))
    if not data or not isinstance(data.get("courses"), list) or not data.get("courses"):
        raise ValueError("ce fichier n'est pas un pack de cours")
    pid = str(data.get("id") or "")
    if not PACK_ID_RE.match(pid):
        from .syllabus_extra import slugify
        pid = slugify(data.get("title") or "cursus")[:40].strip("-") or "cursus"
    data["id"] = free_pack_id(pid) if pid in available() else pid
    return save_pack(data)


def export_pack(pid: str, path) -> None:
    import pathlib
    pack = available()[pid]
    clean = {k: v for k, v in pack.items() if k != "builtin"}
    pathlib.Path(path).write_text(json.dumps(clean, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
