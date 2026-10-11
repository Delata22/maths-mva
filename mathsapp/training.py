"""TD d'entraînement : feuilles d'exercices de rédaction générées pour un cours.

À ne pas confondre avec les « TD importés » (mathsapp/td.py), corrections de
sujets fournis par l'utilisateur. Ici, chaque feuille est produite à la
demande à partir d'un cours rédigé.

Les feuilles vivent dans library/<cours>/entrainement/td-<n>.json. Ce
sous-dossier survit à la régénération du cours (content.delete_course ne vide
que les fichiers du dossier et sections/) : une feuille écrite pour une version
antérieure est conservée et signalée comme telle.
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import time
from typing import List, Optional

from . import content
from .paths import course_dir

FOLDER = "entrainement"

LEVELS = ("application", "classique", "approfondissement")
LEVEL_LABEL = {
    "application": "Application directe",
    "classique": "Classique",
    "approfondissement": "Approfondissement",
}
STATUS_LABEL = {"ok": "Réussi", "partial": "Partiellement", "review": "À revoir"}

# Sans historique : un appel au modèle des exercices, environ 25 000 caractères.
DEFAULT_ESTIMATE = (180.0, 0.35)


def training_dir(course_id: str, create: bool = False) -> pathlib.Path:
    d = course_dir(course_id, create=create) / FOLDER
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _path(course_id: str, td_id: int) -> pathlib.Path:
    return training_dir(course_id) / ("td-%d.json" % int(td_id))


def course_version(course_id: str) -> float:
    """Version du cours rédigé : la date de sa dernière génération complète."""
    try:
        return float(content.read_meta(course_id).get("generated_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def list_tds(course_id: str) -> List[dict]:
    """Les feuilles complètes d'un cours, TD 1, TD 2… dans l'ordre."""
    d = training_dir(course_id)
    if not d.is_dir():
        return []
    out = []
    for p in d.glob("td-*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("exercises"):
            out.append(data)
    out.sort(key=lambda t: int(t.get("id") or 0))
    return out


def read_td(course_id: str, td_id: int) -> Optional[dict]:
    for td in list_tds(course_id):
        if int(td.get("id") or 0) == int(td_id):
            return td
    return None


def is_outdated(td: dict, course_id: str) -> bool:
    """Feuille écrite pour une version antérieure du cours."""
    version = course_version(course_id)
    return bool(version) and abs(float(td.get("course_version") or 0) - version) > 1e-3


def normalize_exercises(raw: dict, section_titles: List[str]) -> List[dict]:
    """Nettoie la réponse du modèle : niveaux, indices, renvoi de section vérifié."""
    known = {t.strip().lower(): t for t in section_titles if t}
    items = []
    for ex in (raw or {}).get("exercises") or []:
        if not isinstance(ex, dict):
            continue
        statement = str(ex.get("statement") or "").strip()
        solution = str(ex.get("solution") or "").strip()
        if not statement or not solution:
            continue
        level = str(ex.get("level") or "").lower()
        if "appli" in level or "direct" in level:
            level = "application"
        elif "approf" in level or "difficile" in level:
            level = "approfondissement"
        else:
            level = "classique"
        hints = [str(h).strip() for h in (ex.get("hints") or []) if str(h).strip()][:2]
        section = known.get(str(ex.get("section") or "").strip().lower(), "")
        items.append({
            "level": level,
            "title": str(ex.get("title") or "").strip(),
            "statement": content.clean_html(statement),
            "hints": [content.clean_html(h) for h in hints],
            "solution": content.clean_html(solution),
            "section": section,
        })
    # difficulté croissante, en gardant l'ordre du modèle à niveau égal
    items.sort(key=lambda e: LEVELS.index(e["level"]))
    for i, ex in enumerate(items, 1):
        ex["id"] = "e%d" % i
    return items


def save(course_id: str, exercises: List[dict], replace: Optional[int] = None,
         **meta) -> int:
    """Écrit une feuille complète, d'un bloc. Retourne son numéro.

    L'écriture passe par un fichier temporaire : une génération interrompue ne
    laisse jamais de feuille partielle qui passerait pour complète."""
    from . import store
    existing = [int(t.get("id") or 0) for t in list_tds(course_id)]
    td_id = int(replace) if replace else (max(existing) + 1 if existing else 1)
    data = {"id": td_id, "created_at": time.time(),
            "course_version": course_version(course_id), "exercises": exercises}
    data.update(meta)
    d = training_dir(course_id, create=True)
    tmp = d / ("td-%d.json.tmp" % td_id)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _path(course_id, td_id))
    if replace:
        # d'autres exercices : l'ancien suivi ne veut plus rien dire
        store.clear_training_status(course_id, str(td_id))
    return td_id


def delete(course_id: str, td_id: int) -> bool:
    from . import store
    p = _path(course_id, td_id)
    if not p.exists():
        return False
    p.unlink()
    store.clear_training_status(course_id, str(int(td_id)))
    return True


def estimate() -> tuple:
    """(durée en s, coût en $) d'une feuille, d'après les feuilles déjà produites."""
    from .paths import library_dir
    durations, costs = [], []
    for d in library_dir().iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        for td in list_tds(d.name):
            if td.get("duration_s"):
                durations.append(float(td["duration_s"]))
                costs.append(float(td.get("cost_usd") or 0))
    if not durations:
        return DEFAULT_ESTIMATE
    return sum(durations) / len(durations), sum(costs) / len(costs)


# ------------------------------------------------------------------- rendu
PAGE_CSS = """
.training-tools { display:flex; gap:8px; margin:-4px 0 14px; }
.training-tools button, .training-status button {
  font: 600 12.5px ui-sans-serif, system-ui, sans-serif; padding:5px 12px;
  border-radius:8px; border:1px solid var(--line-strong); background:var(--bg-soft);
  color:var(--fg); cursor:pointer; }
.training-tools button:hover, .training-status button:hover { border-color:var(--accent); }
.training-status { display:flex; gap:6px; align-items:center; margin:4px 0 12px;
  font: 12.5px ui-sans-serif, system-ui, sans-serif; color:var(--muted); }
.training-status button.on[data-status="ok"] { background:var(--ok); border-color:var(--ok); color:#fff; }
.training-status button.on[data-status="partial"] { background:var(--warn); border-color:var(--warn); color:#fff; }
.training-status button.on[data-status="review"] { background:var(--err, #c0392b); border-color:var(--err, #c0392b); color:#fff; }
.training-ex { margin:0 0 30px; padding-bottom:12px; border-bottom:1px solid var(--line); }
.training-ex details { margin:8px 0; border:1px solid var(--line); border-radius:9px;
  padding:8px 13px; background:var(--bg-soft); }
.training-ex details > summary { cursor:pointer; font: 600 13px ui-sans-serif, system-ui, sans-serif; }
.training-ref { font-size:.92em; color:var(--muted); }
.training-empty { color:var(--muted); }
"""


def _date(ts: float) -> str:
    return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else ""


def page_body(course_id: str, statuses: dict) -> str:
    """Toutes les feuilles du cours en une page, indices et corrigés repliés."""
    tds = list_tds(course_id)
    esc = html.escape
    out = ["<h1>TD d'entraînement</h1>"]
    if not tds:
        out.append("<p class=\"training-empty\">Aucun TD d'entraînement pour ce cours. "
                   "Le bouton « Générer un TD » en produit une feuille de 5 à 8 exercices "
                   "de rédaction, de difficulté croissante, avec indices et corrigés.</p>")
        return "\n".join(out)
    out.append("<p class=\"lead\">Exercices de rédaction, du plus direct au plus "
               "approfondi. Cherchez d'abord ; les indices et le corrigé se déplient un "
               "par un.</p>")
    for td in tds:
        tid = int(td.get("id") or 0)
        out.append("<h2 id=\"td-%d\">TD %d — %s</h2>" % (tid, tid, _date(td.get("created_at") or 0)))
        out.append("<div class=\"training-tools\">"
                   "<button data-act=\"regenerate\" data-td=\"%d\">Régénérer</button>"
                   "<button data-act=\"delete\" data-td=\"%d\">Supprimer</button></div>"
                   % (tid, tid))
        if is_outdated(td, course_id):
            out.append("<div class=\"box warning\"><span class=\"box-title\">Version "
                       "antérieure du cours</span><p>Ce TD a été écrit pour une version "
                       "antérieure du cours, régénéré depuis. Les notations ou les renvois "
                       "aux sections peuvent ne plus correspondre : « Régénérer » en produit "
                       "une version alignée sur le cours actuel.</p></div>")
        for n, ex in enumerate(td.get("exercises") or [], 1):
            key = "%d/%s" % (tid, ex.get("id"))
            current = statuses.get(key, "")
            title = ex.get("title") or ""
            out.append("<div class=\"training-ex\" id=\"td-%d-%s\">" % (tid, esc(str(ex.get("id")))))
            out.append("<h3>Exercice %d%s <span class=\"badge\">%s</span></h3>"
                       % (n, (" — " + title) if title else "",
                          LEVEL_LABEL.get(ex.get("level"), "Classique")))
            buttons = "".join(
                "<button data-key=\"%s\" data-status=\"%s\"%s>%s</button>"
                % (key, value, " class=\"on\"" if value == current else "", label)
                for value, label in STATUS_LABEL.items())
            out.append("<div class=\"training-status\">Mon résultat : %s</div>" % buttons)
            out.append("<div class=\"training-statement\">%s</div>" % ex.get("statement", ""))
            if ex.get("section"):
                out.append("<p class=\"training-ref\">Voir dans le cours : "
                           "<a class=\"course-ref\" data-course=\"%s\" data-section=\"%s\">%s</a></p>"
                           % (esc(course_id, quote=True), esc(ex["section"], quote=True),
                              esc(ex["section"])))
            for k, hint in enumerate(ex.get("hints") or [], 1):
                out.append("<details class=\"training-hint\"><summary>Indice %d</summary>%s</details>"
                           % (k, hint))
            out.append("<details class=\"training-solution\"><summary>Corrigé</summary>%s</details>"
                       % ex.get("solution", ""))
            out.append("</div>")
    out.append(_SCRIPT)
    return "\n".join(out)


_SCRIPT = """<script>
document.addEventListener('click', function (ev) {
  var b = ev.target && ev.target.closest ? ev.target.closest('button[data-status], button[data-act]') : null;
  if (!b || !window.app) return;
  ev.preventDefault();
  if (b.hasAttribute('data-act')) {
    window.app.trainingAction(b.getAttribute('data-act'), b.getAttribute('data-td'));
    return;
  }
  var key = b.getAttribute('data-key'), value = b.getAttribute('data-status');
  var on = b.classList.contains('on');
  Array.prototype.forEach.call(b.parentNode.querySelectorAll('button'), function (x) {
    x.classList.remove('on');
  });
  if (!on) b.classList.add('on');
  window.app.setTrainingStatus(key, on ? '' : value);
});
</script>"""
