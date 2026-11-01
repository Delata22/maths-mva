"""Conversation avec Claude, en streaming, dans un thread Qt."""
from __future__ import annotations

import html as html_mod
import re
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import settings, store
from .generation import claude_cli as cc
from .generation.prompts import chat_system, proof_helper_system, proof_review_system
from .syllabus import Course, Syllabus


class ChatWorker(QThread):
    delta = Signal(str)
    finished_ok = Signal(str, str)      # texte complet, session_id
    failed = Signal(str)

    def __init__(self, prompt: str, model: str, system: str,
                 session_id: Optional[str], parent=None, history=()):
        super().__init__(parent)
        self.prompt = prompt
        self.model = model
        self.system = system
        self.session_id = session_id
        # les moteurs sans sessions (codex) recoivent la conversation a chaque tour
        self.history = list(history)
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            res = cc.chat_stream(
                self.prompt, self.model, self.system, self.session_id,
                on_delta=self.delta.emit, cancel=lambda: self._stop,
                history=self.history,
            )
            self.finished_ok.emit(res.text, res.session_id or "")
        except cc.ClaudeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("%s : %s" % (type(exc).__name__, exc))


_FENCE = re.compile(r"^\s*```(?:html)?\s*\n|\n\s*```\s*$")


def clean_answer(text: str) -> str:
    out = _FENCE.sub("", text.strip())
    if "<" not in out:
        parts = [p.strip() for p in out.split("\n\n") if p.strip()]
        return "".join("<p>%s</p>" % html_mod.escape(p).replace("\n", "<br>") for p in parts)
    return out


class ChatSession:
    """Un fil de discussion persistant, identifie par (cours, contexte)."""

    def __init__(self, course: Optional[Course], syl: Optional[Syllabus],
                 context_key: str = "general", mode: str = "general"):
        self.course = course
        self.syl = syl
        self.context_key = context_key
        self.mode = mode
        self.state_provider = None     # assistant : etat de l'app, relu a chaque tour
        self.queue_provider = None     # assistant : file de generation, jointe a chaque message
        course_id = course.id if course else None
        row = store.find_thread(course_id, context_key)
        if row is None:
            title = course.title if course else "Discussion générale"
            self.thread_id = store.create_thread(course_id, context_key, title)
            self.session_id: Optional[str] = None
        else:
            self.thread_id = int(row["id"])
            self.session_id = row["session_id"]

    @property
    def system(self) -> str:
        if self.mode == "proof":
            return proof_helper_system(self.course, self.syl)
        if self.mode == "review":
            return proof_review_system(self.course, self.syl, "complete")
        if self.mode == "review-etape":
            return proof_review_system(self.course, self.syl, "etape")
        if self.mode == "question":
            from .generation.prompts import question_system
            from .questions import catalogue
            return question_system(catalogue(self.syl), self.syl)
        if self.mode == "assistant":
            from .generation.prompts import assistant_system
            return assistant_system(self.state_provider() if self.state_provider else "")
        return chat_system(self.course, self.syl)

    def turn_prompt(self, prompt: str) -> str:
        """Message envoye a Claude. Pour l'assistant, l'etat de la file est joint
        a chaque message : une conversation reprise garde sinon en memoire les
        etats des tours precedents, et l'assistant se fie a une file perimee."""
        if self.mode != "assistant" or not self.queue_provider:
            return prompt
        return ("<etat_a_jour>\nÉtat actuel de l'application, qui remplace tout état "
                "donné plus tôt dans la conversation :\n%s\n</etat_a_jour>\n\n%s"
                % (self.queue_provider(), prompt))

    @property
    def model(self) -> str:
        return str(settings.get("model/chat"))

    def history(self):
        return store.messages(self.thread_id)

    def record_user(self, text: str) -> None:
        if self.mode == "question" and not store.messages(self.thread_id):
            store.set_thread_title(self.thread_id, " ".join(text.split())[:120])
        store.add_message(self.thread_id, "user", text)

    def record_assistant(self, text: str, session_id: str, actions=()) -> int:
        """Enregistre la réponse et ses cartes d'action (état « proposée »)."""
        message_id = store.add_message(self.thread_id, "assistant", text)
        if actions:
            store.add_chat_actions(self.thread_id, message_id, list(actions))
        if session_id:
            self.session_id = session_id
            store.set_thread_session(self.thread_id, session_id)
        return message_id

    def actions(self):
        """Cartes d'action du fil, par identifiant de message."""
        return store.chat_actions(self.thread_id)

    def reset(self) -> None:
        store.clear_thread(self.thread_id)
        self.session_id = None
