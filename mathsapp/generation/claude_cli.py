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
import signal
import subprocess
import tempfile
import threading
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
    "silence",   # coupure detectee par le chien de garde
)


def is_transient(message: str) -> bool:
    low = (message or "").lower()
    return any(token in low for token in TRANSIENT)


def transient_reason(message: str) -> str:
    """Nature d'un echec transitoire, en clair, pour expliquer une pause."""
    low = (message or "").lower()
    if any(t in low for t in ("rate limit", "429", "overloaded")):
        return "limite de débit de l'API"
    if "silence" in low:
        return "appel resté muet"
    if any(t in low for t in ("500", "502", "503", "504", "internal server",
                              "service unavailable", "temporarily")):
        return "service indisponible"
    return "erreur réseau"


@dataclass
class Result:
    text: str
    cost_usd: float = 0.0
    duration_s: float = 0.0
    session_id: Optional[str] = None
    model: str = ""
    raw: dict = field(default_factory=dict)


def backend() -> str:
    """Moteur de generation : `claude` ou `codex`.

    En mode `auto` (defaut), c'est le CLI installe sur la machine : claude s'il
    est la, sinon codex. L'application marche ainsi sans reglage chez quelqu'un
    qui n'a que l'un des deux.
    """
    name = str(settings.get("gen/backend") or "auto").strip().lower()
    if name in ("claude", "codex"):
        return name
    if shutil.which(str(settings.get("claude/binary") or "claude")) or \
            os.path.exists(os.path.expanduser("~/.local/bin/claude")):
        return "claude"
    if shutil.which(str(settings.get("codex/binary") or "codex")):
        return "codex"
    return "claude"


def uses_tools() -> bool:
    """Le moteur sait-il lire un PDF lui-meme ? Sinon on lui donne le texte."""
    return backend() == "claude"


def binary(override: Optional[str] = None) -> str:
    exe = override or settings.get("claude/binary") or "claude"
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


def check_available(override: Optional[str] = None) -> str:
    """Retourne la version du CLI du moteur courant, ou leve ClaudeError."""
    if backend() == "codex":
        from . import codex_cli
        return codex_cli.check_available(override)
    try:
        out = subprocess.run([binary(override), "--version"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError("Impossible de lancer `claude` : %s" % exc) from exc
    if out.returncode != 0:
        raise ClaudeError("`claude --version` a echoue : %s" % (out.stderr or out.stdout))
    return out.stdout.strip()


def _base_cmd(model: str, system: Optional[str], persist: bool,
              exe: Optional[str] = None, tools: str = "",
              add_dirs: Iterable[str] = ()) -> List[str]:
    """Commande de base. Par defaut aucun outil : la generation n'a pas besoin
    du disque. `tools="Read"` et `add_dirs` ouvrent la lecture d'un dossier
    precis, par exemple pour lire un sujet de TD en PDF avec ses formules."""
    cmd = [binary(exe), "-p", "--model", model, "--safe-mode", "--tools", tools]
    for directory in add_dirs:
        cmd += ["--add-dir", str(directory)]
    if not persist:
        cmd.append("--no-session-persistence")
    if system:
        cmd += ["--system-prompt", system]
    return cmd


def _kill_tree(proc: subprocess.Popen) -> None:
    """Tue l'appel et toute sa descendance.

    Tuer le seul processus lance ne suffit pas : un enfant qui survit garde le
    tuyau de sortie ouvert, on n'atteint jamais la fin de flux et la lecture
    bloque indefiniment. On lance donc chaque appel dans sa propre session et
    on tue le groupe entier.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def kill_tree(proc: subprocess.Popen) -> None:
    """Meme chose, sous un nom utilisable par les autres moteurs."""
    _kill_tree(proc)


def _neutral_cwd() -> str:
    """Repertoire de travail neutre : pas de CLAUDE.md ni de settings de projet."""
    d = os.path.join(tempfile.gettempdir(), "mathsapp-claude-cwd")
    os.makedirs(d, exist_ok=True)
    return d


def neutral_cwd() -> str:
    return _neutral_cwd()


# --------------------------------------------------------------- appel simple
def run(prompt: str, model: str, system: Optional[str] = None,
        json_schema: Optional[dict] = None,
        timeout: Optional[int] = None,
        cancel: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        on_notice: Optional[Callable[[str], None]] = None,
        retries: Optional[int] = None,
        exe: Optional[str] = None,
        stall_timeout: Optional[float] = None,
        tools: str = "",
        add_dirs: Iterable[str] = (),
        cwd: Optional[str] = None) -> Result:
    """Lance une generation, en reessayant les echecs transitoires.

    Une coupure reseau ne doit pas perdre le travail deja fait : on attend et
    on relance le meme appel. `on_notice` sert a le dire dans l'interface.
    """
    attempts = max(1, int(retries if retries is not None else (settings.get("claude/retries") or 3)))
    delays = [10, 30, 90, 180]
    last: Optional[ClaudeError] = None
    for attempt in range(attempts):
        try:
            return _run_once(prompt, model, system, json_schema, timeout, cancel,
                             on_progress, exe, stall_timeout, tools, add_dirs, cwd)
        except Cancelled:
            raise
        except ClaudeError as exc:
            last = exc
            if attempt == attempts - 1 or not is_transient(str(exc)):
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            if on_notice is not None:
                on_notice("%s, nouvelle tentative dans %d s (essai %d/%d) · %s"
                          % (transient_reason(str(exc)), delay, attempt + 2, attempts,
                             " ".join(str(exc).split())[:160]))
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
              on_progress: Optional[Callable[[int], None]] = None,
              exe: Optional[str] = None,
              stall_timeout: Optional[float] = None,
              tools: str = "",
              add_dirs: Iterable[str] = (),
              cwd: Optional[str] = None) -> Result:
    """Un seul appel au CLI.

    `exe` et `stall_timeout` permettent de viser un binaire precis sans toucher
    aux preferences : ces dernieres sont partagees avec l'application, et les
    modifier depuis un test interromprait une generation en cours.
    """
    if backend() == "codex":
        from . import codex_cli
        return codex_cli.run_once(prompt, model, system, json_schema, timeout, cancel,
                                  on_progress, exe, stall_timeout, tools, add_dirs, cwd)
    timeout = int(timeout or settings.get("claude/timeout") or 1800)
    cmd = _base_cmd(model, system, persist=False, exe=exe, tools=tools, add_dirs=add_dirs)
    cmd += ["--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
    cmd.append(prompt)

    chunks: List[str] = []
    result_obj: dict = {}
    proc = subprocess.Popen(
        cmd, cwd=cwd or _neutral_cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, start_new_session=True,
    )

    # Le flux peut se taire sans que le process meure (coupure reseau silencieuse).
    # Un fil de surveillance tue l'appel apres un silence trop long, ce qui le
    # transforme en echec transitoire donc en nouvelle tentative. Il rend aussi
    # l'annulation reactive : sans lui, `cancel` n'etait consulte qu'a l'arrivee
    # d'une ligne, donc jamais pendant un blocage.
    stall_limit = float(stall_timeout if stall_timeout is not None
                        else (settings.get("claude/stall_timeout") or 240))
    last_seen = [time.time()]
    stalled = [False]
    stop_watch = threading.Event()

    def watchdog() -> None:
        while not stop_watch.wait(2.0):
            if proc.poll() is not None:
                return
            if cancel is not None and cancel():
                _kill_tree(proc)
                return
            if time.time() - last_seen[0] > stall_limit:
                stalled[0] = True
                _kill_tree(proc)
                return

    watcher = threading.Thread(target=watchdog, daemon=True)
    watcher.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            last_seen[0] = time.time()
            if cancel is not None and cancel():
                _kill_tree(proc)
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
        _kill_tree(proc)
        raise ClaudeError("Délai dépassé (%ss)." % timeout) from exc
    finally:
        stop_watch.set()
        _kill_tree(proc)

    if stalled[0]:
        raise ClaudeError(
            "Aucune réponse pendant %d s : silence du flux, appel interrompu."
            % int(stall_limit))
    if cancel is not None and cancel():
        raise Cancelled("Génération annulée.")

    stderr = (proc.stderr.read() if proc.stderr else "") or ""
    text = "".join(chunks).strip()
    # Avec des outils, le flux contient aussi les messages intermediaires
    # (« je lis les pages 5 a 20 ») : seule la reponse finale compte.
    if tools and (result_obj.get("result") or "").strip():
        text = result_obj["result"].strip()
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
                timeout: int = 900,
                history: Iterable[dict] = ()) -> Result:
    """Un tour de conversation en streaming.

    Si `session_id` est fourni, la conversation precedente est reprise (le
    contexte est conserve cote CLI). Sinon un nouvel identifiant est cree.
    `history` ne sert qu'aux moteurs sans sessions, comme codex.
    """
    if backend() == "codex":
        from . import codex_cli
        return codex_cli.chat_stream(prompt, model, system, session_id, on_delta,
                                     cancel, timeout, history)
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
        text=True, bufsize=1, start_new_session=True,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel():
                _kill_tree(proc)
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
        _kill_tree(proc)
        raise ClaudeError("Délai dépassé.") from exc
    finally:
        _kill_tree(proc)

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
