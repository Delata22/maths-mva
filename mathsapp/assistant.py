"""Assistant de l'application : piloter l'app et la modifier depuis le chat.

Deux registres :
- les actions sur l'application (générer des cours, une fiche, corriger un TD,
  régler un paramètre…) : Claude les propose dans un bloc <actions>, l'app les
  affiche en cartes et ne les exécute qu'au clic ;
- les modifications du code : un appel `claude` limité aux outils d'édition,
  dans le dossier du projet, suivi des tests et d'un commit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from . import content, settings, td as td_mod
from .paths import PROJECT_ROOT
from .syllabus import Syllabus

MODELS = ["opus", "sonnet", "haiku"]
SETTINGS_ALLOWED: Dict[str, tuple] = {
    "model/course": ("choice", MODELS),
    "model/exercises": ("choice", MODELS),
    "model/chat": ("choice", MODELS),
    "model/sheet": ("choice", MODELS),
    "gen/concurrency": ("int", 1, 4),
    "gen/section_parallel": ("int", 1, 6),
    "gen/max_sections": ("int", 4, 14),
    "gen/auto_sheet": ("bool",),
    "ui/mastery_threshold": ("int", 50, 100),
    "goal/bricks": ("int", 1, 5),
    "goal/review_batch": ("int", 5, 60),
}
PAGES = {"home": "l'accueil", "library": "la bibliothèque", "graph": "le graphe",
         "td": "les TD", "course": "le cours"}
SESSIONS = {"review": "les révisions du jour", "daily": "le quiz du jour",
            "challenge": "un défi éclair"}


# ------------------------------------------------------------------ état
def app_state(syl: Syllabus, statuses: dict, jobs=()) -> str:
    """Photographie compacte de l'application, donnée à Claude à chaque tour."""
    per_course_s, per_course_cost = content.generation_estimate()
    lines = ["COURS (id | titre | niveau | rédaction | progression | prérequis)"]
    by_domain: Dict[str, list] = {}
    for course in syl.all():
        by_domain.setdefault(course.domain, []).append(course)
    for did in syl.domain_order:
        courses = by_domain.get(did) or []
        if not courses:
            continue
        lines.append("## %s [%s]" % (syl.domain_name(did), did))
        for c in courses:
            s = statuses.get(c.id)
            if s is None:
                continue
            if s.complete:
                redaction = "rédigé"
            elif s.partial:
                redaction = "interrompu %d/%d" % (s.sections_done, s.sections_total)
            else:
                redaction = "non généré"
            if s.mastered:
                progress = "maîtrisé (%s %%)" % s.score_pct
            elif s.score_pct is not None:
                progress = "score %d %% sur %d questions" % (s.score_pct, s.answered)
            else:
                progress = "—"
            lines.append("- %s | %s | %d | %s | %s | %s" % (
                c.id, c.title, c.level, redaction, progress, ", ".join(c.prereqs) or "—"))

    lines.append("\nPARCOURS (id : titre)")
    for track in syl.tracks.values():
        lines.append("- %s : %s" % (track.id, track.title))

    tds = td_mod.list_ids()
    lines.append("\nTD IMPORTÉS")
    for tid in tds:
        st = td_mod.state(tid)
        lines.append("- %s : %s — %s" % (
            tid, td_mod.title(tid),
            "%d/%d exercices corrigés" % (st["corrected"], st["total"])
            if st["structured"] else "sujet pas encore lu"))
        linked: Dict[str, int] = {}
        for ex in td_mod.exercises(tid):
            for cid in ex.get("courses") or []:
                linked[cid] = linked.get(cid, 0) + 1
        if linked:
            lines.append("  cours utilisés (nombre d'exercices) : %s" % ", ".join(
                "%s (%d)" % (cid, n) for cid, n in sorted(linked.items(), key=lambda kv: -kv[1])))
    if not tds:
        lines.append("- (aucun)")

    lines.append("\n" + queue_state(syl, statuses, jobs))

    lines.append("\nRÉGLAGES MODIFIABLES")
    for key in SETTINGS_ALLOWED:
        lines.append("- %s = %s" % (key, settings.get(key)))

    lines.append("\nCOÛT MOYEN D'UN COURS COMPLET : environ %d min et %.2f $ "
                 "(d'après les générations passées)." % (per_course_s / 60, per_course_cost))
    return "\n".join(lines)


QUEUE_MAX_ITEMS = 15


def _clock(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "—"


def queue_state(syl: Syllabus, statuses: dict, jobs=(), now: Optional[float] = None,
                limit: Optional[int] = None) -> str:
    """Section FILE DE GÉNÉRATION : statut, avancement, horodatages et raison de
    chaque attente ou pause. Reconstruite à chaque message de l'utilisateur."""
    from .generation import queue as queue_mod
    now = time.time() if now is None else now
    if limit is None:
        limit = max(1, min(4, int(settings.get("gen/concurrency") or 1)))
    jobs = list(jobs)
    running = sum(1 for j in jobs if j.state == queue_mod.RUNNING)
    recent = [j for j in jobs if j.active
              or now - (j.finished_at or j.last_activity) < queue_mod.RECENT_AFTER]
    rank = {queue_mod.RUNNING: 0, queue_mod.QUEUED: 1, queue_mod.ERROR: 2,
            queue_mod.CANCELLED: 3, queue_mod.DONE: 4}
    recent.sort(key=lambda j: rank.get(j.state, 5))
    lines = ["FILE DE GÉNÉRATION (état à %s ; %d en cours, limite gen/concurrency = %d ; "
             "statut | avancement | ajouté, démarré, dernière progression | raison)"
             % (_clock(now), running, limit)]
    if not recent:
        lines.append("- file vide : aucune génération en cours, en attente ni récente")
    active_ids = {j.course_id for j in jobs if j.active}
    for j in recent[:QUEUE_MAX_ITEMS]:
        status, reason = queue_mod.explain(j, running, limit, now)
        progress = "%d %%" % int(j.progress * 100)
        s = statuses.get(j.course_id)
        if s is not None and j.kind in ("course", "regenerate") and s.sections_total:
            progress += ", %d/%d sections" % (s.sections_done, s.sections_total)
        if j.state == queue_mod.QUEUED and j.course_id in syl.courses:
            waiting = [p for p in syl.get(j.course_id).prereqs if p in active_ids]
            if waiting:
                # la file n'attend pas les prérequis : on le signale seulement
                reason += (" ; prérequis du même lot encore en file : %s "
                           "(la file ne les attend pas)" % ", ".join(waiting))
        line = "- [%s] %s (%s) : %s | %s | %s, %s, %s" % (
            j.kind, j.course_id, j.title, status, progress, _clock(j.queued_at),
            _clock(j.started_at), _clock(j.last_activity))
        if reason:
            line += " | %s" % reason
        if j.active and j.label:
            line += " | étape : %s" % j.label.split(" · ")[0][:120]
        if j.last_notice and j.state != queue_mod.ERROR:
            line += " | dernier message d'erreur : %s" % j.last_notice[:200]
        lines.append(line)
    if len(recent) > QUEUE_MAX_ITEMS:
        lines.append("- … et %d autres éléments non détaillés" % (len(recent) - QUEUE_MAX_ITEMS))

    paused = [cid for cid in syl.order
              if statuses.get(cid) is not None and statuses[cid].partial
              and cid not in active_ids]
    if paused:
        lines.append("Cours interrompus sans génération active (« Incomplet » dans la "
                     "bibliothèque) :")
        for cid in paused[:QUEUE_MAX_ITEMS]:
            s = statuses[cid]
            lines.append("- %s : %d/%d sections | %s" % (
                cid, s.sections_done, s.sections_total, queue_mod.pause_reason(jobs, cid)))
        if len(paused) > QUEUE_MAX_ITEMS:
            lines.append("- … et %d autres cours interrompus" % (len(paused) - QUEUE_MAX_ITEMS))
    return "\n".join(lines)


# ---------------------------------------------------------------- actions
_BLOCK = re.compile(r"<actions>\s*(.*?)\s*(?:</actions>|$)", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def resolve_course(ref, syl: Syllabus) -> Optional[str]:
    """Un identifiant exact, sinon un titre ou un identifiant approché sans ambiguïté."""
    ref = str(ref or "").strip()
    if ref in syl.courses:
        return ref
    slug = _slug(ref)
    if not slug:
        return None
    exact = [c.id for c in syl.all() if _slug(c.title) == slug or _slug(c.id) == slug]
    if len(exact) == 1:
        return exact[0]
    near = [c.id for c in syl.all() if slug in _slug(c.title) or slug in c.id]
    return near[0] if len(near) == 1 else None


def visible_limit(raw: str) -> int:
    """Jusqu'où afficher un flux en cours sans montrer le bloc <actions>."""
    cut = raw.find("<actions")
    if cut >= 0:
        return cut
    tag = "<actions"
    for k in range(min(len(tag) - 1, len(raw)), 0, -1):
        if raw.endswith(tag[:k]):
            return len(raw) - k
    return len(raw)


def split_answer(text: str) -> Tuple[str, list]:
    """Sépare la réponse visible du bloc d'actions brut (liste de dicts)."""
    m = _BLOCK.search(text)
    if not m:
        return text, []
    visible = (text[:m.start()] + text[m.end():]).strip()
    raw = _FENCE.sub("", m.group(1).strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return visible, []
    if isinstance(data, dict):
        data = data.get("actions") or [data]
    return visible, [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _course_list(value, syl: Syllabus) -> Tuple[List[str], List[str]]:
    if isinstance(value, str):
        value = [value]
    found, unknown = [], []
    for ref in value or []:
        cid = resolve_course(ref, syl)
        if cid is None:
            unknown.append(str(ref))
        elif cid not in found:
            found.append(cid)
    rank = {cid: i for i, cid in enumerate(syl.topo)}
    found.sort(key=lambda cid: rank.get(cid, 0))
    return found, unknown


def _cast_setting(key: str, value):
    spec = SETTINGS_ALLOWED.get(key)
    if spec is None:
        return None
    if spec[0] == "choice":
        value = str(value).strip().lower()
        return value if value in spec[1] else None
    if spec[0] == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "oui", "vrai", "yes")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if spec[1] <= number <= spec[2] else None


def normalize_action(raw: dict, syl: Syllabus, statuses: Optional[dict] = None) -> Optional[dict]:
    """Valide une action proposée et lui donne un intitulé lisible. None si inutilisable."""
    kind = str(raw.get("type") or "").strip()
    out = {"id": uuid.uuid4().hex[:8], "type": kind}
    per_course_s, per_course_cost = content.generation_estimate()

    if kind == "generate_courses":
        ids, unknown = _course_list(raw.get("courses"), syl)
        done = [cid for cid in ids if content.is_complete(cid)]
        todo = [cid for cid in ids if cid not in done]
        if not todo:
            return None
        detail = ", ".join(syl.title(cid) for cid in todo)
        detail += "  ·  environ %d min et %.0f $ au total" % (
            len(todo) * per_course_s / 60, len(todo) * per_course_cost)
        if done:
            detail += "  ·  déjà rédigés, ignorés : %s" % ", ".join(syl.title(c) for c in done)
        if unknown:
            detail += "  ·  introuvables : %s" % ", ".join(unknown)
        out.update(courses=todo, costly=True,
                   label="Générer %d cours" % len(todo) if len(todo) > 1
                   else "Générer « %s »" % syl.title(todo[0]), detail=detail)
        return out

    if kind in ("regenerate_course", "new_quiz_set"):
        cid = resolve_course(raw.get("course"), syl)
        if cid is None or not content.has_course(cid):
            return None
        if kind == "regenerate_course":
            out.update(label="Régénérer « %s »" % syl.title(cid), costly=True,
                       detail="Nouveau plan, nouveau texte et nouveaux exercices ; "
                              "scores et notes conservés. Environ %.0f $." % per_course_cost)
        else:
            out.update(label="Nouvelle série de QCM : « %s »" % syl.title(cid), costly=True,
                       detail="Environ deux minutes et quelques centimes.")
        out["course"] = cid
        return out

    if kind == "generate_sheets":
        ids, _unknown = _course_list(raw.get("courses"), syl)
        todo = [cid for cid in ids if content.has_course(cid) and not content.has_sheet(cid)]
        if not todo:
            return None
        out.update(courses=todo, costly=True,
                   label="Fiches de révision : %d cours" % len(todo),
                   detail="%s  ·  environ 0,20 $ par fiche"
                          % ", ".join(syl.title(cid) for cid in todo))
        return out

    if kind == "correct_td":
        tid = str(raw.get("td") or "").strip()
        if tid not in td_mod.list_ids():
            return None
        st = td_mod.state(tid)
        if st["complete"]:
            return None
        out.update(td=tid, costly=True, label="Corriger le TD « %s »" % td_mod.title(tid),
                   detail="%d exercices restants" % (st["total"] - st["corrected"])
                   if st["structured"] else "Lecture du sujet puis correction")
        return out

    if kind == "extend_syllabus":
        request = str(raw.get("request") or "").strip()
        if len(request) < 5:
            return None
        try:
            count = max(3, min(24, int(raw.get("count") or 8)))
        except (TypeError, ValueError):
            count = 8
        out.update(request=request, count=count, costly=True,
                   label="Étendre le syllabus (%d cours)" % count, detail=request)
        return out

    if kind == "set_setting":
        key = str(raw.get("key") or "").strip()
        value = _cast_setting(key, raw.get("value"))
        if value is None:
            return None
        out.update(key=key, value=value, label="Réglage : %s → %s" % (key, value),
                   detail="actuellement %s" % settings.get(key))
        return out

    if kind == "cancel_generation":
        if raw.get("all"):
            out.update(all=True, courses=[], label="Arrêter toutes les générations", detail="")
            return out
        ids, _unknown = _course_list(raw.get("courses"), syl)
        if not ids:
            return None
        out.update(all=False, courses=ids, label="Arrêter %d génération%s"
                   % (len(ids), "s" if len(ids) > 1 else ""),
                   detail=", ".join(syl.title(cid) for cid in ids))
        return out

    if kind == "open":
        page = str(raw.get("page") or "").strip()
        if page not in PAGES:
            return None
        cid = resolve_course(raw.get("course"), syl) if page == "course" else None
        if page == "course" and cid is None:
            return None
        out.update(page=page, course=cid, detail="",
                   label="Ouvrir « %s »" % syl.title(cid) if cid else "Ouvrir %s" % PAGES[page])
        return out

    if kind == "start_session":
        session = str(raw.get("kind") or "").strip()
        if session not in SESSIONS:
            return None
        out.update(kind=session, label="Lancer %s" % SESSIONS[session], detail="")
        return out

    if kind == "modify_app":
        request = str(raw.get("request") or "").strip()
        if len(request) < 10:
            return None
        out.update(request=request, costly=True,
                   label="Modifier l'application",
                   detail=str(raw.get("summary") or request)[:400])
        return out
    return None


def parse_actions(text: str, syl: Syllabus) -> Tuple[str, List[dict]]:
    visible, raw = split_answer(text)
    actions = [a for a in (normalize_action(r, syl) for r in raw[:8]) if a]
    return visible, actions


# -------------------------------------------------------------- git
def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(PROJECT_ROOT), capture_output=True,
                          text=True, timeout=timeout)


def git_status() -> Tuple[List[str], List[str]]:
    """(fichiers suivis modifiés, fichiers non suivis)."""
    res = _git("status", "--porcelain")
    tracked, untracked = [], []
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        (untracked if line.startswith("??") else tracked).append(path)
    return tracked, untracked


def discard_changes(tracked: List[str], created: List[str]) -> None:
    if tracked:
        _git("checkout", "--", *tracked)
    for rel in created:
        path = PROJECT_ROOT / rel
        if path.is_file():
            path.unlink()


def commit_changes(files: List[str], message: str) -> str:
    _git("add", "--", *files)
    res = _git("commit", "-q", "-m", message)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[:400])
    sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
    try:
        _git("push", "-q", timeout=90)
    except subprocess.TimeoutExpired:
        pass
    return sha


def revert_commit(sha: str) -> str:
    res = _git("revert", "--no-edit", sha)
    if res.returncode != 0:
        _git("revert", "--abort")
        raise RuntimeError((res.stderr or res.stdout).strip()[:400])
    try:
        _git("push", "-q", timeout=90)
    except subprocess.TimeoutExpired:
        pass
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


_SUMMARY = re.compile(r"(\d+) verifications, (\d+) echec")


def run_selftest(timeout: int = 1200) -> Tuple[bool, str]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        res = subprocess.run([sys.executable, "tools/selftest.py"], cwd=str(PROJECT_ROOT),
                             capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, "Les tests ont dépassé %d s." % timeout
    output = res.stdout + res.stderr
    m = _SUMMARY.search(output)
    ok = res.returncode == 0 and bool(m) and m.group(2) == "0"
    if ok:
        return True, "%s vérifications, aucun échec" % m.group(1)
    failures = [l for l in output.splitlines()
                if "ECHEC" in l or "Error" in l or "Traceback" in l or l.startswith("  File")]
    tail = "\n".join(output.strip().splitlines()[-25:])
    return False, "\n".join(failures[:30]) + "\n---\n" + tail


# ------------------------------------------------------ modification du code
class CodeChangeWorker(QThread):
    """Fait modifier le code par Claude, lance les tests, committe si tout passe."""

    activity = Signal(str)
    done = Signal(dict)

    MAX_FIX_ROUNDS = 2

    def __init__(self, request: str, parent=None, title: str = ""):
        super().__init__(parent)
        self.request = request
        self.title = title
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None

    def request_stop(self) -> None:
        self._stop = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, 15)
            except OSError:
                pass

    # -- un tour de Claude, outils d'édition seulement
    def _claude(self, prompt: str, session: str, resume: bool) -> Tuple[str, float]:
        from .generation import prompts
        exe = str(settings.get("claude/binary") or "claude")
        cmd = [exe, "-p", "--model", str(settings.get("model/chat") or "opus"),
               "--safe-mode", "--tools", "Read,Edit,Write,Glob,Grep",
               "--permission-mode", "acceptEdits",
               "--system-prompt", prompts.code_change_system(),
               "--output-format", "stream-json", "--verbose"]
        cmd += ["--resume", session] if resume else ["--session-id", session]
        cmd.append(prompt)
        self._proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, bufsize=1,
                                      start_new_session=True)
        killer = threading.Timer(2400, self.request_stop)
        killer.start()
        final, cost = "", 0.0
        seen_tools = set()
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        # un meme appel d'outil peut revenir dans plusieurs messages
                        if block.get("type") == "tool_use" and block.get("id") not in seen_tools:
                            seen_tools.add(block.get("id"))
                            self.activity.emit(_describe_tool(block))
                elif obj.get("type") == "result":
                    final = obj.get("result") or ""
                    cost = float(obj.get("total_cost_usd") or 0.0)
            self._proc.wait(timeout=30)
        finally:
            killer.cancel()
            if self._proc.poll() is None:
                self.request_stop()
        if self._stop:
            raise InterruptedError("Modification interrompue.")
        if not final:
            err = (self._proc.stderr.read() if self._proc.stderr else "")[:300]
            raise RuntimeError("Claude n'a pas répondu. %s" % err)
        return final, cost

    def run(self) -> None:
        result = {"ok": False, "request": self.request, "files": [], "created": [],
                  "tracked": [], "summary": "", "tests": "", "commit": "", "cost": 0.0}
        try:
            tracked, untracked_before = git_status()
            if tracked:
                result["error"] = ("Des modifications non enregistrées existent déjà dans le "
                                   "code (%s). Enregistrez-les ou annulez-les d'abord."
                                   % ", ".join(tracked[:5]))
                self.done.emit(result)
                return
            from .generation import prompts
            session = str(uuid.uuid4())
            self.activity.emit("Claude lit le code et prépare la modification…")
            summary, cost = self._claude(prompts.code_change_prompt(self.request), session, False)
            result["summary"], result["cost"] = summary, cost

            rounds = 0
            while True:
                tracked, untracked = git_status()
                created = [p for p in untracked if p not in untracked_before]
                result.update(tracked=tracked, created=created, files=tracked + created)
                if not result["files"]:
                    result["error"] = "Aucun fichier n'a été modifié."
                    break
                self.activity.emit("Tests de l'application (deux à trois minutes)…")
                ok, report = run_selftest()
                result["tests"] = report
                if ok:
                    message = ("assistant: %s\n\n%s\n\nCo-Authored-By: Claude Opus 5 "
                               "<noreply@anthropic.com>"
                               % (_subject(self.title or self.request),
                                  re.sub(r"<[^>]+>", "", summary).strip()[:1500]))
                    result["commit"] = commit_changes(result["files"], message)
                    result["ok"] = True
                    break
                if rounds >= self.MAX_FIX_ROUNDS:
                    break
                rounds += 1
                self.activity.emit("Des tests échouent : Claude corrige (tour %d/%d)…"
                                   % (rounds, self.MAX_FIX_ROUNDS))
                summary, extra = self._claude(prompts.code_fix_prompt(report), session, True)
                result["summary"] = summary
                result["cost"] += extra
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
            tracked, untracked = git_status()
            result.update(tracked=tracked, files=tracked)
        self.done.emit(result)


def _subject(text: str, width: int = 68) -> str:
    """Titre de commit : première ligne, coupée à un mot entier."""
    line = re.sub(r"\s+", " ", text.strip().splitlines()[0] if text.strip() else "modification")
    if len(line) <= width:
        return line
    return line[:width].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _describe_tool(block: dict) -> str:
    name = block.get("name", "")
    data = block.get("input") or {}
    path = str(data.get("file_path") or data.get("path") or data.get("pattern") or "")
    if path.startswith("/"):
        # chemins resolus des deux cotes : /tmp ou le dossier personnel peuvent
        # etre des liens symboliques
        root = os.path.realpath(str(PROJECT_ROOT))
        real = os.path.realpath(path)
        if real == root or real.startswith(root + os.sep):
            path = os.path.relpath(real, root)
    verb = {"Read": "Lecture", "Edit": "Modification", "Write": "Écriture",
            "Glob": "Recherche de fichiers", "Grep": "Recherche"}.get(name, name)
    return "%s : %s" % (verb, path) if path else verb
