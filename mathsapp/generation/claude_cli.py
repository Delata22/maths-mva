"""Enveloppe autour du CLI `claude` local.

Toutes les generations passent par ici. On lance `claude` en mode print, sans
outils et en `--safe-mode` : la generation de cours n'a besoin d'aucun acces au
disque, et on evite ainsi que les hooks / CLAUDE.md de l'utilisateur viennent
polluer les reponses.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from .. import settings


class ClaudeError(RuntimeError):
    pass


class Cancelled(ClaudeError):
    """L'utilisateur a demande l'arret : on ne reessaie pas."""


# Erreurs qui valent la peine d'etre reessayees : une coupure reseau de
# quelques secondes ne doit pas tuer une generation de vingt minutes.
TRANSIENT = (
    "network", "reseau", "econnreset", "enotfound", "eai_again", "etimedout",
    "socket", "connection", "connexion", "timeout", "delai", "fetch failed",
    "overloaded", "rate limit", "429", "500", "502", "503", "504",
    "internal server", "service unavailable", "temporarily",
)


def is_transient(message: str) -> bool:
    low = (message or "").lower()
    return any(token in low for token in TRANSIENT)


@dataclass
class Result:
    text: str
    cost_usd: float = 0.0
    duration_s: float = 0.0
    session_id: Optional[str] = None
    model: str = ""
    raw: dict = field(default_factory=dict)


def binary() -> str:
    exe = settings.get("claude/binary") or "claude"
    found = shutil.which(exe)
    if found:
        return found
    for candidate in (os.path.expanduser("~/.local/bin/claude"), "/usr/local/bin/claude"):
        if os.path.exists(candidate):
            return candidate
    raise ClaudeError(
        "Le CLI `claude` est introuvable. Installez-le ou renseignez son chemin "
        "dans Préférences > Modèles."
    )


def check_available() -> str:
    """Retourne la version du CLI, ou leve ClaudeError."""
    try:
        out = subprocess.run([binary(), "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError("Impossible de lancer `claude` : %s" % exc) from exc
    if out.returncode != 0:
        raise ClaudeError("`claude --version` a echoue : %s" % (out.stderr or out.stdout))
    return out.stdout.strip()


def _base_cmd(model: str, system: Optional[str], persist: bool) -> List[str]:
    cmd = [binary(), "-p", "--model", model, "--safe-mode", "--tools", ""]
    if not persist:
        cmd.append("--no-session-persistence")
    if system:
        cmd += ["--system-prompt", system]
    return cmd


def _neutral_cwd() -> str:
    """Repertoire de travail neutre : pas de CLAUDE.md ni de settings de projet."""
    d = os.path.join(tempfile.gettempdir(), "mathsapp-claude-cwd")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------- appel simple
def run(prompt: str, model: str, system: Optional[str] = None,
        json_schema: Optional[dict] = None,
        timeout: Optional[int] = None,
        cancel: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        on_notice: Optional[Callable[[str], None]] = None,
        retries: Optional[int] = None) -> Result:
    """Lance une generation, en reessayant les echecs transitoires.

    Une coupure reseau ne doit pas perdre le travail deja fait : on attend et
    on relance le meme appel. `on_notice` sert a le dire dans l'interface.
    """
    attempts = max(1, int(retries if retries is not None else (settings.get("claude/retries") or 3)))
    delays = [10, 30, 90, 180]
    last: Optional[ClaudeError] = None
    for attempt in range(attempts):
        try:
            return _run_once(prompt, model, system, json_schema, timeout, cancel, on_progress)
        except Cancelled:
            raise
        except ClaudeError as exc:
            last = exc
            if attempt == attempts - 1 or not is_transient(str(exc)):
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            if on_notice is not None:
                on_notice("connexion perdue, nouvelle tentative dans %d s "
                          "(essai %d/%d)" % (delay, attempt + 2, attempts))
            waited = 0.0
            while waited < delay:
                if cancel is not None and cancel():
                    raise Cancelled("Génération annulée.")
                time.sleep(0.5)
                waited += 0.5
    raise last if last else ClaudeError("Échec inattendu.")


def _run_once(prompt: str, model: str, system: Optional[str] = None,
              json_schema: Optional[dict] = None,
              timeout: Optional[int] = None,
              cancel: Optional[Callable[[], bool]] = None,
              on_progress: Optional[Callable[[int], None]] = None) -> Result:
    """Un seul appel au CLI."""
    timeout = int(timeout or settings.get("claude/timeout") or 1800)
    cmd = _base_cmd(model, system, persist=False)
    cmd += ["--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
    cmd.append(prompt)

    chunks: List[str] = []
    result_obj: dict = {}
    proc = subprocess.Popen(
        cmd, cwd=_neutral_cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel():
                proc.kill()
                raise Cancelled("Génération annulée.")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = obj.get("type")
            if kind == "stream_event":
                event = obj.get("event", {})
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        chunks.append(delta.get("text", ""))
                        if on_progress is not None:
                            on_progress(sum(len(c) for c in chunks))
            elif kind == "result":
                result_obj = obj
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise ClaudeError("Délai dépassé (%ss)." % timeout) from exc
    finally:
        if proc.poll() is None:
            proc.kill()

    stderr = (proc.stderr.read() if proc.stderr else "") or ""
    text = "".join(chunks).strip()
    if not text:
        text = (result_obj.get("result") or "").strip()
    if result_obj.get("is_error") or (proc.returncode not in (0, None) and not text):
        raise ClaudeError(
            "Echec de l'appel a claude (code %s) : %s"
            % (proc.returncode, (result_obj.get("result") or stderr or "sortie vide")[:600])
        )
    if not text:
        raise ClaudeError("Le modèle n'a rien renvoyé. %s" % stderr[:300])

    return Result(
        text=text,
        cost_usd=float(result_obj.get("total_cost_usd") or 0.0),
        duration_s=float(result_obj.get("duration_ms") or 0.0) / 1000.0,
        session_id=result_obj.get("session_id"),
        model=model,
        raw=result_obj,
    )


# ------------------------------------------------------------------ JSON util
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extract_json(text: str):
    """Recupere un objet JSON dans une reponse, meme entouree de texte."""
    candidate = _FENCE.sub("", text).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ClaudeError("Réponse JSON illisible : %s" % candidate[:400])


def run_json(prompt: str, model: str, system: Optional[str] = None,
             schema: Optional[dict] = None, **kwargs):
    res = run(prompt, model, system=system, json_schema=schema, **kwargs)
    return extract_json(res.text), res


def connectivity_hint(message: str) -> str:
    """Message d'aide quand l'echec ressemble a une coupure reseau."""
    if is_transient(message):
        return ("La connexion semble avoir ete perdue. Le travail deja fait est "
                "conserve : relancez la generation, elle reprendra ou elle s'est "
                "arretee.")
    return ""


# ----------------------------------------------------------------------- chat
def chat_stream(prompt: str, model: str, system: Optional[str],
                session_id: Optional[str],
                on_delta: Callable[[str], None],
                cancel: Optional[Callable[[], bool]] = None,
                timeout: int = 900) -> Result:
    """Un tour de conversation en streaming.

    Si `session_id` est fourni, la conversation precedente est reprise (le
    contexte est conserve cote CLI). Sinon un nouvel identifiant est cree.
    """
    new_session = session_id or str(uuid.uuid4())
    cmd = _base_cmd(model, system, persist=True)
    if session_id:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--session-id", new_session]
    cmd += ["--output-format", "stream-json", "--include-partial-messages", "--verbose", prompt]

    chunks: List[str] = []
    result_obj: dict = {}
    proc = subprocess.Popen(
        cmd, cwd=_neutral_cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel():
                proc.kill()
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "stream_event":
                event = obj.get("event", {})
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        piece = delta.get("text", "")
                        chunks.append(piece)
                        on_delta(piece)
            elif obj.get("type") == "result":
                result_obj = obj
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise ClaudeError("Délai dépassé.") from exc
    finally:
        if proc.poll() is None:
            proc.kill()

    text = "".join(chunks).strip() or (result_obj.get("result") or "").strip()
    if not text:
        stderr = (proc.stderr.read() if proc.stderr else "") or ""
        raise ClaudeError("Pas de réponse. %s" % stderr[:300])
    return Result(
        text=text,
        cost_usd=float(result_obj.get("total_cost_usd") or 0.0),
        session_id=result_obj.get("session_id") or new_session,
        model=model,
        raw=result_obj,
    )
