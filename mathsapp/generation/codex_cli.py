"""Moteur Codex : le CLI `codex` à la place de `claude`.

Même contrat que `claude_cli` (mêmes signatures, même `Result`), pour que le
reste de l'application ne sache pas quel moteur tourne. Les différences :

- pas d'option de prompt système : les consignes sont mises en tête du prompt ;
- pas de sessions reprises : l'historique du fil est renvoyé à chaque tour ;
- pas de lecture de PDF : l'application en extrait le texte elle-même
  (voir `mathsapp.pdf_text`) et le met dans le prompt ;
- le coût en dollars n'est pas renvoyé par le CLI : il reste à zéro.

Les options du CLI changent d'une version à l'autre : celles qui ne sont pas
indispensables sont retirées et l'appel rejoué si `codex` les refuse.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Callable, Iterable, List, Optional, Tuple

from .. import settings
from .claude_cli import Cancelled, ClaudeError, Result, kill_tree, neutral_cwd

# Options confortables mais facultatives, retirées si le CLI ne les connaît pas.
OPTIONAL_FLAGS = ["--output-schema", "--output-last-message", "--json",
                  "--skip-git-repo-check", "--cd", "--sandbox"]
_UNSUPPORTED = re.compile(
    r"unexpected argument|unrecognized|unknown (?:option|flag|argument|command)|"
    r"invalid (?:option|value)|no such option", re.I)


def binary(override: Optional[str] = None) -> str:
    exe = override or settings.get("codex/binary") or "codex"
    found = shutil.which(exe)
    if found:
        return found
    for candidate in (os.path.expanduser("~/.local/bin/codex"),
                      os.path.expanduser("~/.npm-global/bin/codex"),
                      "/usr/local/bin/codex"):
        if os.path.exists(candidate):
            return candidate
    raise ClaudeError(
        "Le CLI `codex` est introuvable. Installez-le (npm i -g @openai/codex) "
        "ou renseignez son chemin dans Préférences > Génération.")


def check_available(override: Optional[str] = None) -> str:
    try:
        out = subprocess.run([binary(override), "--version"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError("Impossible de lancer `codex` : %s" % exc) from exc
    if out.returncode != 0:
        raise ClaudeError("`codex --version` a échoué : %s" % (out.stderr or out.stdout))
    return out.stdout.strip()


def model_for(model: str) -> str:
    """Traduit les noms de modèles de l'application, nommés à la Claude.

    Vide = on laisse Codex utiliser le modèle configuré chez l'utilisateur.
    """
    alias = str(model or "").strip().lower()
    if alias in ("opus", "sonnet", "haiku"):
        key = "codex/model_strong" if alias == "opus" else "codex/model_fast"
        return str(settings.get(key) or "").strip()
    return str(model or "").strip()


def strict_schema(schema: dict) -> dict:
    """Schéma JSON accepté en sortie structurée : tout est requis et fermé."""
    def walk(node):
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items()}
            if out.get("type") == "object" and isinstance(out.get("properties"), dict):
                out.setdefault("additionalProperties", False)
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    return walk(copy.deepcopy(schema))


def with_system(prompt: str, system: Optional[str]) -> str:
    if not system:
        return prompt
    return ("CONSIGNES PERMANENTES\n%s\n\n"
            "----------------------------------------------------------------\n\n"
            "%s" % (system, prompt))


def transcript(history: Iterable[dict], prompt: str) -> str:
    """Codex ne reprend pas une session : on lui rend la conversation."""
    turns = []
    for message in history or []:
        role = "Question" if message.get("role") == "user" else "Votre réponse"
        content = str(message.get("content") or "").strip()
        if content:
            turns.append("### %s\n%s" % (role, content))
    # le dernier tour est la question posée maintenant : elle est donnée à part
    while turns and turns[-1].startswith("### Question") and \
            turns[-1][len("### Question\n"):].strip() == prompt.strip():
        turns.pop()
    if not turns:
        return prompt
    return ("CONVERSATION EN COURS, pour le contexte :\n\n%s\n\n"
            "----------------------------------------------------------------\n\n"
            "NOUVELLE QUESTION :\n%s" % ("\n\n".join(turns[-20:]), prompt))


def _cmd(exe: Optional[str], model: str, cwd: str, last_file: str,
         schema_file: Optional[str], prompt: str) -> List[str]:
    cmd = [binary(exe), "exec", "--json", "--skip-git-repo-check",
           "--sandbox", str(settings.get("codex/sandbox") or "read-only"),
           "--cd", cwd, "--output-last-message", last_file]
    if schema_file:
        cmd += ["--output-schema", schema_file]
    name = model_for(model)
    if name:
        cmd += ["--model", name]
    cmd.append(prompt)
    return cmd


def drop_flag(cmd: List[str], flag: str) -> List[str]:
    """Retire une option et sa valeur éventuelle."""
    if flag not in cmd:
        return cmd
    i = cmd.index(flag)
    takes_value = flag in ("--output-schema", "--output-last-message", "--cd",
                           "--sandbox", "--model")
    end = i + (2 if takes_value and i + 1 < len(cmd) else 1)
    return cmd[:i] + cmd[end:]


def unsupported_flag(cmd: List[str], stderr: str) -> Optional[str]:
    """L'option refusée par cette version du CLI, s'il y en a une."""
    if not _UNSUPPORTED.search(stderr or ""):
        return None
    for flag in OPTIONAL_FLAGS:
        if flag in cmd and flag.lstrip("-") in (stderr or "").lower():
            return flag
    for flag in OPTIONAL_FLAGS:
        if flag in cmd:
            return flag
    return None


def message_text(obj: dict) -> Tuple[str, bool]:
    """(texte, est_un_fragment) d'un évènement du flux, sinon ("", False).

    La forme des évènements change selon la version : on cible les messages de
    l'agent et on ignore le raisonnement.
    """
    if not isinstance(obj, dict):
        return "", False
    node = obj.get("msg") if isinstance(obj.get("msg"), dict) else obj
    kind = str(node.get("type") or obj.get("type") or "")
    low = kind.lower()
    if "reasoning" in low or "token_count" in low:
        return "", False
    if "agent_message" in low or "output_text" in low or "assistant" in low:
        for key in ("delta", "text", "message", "content"):
            value = node.get(key)
            if isinstance(value, str) and value:
                return value, ("delta" in low or key == "delta")
            if isinstance(value, dict):
                inner = value.get("text") or value.get("delta")
                if isinstance(inner, str) and inner:
                    return inner, ("delta" in low or "delta" in value)
    item = node.get("item")
    if isinstance(item, dict):
        return message_text({"msg": item})
    return "", False


def _stream(cmd: List[str], cwd: str, timeout: int,
            cancel: Optional[Callable[[], bool]],
            stall_limit: float,
            on_piece: Optional[Callable[[str], None]]) -> dict:
    """Lance l'appel et suit son flux. Même surveillance que pour `claude`."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, start_new_session=True)
    deltas: List[str] = []
    messages: List[str] = []
    session_id: Optional[str] = None
    last_seen = [time.time()]
    stalled = [False]
    stop_watch = threading.Event()

    def watchdog() -> None:
        while not stop_watch.wait(2.0):
            if proc.poll() is not None:
                return
            if cancel is not None and cancel():
                kill_tree(proc)
                return
            if time.time() - last_seen[0] > stall_limit:
                stalled[0] = True
                kill_tree(proc)
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            last_seen[0] = time.time()
            if cancel is not None and cancel():
                kill_tree(proc)
                raise Cancelled("Génération annulée.")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                session_id = session_id or obj.get("session_id") or obj.get("id")
            piece, is_delta = message_text(obj)
            if not piece:
                continue
            if is_delta:
                deltas.append(piece)
                if on_piece is not None:
                    on_piece(piece)
            else:
                messages.append(piece)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        kill_tree(proc)
        raise ClaudeError("Délai dépassé (%ss)." % timeout) from exc
    finally:
        stop_watch.set()
        kill_tree(proc)

    if stalled[0]:
        raise ClaudeError("Aucune réponse pendant %d s : silence du flux, appel interrompu."
                          % int(stall_limit))
    return {"deltas": deltas, "messages": messages, "session_id": session_id,
            "code": proc.returncode,
            "stderr": (proc.stderr.read() if proc.stderr else "") or ""}


def _final_text(outcome: dict, last_file: str) -> str:
    try:
        text = open(last_file, encoding="utf-8").read().strip() if os.path.exists(last_file) else ""
    except OSError:
        text = ""
    if text:
        return text
    if outcome["messages"]:
        return outcome["messages"][-1].strip()
    return "".join(outcome["deltas"]).strip()


def run_once(prompt: str, model: str, system: Optional[str] = None,
             json_schema: Optional[dict] = None,
             timeout: Optional[int] = None,
             cancel: Optional[Callable[[], bool]] = None,
             on_progress: Optional[Callable[[int], None]] = None,
             exe: Optional[str] = None,
             stall_timeout: Optional[float] = None,
             tools: str = "",
             add_dirs: Iterable[str] = (),
             cwd: Optional[str] = None) -> Result:
    timeout = int(timeout or settings.get("claude/timeout") or 1800)
    stall_limit = float(stall_timeout if stall_timeout is not None
                        else (settings.get("claude/stall_timeout") or 240))
    folder = tempfile.mkdtemp(prefix="mathsapp-codex-")
    last_file = os.path.join(folder, "reponse.txt")
    schema_file = None
    if json_schema is not None:
        schema_file = os.path.join(folder, "schema.json")
        with open(schema_file, "w", encoding="utf-8") as fh:
            json.dump(strict_schema(json_schema), fh, ensure_ascii=False)

    seen = [0]

    def piece(text: str) -> None:
        seen[0] += len(text)
        if on_progress is not None:
            on_progress(seen[0])

    work_dir = cwd or neutral_cwd()
    cmd = _cmd(exe, model, work_dir, last_file, schema_file, with_system(prompt, system))
    try:
        return _run_with_fallback(cmd, work_dir, timeout, cancel, stall_limit, piece,
                                  last_file, model, json_schema)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _run_with_fallback(cmd, work_dir, timeout, cancel, stall_limit, piece,
                       last_file, model, json_schema) -> Result:
    outcome = {"code": None, "stderr": ""}
    for _attempt in range(len(OPTIONAL_FLAGS) + 1):
        outcome = _stream(cmd, work_dir, timeout, cancel, stall_limit, piece)
        text = _final_text(outcome, last_file)
        if outcome["code"] in (0, None) and text:
            return Result(text=text, cost_usd=0.0,
                          session_id=outcome["session_id"], model=model,
                          raw={"backend": "codex"})
        flag = unsupported_flag(cmd, outcome["stderr"])
        if flag is None:
            break
        cmd = drop_flag(cmd, flag)
        if flag == "--output-schema" and json_schema is not None:
            # sans sortie structuree, on redemande le JSON dans le prompt
            cmd[-1] = cmd[-1] + ("\n\nRépondez UNIQUEMENT par un objet JSON valide "
                                 "conforme à ce schéma :\n%s"
                                 % json.dumps(json_schema, ensure_ascii=False))
    raise ClaudeError("Échec de l'appel à codex (code %s) : %s"
                      % (outcome["code"], (outcome["stderr"] or "sortie vide")[:600]))


def chat_stream(prompt: str, model: str, system: Optional[str],
                session_id: Optional[str],
                on_delta: Callable[[str], None],
                cancel: Optional[Callable[[], bool]] = None,
                timeout: int = 900,
                history: Iterable[dict] = (),
                exe: Optional[str] = None) -> Result:
    folder = tempfile.mkdtemp(prefix="mathsapp-codex-")
    last_file = os.path.join(folder, "reponse.txt")
    work_dir = neutral_cwd()
    full = with_system(transcript(history, prompt), system)
    cmd = _cmd(exe, model, work_dir, last_file, None, full)
    try:
        outcome = _stream(cmd, work_dir, timeout, cancel, 600.0, on_delta)
        text = _final_text(outcome, last_file)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not text:
        raise ClaudeError("Pas de réponse. %s" % (outcome["stderr"] or "")[:300])
    return Result(text=text, cost_usd=0.0,
                  session_id=session_id or outcome["session_id"] or str(uuid.uuid4()),
                  model=model, raw={"backend": "codex"})
