"""Conversation avec Claude, en streaming, dans un thread Qt."""
from __future__ import annotations

import html as html_mod
import re
from typing import Optional

from PySide6.QtCore import QThread, Signal

from . import settings, store
from .generation import claude_cli as cc
from .generation.prompts import chat_system, proof_helper_system
from .syllabus import Course, Syllabus


class ChatWorker(QThread):
    delta = Signal(str)
    finished_ok = Signal(str, str)      # texte complet, session_id
    failed = Signal(str)

    def __init__(self, prompt: str, model: str, system: str,
                 session_id: Optional[str], parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.model = model
        self.system = system
        self.session_id = session_id
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            res = cc.chat_stream(
                self.prompt, self.model, self.system, self.session_id,
                on_delta=self.delta.emit, cancel=lambda: self._stop,
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
                 context_key: str = "general", proof_mode: bool = False):
        self.course = course
        self.syl = syl
        self.context_key = context_key
        self.proof_mode = proof_mode
        course_id = course.id if course else None
        row = store.find_thread(course_id, context_key)
        if row is None:
            title = course.title if course else "Discussion generale"
            self.thread_id = store.create_thread(course_id, context_key, title)
            self.session_id: Optional[str] = None
        else:
            self.thread_id = int(row["id"])
            self.session_id = row["session_id"]

    @property
    def system(self) -> str:
        if self.proof_mode:
            return proof_helper_system(self.course, self.syl)
        return chat_system(self.course, self.syl)

    @property
    def model(self) -> str:
        return str(settings.get("model/chat"))

    def history(self):
        return store.messages(self.thread_id)

    def record_user(self, text: str) -> None:
        store.add_message(self.thread_id, "user", text)

    def record_assistant(self, text: str, session_id: str) -> None:
        store.add_message(self.thread_id, "assistant", text)
        if session_id:
            self.session_id = session_id
            store.set_thread_session(self.thread_id, session_id)

    def reset(self) -> None:
        store.clear_thread(self.thread_id)
        self.session_id = None
