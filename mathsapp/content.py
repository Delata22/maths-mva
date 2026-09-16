"""Lecture / ecriture des cours generes et assemblage des pages HTML."""
from __future__ import annotations

import html
import json
import pathlib
import re
import time
from typing import List, Optional

from .paths import ASSETS_DIR, course_dir

BODY = "body.html"
SHEET = "sheet.html"
SECTIONS = "sections"
PLAN = "plan.json"
EXOS = "exercises.json"
QUIZZES = "quizzes.json"
META = "meta.json"


# ------------------------------------------------------------------- acces
def _p(course_id: str, name: str, create: bool = False) -> pathlib.Path:
    return course_dir(course_id, create=create) / name


def has_course(course_id: str) -> bool:
    p = _p(course_id, BODY)
    return p.exists() and p.stat().st_size > 200


def is_complete(course_id: str) -> bool:
    """Un cours n'est fini que si meta.json existe : il est ecrit en dernier."""
    return has_course(course_id) and has_exercises(course_id) and bool(read_meta(course_id))


def generation_state(course_id: str) -> dict:
    """Ou en est la generation de ce cours.

    Sert a distinguer un cours termine d'un cours interrompu en cours de route :
    body.html est ecrit au fil des sections, il ne prouve rien a lui seul.
    """
    plan = read_plan(course_id)
    total = len(plan.get("sections", [])) if plan else 0
    done = 0
    if plan:
        from .generation.pipeline import plan_fingerprint
        fingerprint = plan_fingerprint(plan)
        done = sum(1 for i in range(total)
                   if read_section(course_id, i, fingerprint) is not None)
    started = bool(plan) or has_course(course_id)
    complete = is_complete(course_id)
    return {
        "started": started,
        "complete": complete,
        "sections_done": done,
        "sections_total": total,
        "has_exercises": has_exercises(course_id),
        "partial": started and not complete,
    }


def has_exercises(course_id: str) -> bool:
    p = _p(course_id, EXOS)
    return p.exists() and p.stat().st_size > 50


def has_sheet(course_id: str) -> bool:
    p = _p(course_id, SHEET)
    return p.exists() and p.stat().st_size > 200


def read_sheet(course_id: str) -> str:
    return _p(course_id, SHEET).read_text(encoding="utf-8")


def write_sheet(course_id: str, body: str) -> None:
    _p(course_id, SHEET).write_text(body, encoding="utf-8")


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


def quiz_sets(course_id: str) -> List[dict]:
    """Les series de QCM d'un cours.

    La premiere vient de exercises.json, produite avec le cours ; les suivantes
    vivent dans quizzes.json, pour ne pas toucher au fichier d'origine.
    """
    sets: List[dict] = []
    base = read_exercises(course_id)
    if base and base.get("qcm"):
        sets.append({"id": "1", "title": "Série 1", "qcm": base["qcm"]})
    extra = read_json(course_id, QUIZZES) or {}
    for item in extra.get("sets", []):
        if item.get("qcm"):
            sets.append({"id": str(item.get("id") or len(sets) + 1),
                         "title": item.get("title") or "Série %d" % (len(sets) + 1),
                         "qcm": item["qcm"]})
    return sets


def next_quiz_set_id(course_id: str) -> str:
    return str(len(quiz_sets(course_id)) + 1)


def add_quiz_set(course_id: str, qcm: List[dict], title: Optional[str] = None) -> str:
    extra = read_json(course_id, QUIZZES) or {"sets": []}
    extra.setdefault("sets", [])
    set_id = next_quiz_set_id(course_id)
    extra["sets"].append({
        "id": set_id,
        "title": title or "Série %s" % set_id,
        "created_at": time.time(),
        "qcm": qcm,
    })
    write_json(course_id, QUIZZES, extra)
    return set_id


def delete_quiz_set(course_id: str, set_id: str) -> bool:
    if set_id == "1":
        return False
    extra = read_json(course_id, QUIZZES) or {"sets": []}
    before = len(extra.get("sets", []))
    extra["sets"] = [s for s in extra.get("sets", []) if str(s.get("id")) != str(set_id)]
    write_json(course_id, QUIZZES, extra)
    return len(extra["sets"]) < before


def question_ids(course_id: str) -> set:
    """Identifiants des questions actuellement proposees, toutes series."""
    return {q["id"] for q in all_questions(course_id) if q.get("id")}


def largest_set_size(course_id: str) -> int:
    sizes = [len(item["qcm"]) for item in quiz_sets(course_id)]
    return max(sizes) if sizes else 0


def all_questions(course_id: str) -> List[dict]:
    out: List[dict] = []
    for item in quiz_sets(course_id):
        out.extend(item["qcm"])
    return out


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
# Dans une formule, « $\sum_{i<j}$ » ou « $u_{n+1}<u_n$ » : pour le navigateur,
# « <j » ou « <u » ouvre une balise, qui avale le texte jusqu'au prochain « > ».
# On neutralise donc, a l'affichage, tout « < » de formule qui n'est pas une
# vraie balise. KaTeX lit le texte decode : il voit toujours « < ».
_SCRIPT_BLOCK = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>)", re.S | re.I)
_MATH_SPAN = re.compile(
    r"\$\$.+?\$\$|\\\[.+?\\\]|\\\(.+?\\\)|(?<![\\$])\$(?!\$).+?(?<![\\$])\$", re.S)
_NOT_A_TAG = re.compile(
    r"<(?!!--|/?[a-zA-Z][a-zA-Z0-9-]*"
    r"""(?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*\s*/?>)""")


def _escape_math_lt(match) -> str:
    return _NOT_A_TAG.sub("&lt;", match.group(0))


def protect_math(text: str) -> str:
    """Neutralise les « < » des formules qui ressembleraient a une balise."""
    if not text or "<" not in text or ("$" not in text and "\\" not in text):
        return text
    parts = _SCRIPT_BLOCK.split(text)
    for i in range(0, len(parts), 2):
        if "<" in parts[i]:
            parts[i] = _MATH_SPAN.sub(_escape_math_lt, parts[i])
    return "".join(parts)


def protect_math_data(value):
    """Meme traitement sur toutes les chaines d'une structure JSON."""
    if isinstance(value, str):
        return protect_math(value)
    if isinstance(value, list):
        return [protect_math_data(v) for v in value]
    if isinstance(value, dict):
        return {k: protect_math_data(v) for k, v in value.items()}
    return value


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
            .replace("__BODY__", protect_math(body)))


def with_quiz_progress(page: str, progress: dict, course_id: Optional[str]) -> str:
    """Page de QCM : y joint les tentatives en cours ({set_id: etat}), lues
    par quiz.html avant son script principal."""
    data = json.dumps(progress or {}, ensure_ascii=False).replace("</", "<\\/")
    script = ("<script>window.QUIZ_PROGRESS = %s; window.QUIZ_COURSE = %s;</script>\n"
              % (data, json.dumps(course_id)))
    return page.replace("</head>", script + "</head>", 1)


def render_course_page(course_id: str, title: str, theme: str = "light") -> pathlib.Path:
    """Ecrit la page complete du cours et retourne son chemin."""
    from .questions import link_courses
    from .syllabus import load
    page = build_page(link_courses(read_body(course_id), load()), title, theme)
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


def generation_estimate() -> tuple[float, float]:
    """Durée et coût moyens d'un cours, mesurés sur ce qui a déjà été généré.

    Sans historique, on prend des valeurs prudentes tirées des premiers cours
    produits avec Opus : environ vingt minutes et cinq dollars.
    """
    from .paths import library_dir
    durations, costs = [], []
    for d in library_dir().iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        meta = read_meta(d.name)
        if meta.get("duration_s") and meta.get("cost_usd"):
            durations.append(float(meta["duration_s"]))
            costs.append(float(meta["cost_usd"]))
    if not durations:
        return 1200.0, 5.0
    return sum(durations) / len(durations), sum(costs) / len(costs)


# ------------------------------------------------------------------ substance
_BOX_RE = re.compile(
    r'<div class="box (definition|theorem|proposition|lemma|corollary|recap|warning|pitfall|intuition)"[^>]*>(.*?)</div>\s*(?=<(?:h[1-4]|p|div|details|ul|ol|table|hr|figure|script)\b|$)',
    re.S | re.I)
_HEAD_RE = re.compile(r"<(h2|h3)[^>]*>(.*?)</\1>", re.S | re.I)
_PROOF_OF_RE = re.compile(r'<details class="proof"[^>]*data-of="([^"]*)"', re.I)
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.S)

# Ce qu'on garde en priorite quand il faut couper : les enonces avant le reste.
_BOX_PRIORITY = {
    "definition": 0, "theorem": 1, "proposition": 1, "lemma": 2, "corollary": 2,
    "recap": 3, "warning": 4, "pitfall": 4, "intuition": 5,
}
_BOX_LABEL = {
    "definition": "DEFINITION", "theorem": "THEOREME", "proposition": "PROPOSITION",
    "lemma": "LEMME", "corollary": "COROLLAIRE", "recap": "A RETENIR",
    "warning": "PIEGE", "pitfall": "PIEGE", "intuition": "INTUITION",
}


def _plain(html_text: str, keep_math: bool = True) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"</(p|li|div|h[1-4])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def substance(course_id: str, limit: int = 34000) -> str:
    """La matiere du cours : enonces, resultats, pieges, formules centrees.

    Sert a produire la fiche de revision. Contrairement a `digest`, qui donne un
    apercu, on veut ici le texte complet des encadres : c'est la substance a
    condenser, et la tronquer produirait une fiche qui invente.
    """
    body = read_body(course_id)
    body = re.sub(r"<script\b.*?</script>", " ", body, flags=re.S | re.I)

    pieces = []          # (priorite, position, texte)
    for match in _HEAD_RE.finditer(body):
        title = _plain(match.group(2))
        if title:
            level = "##" if match.group(1).lower() == "h2" else "###"
            pieces.append((-1, match.start(), "\n%s %s" % (level, title)))
    for match in _BOX_RE.finditer(body):
        kind = match.group(1).lower()
        text = _plain(match.group(2))
        if not text:
            continue
        text = re.sub(r"^(Définition|Théorème|Proposition|Lemme|Corollaire|"
                      r"À retenir|Piège classique|L'idée)\s*", "", text)
        pieces.append((_BOX_PRIORITY.get(kind, 6), match.start(),
                       "[%s] %s" % (_BOX_LABEL.get(kind, kind.upper()), text)))

    proved = _PROOF_OF_RE.findall(body)
    if proved:
        pieces.append((3, len(body), "[DEMONTRE DANS LE COURS] "
                       + " ; ".join(dict.fromkeys(proved))))

    # on coupe par ordre d'importance, puis on restitue l'ordre de lecture
    pieces.sort(key=lambda t: (t[0], t[1]))
    kept, total = [], 0
    for priority, position, text in pieces:
        if total + len(text) > limit:
            continue
        kept.append((position, text))
        total += len(text)
    kept.sort()
    return "\n".join(text for _pos, text in kept)


def render_sheet_page(course_id: str, title: str, theme: str = "light",
                      for_print: bool = False) -> pathlib.Path:
    """Assemble la fiche de revision et retourne le chemin de la page."""
    template = (ASSETS_DIR / "sheet_template.html").read_text(encoding="utf-8")
    page = (template
            .replace("__THEME__", "light" if for_print else theme)
            .replace("__TITLE__", html.escape(title))
            .replace("__ASSETS__", assets_url())
            .replace("__CLASS__", "print" if for_print else "screen")
            .replace("__BODY__", protect_math(read_sheet(course_id))))
    out = course_dir(course_id) / ("_sheet_print.html" if for_print else "_sheet.html")
    out.write_text(page, encoding="utf-8")
    return out


_TITLED_BOX_RE = re.compile(
    r'<div class="box (definition|theorem|proposition|lemma|corollary)"[^>]*>\s*'
    r'<span class="box-title">(.*?)</span>(.*?)(?=<div class="box|<h[23]|<details|$)',
    re.S | re.I)
_FIRST_BOLD_RE = re.compile(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>", re.S | re.I)


def section_items(html_text: str, limit: int = 14) -> List[str]:
    """Les notions qu'une section a effectivement introduites.

    Sert a dire aux sections suivantes ce qui est deja acquis : sans cela,
    chacune reintroduit les memes definitions, puisqu'elles sont redigees en
    parallele et ne voient que les titres des autres.
    """
    items: List[str] = []
    for kind, box_title, body in _TITLED_BOX_RE.findall(html_text):
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", box_title)).strip()
        name = ""
        bold = _FIRST_BOLD_RE.search(body)
        if bold:
            name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", bold.group(1))).strip(" .:")
        if not name:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
            name = text[:70].rsplit(" ", 1)[0] if len(text) > 70 else text
        if not name:
            continue
        items.append("%s : %s" % (label, name) if label.lower() not in name.lower() else name)
    for proved in _PROOF_OF_RE.findall(html_text):
        items.append("démontré : %s" % proved.strip())
    seen, out = set(), []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:limit]


# --------------------------------------------------------- quiz du jour
def daily_path(day: str) -> pathlib.Path:
    from .paths import daily_dir
    return daily_dir() / ("%s.json" % day)


def read_daily(day: str) -> Optional[dict]:
    path = daily_path(day)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_daily(day: str, data: dict) -> None:
    daily_path(day).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")


def has_daily(day: str) -> bool:
    data = read_daily(day)
    return bool(data and data.get("qcm"))


def daily_days() -> List[str]:
    from .paths import daily_dir
    return sorted(p.stem for p in daily_dir().glob("*.json"))


def question_index() -> dict:
    """{(course_id, set_id, question_id): question} sur tout le contenu.

    Inclut les quiz du jour : leurs questions entrent aussi dans le cycle de
    revision, et il faut pouvoir les retrouver plus tard.
    """
    from .paths import library_dir
    index = {}
    for d in library_dir().iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        for item in quiz_sets(d.name):
            for q in item["qcm"]:
                index[(d.name, item["id"], q["id"])] = q
    for day in daily_days():
        data = read_daily(day) or {}
        for q in data.get("qcm", []):
            index[(q.get("course_id", ""), "daily", q["id"])] = q
    for day, course_id in refreshers():
        data = read_refresher(day, course_id) or {}
        for q in data.get("qcm", []):
            index[(course_id, "rappel", q["id"])] = q
    return index


# --------------------------------------------------------- rappels ciblés
def refresher_path(day: str, course_id: str) -> pathlib.Path:
    from .paths import refresher_dir
    return refresher_dir() / ("%s_%s.json" % (day, course_id))


def read_refresher(day: str, course_id: str) -> Optional[dict]:
    path = refresher_path(day, course_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_refresher(day: str, course_id: str, data: dict) -> None:
    refresher_path(day, course_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def refreshers() -> List[tuple]:
    """[(jour, cours)] de tous les rappels produits, du plus ancien au plus récent."""
    from .paths import refresher_dir
    out = []
    for p in sorted(refresher_dir().glob("*.json")):
        day, _, course_id = p.stem.partition("_")
        if len(day) == 10 and course_id:
            out.append((day, course_id))
    return out


def pending_refresher(day: str) -> Optional[str]:
    """Cours d'un rappel prêt ce jour-là et pas encore fait."""
    for d, course_id in refreshers():
        if d != day:
            continue
        data = read_refresher(d, course_id) or {}
        if data.get("qcm") and not data.get("done_at"):
            return course_id
    return None


def mark_refresher_done(day: str, course_id: str) -> None:
    data = read_refresher(day, course_id)
    if data is not None:
        data["done_at"] = time.time()
        write_refresher(day, course_id, data)
