"""Lecture / ecriture des cours generes et assemblage des pages HTML."""
from __future__ import annotations

import html
import json
import pathlib
import re
from typing import Optional

from .paths import ASSETS_DIR, course_dir

BODY = "body.html"
SECTIONS = "sections"
PLAN = "plan.json"
EXOS = "exercises.json"
META = "meta.json"


# ------------------------------------------------------------------- acces
def _p(course_id: str, name: str, create: bool = False) -> pathlib.Path:
    return course_dir(course_id, create=create) / name


def has_course(course_id: str) -> bool:
    p = _p(course_id, BODY)
    return p.exists() and p.stat().st_size > 200


def has_exercises(course_id: str) -> bool:
    p = _p(course_id, EXOS)
    return p.exists() and p.stat().st_size > 50


def read_body(course_id: str) -> str:
    return _p(course_id, BODY).read_text(encoding="utf-8")


def write_body(course_id: str, body: str) -> None:
    _p(course_id, BODY, create=True).write_text(body, encoding="utf-8")


def sections_dir(course_id: str, create: bool = False) -> pathlib.Path:
    d = course_dir(course_id, create=create) / SECTIONS
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def read_section(course_id: str, index: int, fingerprint: str) -> Optional[str]:
    """Section deja generee pour ce plan, ou None.

    Le plan peut changer d'une generation a l'autre : on ne reutilise une
    section que si l'empreinte du plan est la meme.
    """
    p = sections_dir(course_id) / ("%02d.html" % index)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    head, _, body = text.partition("\n")
    if head.strip() != "<!--%s-->" % fingerprint or len(body.strip()) < 200:
        return None
    return body.strip()


def write_section(course_id: str, index: int, fingerprint: str, html_text: str) -> None:
    p = sections_dir(course_id, create=True) / ("%02d.html" % index)
    p.write_text("<!--%s-->\n%s" % (fingerprint, html_text), encoding="utf-8")


def read_json(course_id: str, name: str) -> Optional[dict]:
    p = _p(course_id, name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_json(course_id: str, name: str, data) -> None:
    _p(course_id, name, create=True).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def read_plan(course_id: str):
    return read_json(course_id, PLAN)


def read_exercises(course_id: str):
    return read_json(course_id, EXOS)


def read_meta(course_id: str):
    return read_json(course_id, META) or {}


def delete_course(course_id: str) -> None:
    d = course_dir(course_id)
    if not d.is_dir():
        return
    for f in d.iterdir():
        if f.is_file():
            f.unlink()
    sec = d / SECTIONS
    if sec.is_dir():
        for f in sec.iterdir():
            if f.is_file():
                f.unlink()


# ------------------------------------------------------------------ nettoyage
_FENCE_OPEN = re.compile(r"^\s*```(?:html)?\s*\n", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\n\s*```\s*$")
_WRAPPER = re.compile(r"</?(?:html|head|body|article|!DOCTYPE)[^>]*>", re.IGNORECASE)


def clean_html(text: str) -> str:
    """Retire les artefacts frequents des reponses de modele."""
    out = text.strip()
    out = _FENCE_OPEN.sub("", out)
    out = _FENCE_CLOSE.sub("", out)
    out = _WRAPPER.sub("", out)
    # une phrase d'introduction avant la premiere balise
    first = out.find("<")
    if 0 < first < 220 and "\n" in out[:first]:
        out = out[first:]
    return out.strip()


# ------------------------------------------------------------------- rendu
def _template() -> str:
    return (ASSETS_DIR / "template.html").read_text(encoding="utf-8")


def assets_url() -> str:
    return pathlib.Path(ASSETS_DIR).resolve().as_uri()


def build_page(body: str, title: str, theme: str = "light", extra_css: str = "") -> str:
    return (_template()
            .replace("__THEME__", theme)
            .replace("__TITLE__", html.escape(title))
            .replace("__ASSETS__", assets_url())
            .replace("__EXTRA_CSS__", extra_css)
            .replace("__BODY__", body))


def render_course_page(course_id: str, title: str, theme: str = "light") -> pathlib.Path:
    """Ecrit la page complete du cours et retourne son chemin."""
    page = build_page(read_body(course_id), title, theme)
    out = course_dir(course_id, create=True) / "_render.html"
    out.write_text(page, encoding="utf-8")
    return out


def render_scratch_page(body: str, title: str, theme: str, name: str) -> pathlib.Path:
    """Page autonome (chat, aide a la demonstration, apercu)."""
    from .paths import library_dir
    d = library_dir() / "_views"
    d.mkdir(parents=True, exist_ok=True)
    out = d / ("%s.html" % name)
    out.write_text(build_page(body, title, theme), encoding="utf-8")
    return out


# -------------------------------------------------------------------- digest
def digest(course_id: str, limit: int = 9000) -> str:
    """Extrait condense du cours, pour prompter la generation d'exercices."""
    body = read_body(course_id)
    body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.S | re.I)
    keep = []
    for m in re.finditer(
            r'<(h1|h2|h3)[^>]*>(.*?)</\1>'
            r'|<div class="box ([a-z]+)"[^>]*>(.*?)</div>'
            r'|<p class="lead">(.*?)</p>', body, flags=re.S | re.I):
        chunk = next(g for g in m.groups()[1::2] if g) if any(m.groups()[1::2]) else ""
        tag = m.group(1) or m.group(3) or "lead"
        text = re.sub(r"<[^>]+>", " ", chunk or "")
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        if text:
            keep.append("[%s] %s" % (tag, text[:600]))
    out = "\n".join(keep)
    return out[:limit]
