"""Brouillons des démonstrations : comment on TROUVE la preuve.

Chaque démonstration présentée dans l'application peut recevoir un brouillon
généré à partir de son énoncé et de sa preuve rédigée : point de départ, idée
directrice, démarche à rebours, tentative naïve, lien avec la preuve propre,
astuce réutilisable.

Deux familles de démonstrations :
- celles du cours (<details class="proof"> de body.html), clé « c-<résultat> » ;
- les démonstrations à faire (exercises.json), clé « d-<id> ».

Les brouillons vivent dans library/<cours>/brouillons/<clé>.json, un fichier
par démonstration : ils survivent à la régénération du cours. Chacun garde
l'empreinte de la preuve dont il est issu ; si la preuve change, il est
signalé comme obsolète.

Ne pas confondre avec store.proof_drafts : la rédaction de l'utilisateur.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import pathlib
import re
import time
import unicodedata
from typing import Dict, List, Optional

from . import content
from .paths import course_dir

FOLDER = "brouillons"

# En deçà, la preuve tient en une ligne : pas de brouillon proposé.
MIN_CHARS = 220

_PROOF_RE = re.compile(r'<details\b[^>]*\bclass="proof"[^>]*>', re.I)
_DATA_OF_RE = re.compile(r'data-of="([^"]*)"', re.I)
_SUMMARY_RE = re.compile(r"<summary\b.*?</summary>", re.S | re.I)
_STATEMENT_RE = re.compile(
    r'<div class="box (?:theorem|proposition|lemma|corollary)"', re.I)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")


def fingerprint(*texts: str) -> str:
    payload = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def course_entries(body: str) -> List[dict]:
    """Les démonstrations du cours rédigé, dans l'ordre, avec leur clé stable.

    La clé vient du nom du résultat (data-of) : elle survit à une régénération
    du cours tant que le résultat garde son nom."""
    out, used, last = [], set(), 0
    for i, m in enumerate(_PROOF_RE.finditer(body)):
        if m.start() < last:
            continue
        close = body.find("</details>", m.end())
        if close < 0:
            continue
        last = close
        inner = body[m.end():close]
        of = _DATA_OF_RE.search(m.group(0))
        title = html.unescape(of.group(1)).strip() if of else ""
        base = "c-" + (_slug(title) or str(i + 1))
        key, n = base, 2
        while key in used:
            key, n = "%s-%d" % (base, n), n + 1
        used.add(key)
        # l'énoncé : le dernier encadré de résultat avant la preuve
        window = body[max(0, m.start() - 6000):m.start()]
        boxes = list(_STATEMENT_RE.finditer(window))
        before = window[boxes[-1].start():] if boxes else window[-1500:]
        out.append({
            "key": key, "title": title or "Démonstration %d" % (i + 1),
            "statement": content._plain(before)[-1500:],
            "text": content._plain(_SUMMARY_RE.sub(" ", inner)),
            "open_end": m.end(), "where": "cours",
        })
    return out


def annotate(body: str) -> str:
    """Ajoute data-brouillon="<clé>" à chaque démonstration du cours."""
    entries = course_entries(body)
    for e in reversed(entries):
        cut = e["open_end"] - 1          # avant le « > » de la balise ouvrante
        body = body[:cut] + ' data-brouillon="%s"' % e["key"] + body[cut:]
    return body


def proofs(course_id: str) -> List[dict]:
    """Toutes les démonstrations d'un cours : celles du cours, puis celles à faire."""
    out = []
    if content.has_course(course_id):
        out.extend(course_entries(content.read_body(course_id)))
    data = content.read_exercises(course_id) or {}
    for p in data.get("proofs") or []:
        steps = " ".join("%s : %s" % (s.get("title", ""), s.get("content", ""))
                         for s in p.get("steps") or [])
        out.append({
            "key": "d-" + (_slug(p.get("id") or "") or str(len(out) + 1)),
            "title": content._plain(p.get("title") or "Démonstration"),
            "statement": content._plain(p.get("statement") or ""),
            "text": content._plain((p.get("solution") or "") + " " + steps),
            "where": "démonstrations",
        })
    for e in out:
        e["fingerprint"] = fingerprint(e["statement"], e["text"])
        e["eligible"] = len(e["text"]) >= MIN_CHARS
    return out


# ------------------------------------------------------------------ stockage
def _dir(course_id: str, create: bool = False) -> pathlib.Path:
    d = course_dir(course_id, create=create) / FOLDER
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def read(course_id: str, key: str) -> Optional[dict]:
    p = _dir(course_id) / ("%s.json" % key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(course_id: str, entry: dict, html_text: str, trivial: bool, **meta) -> dict:
    """Écrit un brouillon d'un bloc (fichier temporaire puis renommage)."""
    data = {"key": entry["key"], "title": entry["title"],
            "fingerprint": entry["fingerprint"], "html": html_text,
            "trivial": bool(trivial), "created_at": time.time()}
    data.update(meta)
    d = _dir(course_id, create=True)
    tmp = d / ("%s.json.tmp" % entry["key"])
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, d / ("%s.json" % entry["key"]))
    return data


def status(entry: dict, saved: Optional[dict]) -> str:
    """« missing », « ok » ou « obsolete » (la preuve a changé depuis)."""
    if not saved:
        return "missing"
    return "ok" if saved.get("fingerprint") == entry.get("fingerprint") else "obsolete"


def state_map(course_id: str, entries: Optional[List[dict]] = None) -> Dict[str, dict]:
    """{clé: {eligible, status, html, trivial}} : ce que les pages affichent."""
    out = {}
    for e in entries if entries is not None else proofs(course_id):
        saved = read(course_id, e["key"])
        out[e["key"]] = {"eligible": e["eligible"], "status": status(e, saved),
                         "html": (saved or {}).get("html", ""),
                         "trivial": bool((saved or {}).get("trivial"))}
    return out


def pending(course_id: str, entries: Optional[List[dict]] = None) -> List[dict]:
    """Démonstrations qui méritent un brouillon et n'en ont pas d'à jour."""
    entries = entries if entries is not None else proofs(course_id)
    return [e for e in entries
            if e["eligible"] and status(e, read(course_id, e["key"])) != "ok"]


def inject(page: str, course_id: str) -> str:
    """Joint l'état des brouillons à une page (window.BROUILLONS)."""
    data = json.dumps(content.protect_math_data(state_map(course_id)),
                      ensure_ascii=False).replace("</", "<\\/")
    script = "<script>window.BROUILLONS = %s;</script>\n" % data
    return page.replace("</head>", script + "</head>", 1)
