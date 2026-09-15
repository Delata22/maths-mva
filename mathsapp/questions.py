"""Questions libres : catalogue du cursus donné à Claude, liens vers les cours.

Claude répond puis pointe vers les cours qui traitent la question, avec des
liens <a class="course-ref" data-course="id" data-section="titre">. L'application
vérifie chaque lien avant de l'afficher : cours inconnu retiré, cours pas encore
rédigé signalé, section gardée seulement si elle existe vraiment.
"""
from __future__ import annotations

import html as html_mod
import re
import time
import unicodedata
from typing import Dict, List, Optional

from . import content, store
from .syllabus import Syllabus

PREFIX = "question:"


def new_key() -> str:
    return PREFIX + str(int(time.time() * 1000))


def threads():
    """Fils de questions ayant au moins un message, le plus récent d'abord."""
    return store.question_threads(PREFIX)


def section_titles(course_id: str) -> List[str]:
    plan = content.read_plan(course_id) or {}
    return [str(s.get("title") or "").strip()
            for s in plan.get("sections") or [] if str(s.get("title") or "").strip()]


def catalogue(syl: Syllabus) -> str:
    """Tout le cursus en une page : de quoi choisir les bons cours et sections."""
    by_domain: Dict[str, list] = {}
    for course in syl.all():
        by_domain.setdefault(course.domain, []).append(course)
    lines = []
    for did in syl.domain_order:
        courses = by_domain.get(did) or []
        if not courses:
            continue
        lines.append("## %s" % syl.domain_name(did))
        for c in courses:
            ready = content.is_complete(c.id)
            lines.append("- %s | %s | niveau %d | %s | %s" % (
                c.id, c.title, c.level, "rédigé" if ready else "non rédigé",
                ", ".join(c.keywords[:8])))
            if ready:
                titles = section_titles(c.id)
                if titles:
                    lines.append("    sections : %s" % " ; ".join(titles))
    return "\n".join(lines)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", html_mod.unescape(str(text)))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def match_section(course_id: str, wanted: str) -> Optional[str]:
    """Le titre de section réel le plus proche de celui cité, sinon None."""
    target = _norm(wanted)
    if not target:
        return None
    titles = section_titles(course_id)
    for title in titles:
        if _norm(title) == target:
            return title
    for title in titles:
        norm = _norm(title)
        if norm and (target in norm or norm in target):
            return title
    return None


_REF = re.compile(r'<a\b([^>]*\bclass="[^"]*\bcourse-ref\b[^"]*"[^>]*)>(.*?)</a>', re.S | re.I)
_ATTR = re.compile(r'([a-zA-Z][a-zA-Z-]*)\s*=\s*"([^"]*)"')


def link_courses(html_text: str, syl: Syllabus) -> str:
    """Vérifie et reconstruit chaque lien de cours. Idempotent."""
    def rebuild(m) -> str:
        attrs = {k.lower(): html_mod.unescape(v) for k, v in _ATTR.findall(m.group(1))}
        inner = m.group(2)
        cid = attrs.get("data-course", "").strip()
        if cid not in syl.courses:
            return inner
        ready = content.is_complete(cid)
        section = match_section(cid, attrs.get("data-section", "")) if ready else None
        if not ready:
            tip = "« %s » n'est pas encore rédigé : l'ouvrir pour le générer" % syl.title(cid)
        elif section:
            tip = "Ouvrir « %s » à la section « %s »" % (syl.title(cid), section)
        else:
            tip = "Ouvrir « %s »" % syl.title(cid)
        out = '<a class="course-ref%s" data-course="%s"' % ("" if ready else " todo", cid)
        if section:
            out += ' data-section="%s"' % html_mod.escape(section, quote=True)
        return out + ' title="%s">%s</a>' % (html_mod.escape(tip, quote=True), inner)

    return _REF.sub(rebuild, html_text)


def referenced_courses(html_text: str) -> List[str]:
    out: List[str] = []
    for m in _REF.finditer(html_text):
        attrs = dict(_ATTR.findall(m.group(1)))
        cid = attrs.get("data-course", "")
        if cid and cid not in out:
            out.append(cid)
    return out
