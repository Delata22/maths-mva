"""Persistance de la progression (SQLite)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .paths import db_file

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_state (
    course_id     TEXT PRIMARY KEY,
    generated_at  REAL,
    model         TEXT,
    cost_usd      REAL DEFAULT 0,
    duration_s    REAL DEFAULT 0,
    opened_at     REAL,
    open_count    INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quiz_attempt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   TEXT NOT NULL,
    finished_at REAL NOT NULL,
    total       INTEGER NOT NULL,
    correct     INTEGER NOT NULL,
    detail      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attempt_course ON quiz_attempt(course_id);

CREATE TABLE IF NOT EXISTS proof_state (
    course_id   TEXT NOT NULL,
    proof_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, proof_id)
);

CREATE TABLE IF NOT EXISTS proof_draft (
    course_id   TEXT NOT NULL,
    proof_id    TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    reviews     INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (course_id, proof_id)
);

CREATE TABLE IF NOT EXISTS chat_thread (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   TEXT,
    context_key TEXT,
    session_id  TEXT,
    title       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_message (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON chat_message(thread_id);
"""


def conn() -> sqlite3.Connection:
    """Connexion propre au thread courant (sqlite n'aime pas le partage)."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(str(db_file()), timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        c.commit()
        _local.conn = c
    return c


# --------------------------------------------------------------------- cours
def mark_generated(course_id: str, model: str, cost: float, duration: float) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, generated_at, model, cost_usd, duration_s)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(course_id) DO UPDATE SET
             generated_at=excluded.generated_at, model=excluded.model,
             cost_usd=COALESCE(course_state.cost_usd,0)+excluded.cost_usd,
             duration_s=excluded.duration_s""",
        (course_id, time.time(), model, cost, duration),
    )
    c.commit()


def mark_opened(course_id: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, opened_at, open_count) VALUES (?, ?, 1)
           ON CONFLICT(course_id) DO UPDATE SET
             opened_at=excluded.opened_at, open_count=course_state.open_count+1""",
        (course_id, time.time()),
    )
    c.commit()


def set_notes(course_id: str, notes: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO course_state (course_id, notes) VALUES (?, ?)
           ON CONFLICT(course_id) DO UPDATE SET notes=excluded.notes""",
        (course_id, notes),
    )
    c.commit()


def get_notes(course_id: str) -> str:
    row = conn().execute(
        "SELECT notes FROM course_state WHERE course_id=?", (course_id,)
    ).fetchone()
    return (row["notes"] if row else "") or ""


# ---------------------------------------------------------------------- QCM
def record_attempt(course_id: str, total: int, correct: int, detail: dict) -> int:
    c = conn()
    cur = c.execute(
        "INSERT INTO quiz_attempt (course_id, finished_at, total, correct, detail) VALUES (?,?,?,?,?)",
        (course_id, time.time(), total, correct, json.dumps(detail, ensure_ascii=False)),
    )
    c.commit()
    return int(cur.lastrowid)


def attempts(course_id: str) -> List[sqlite3.Row]:
    return list(conn().execute(
        "SELECT * FROM quiz_attempt WHERE course_id=? ORDER BY finished_at DESC", (course_id,)
    ))


# -------------------------------------------------------------------- demos
def set_proof_status(course_id: str, proof_id: str, status: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO proof_state (course_id, proof_id, status, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             status=excluded.status, updated_at=excluded.updated_at""",
        (course_id, proof_id, status, time.time()),
    )
    c.commit()


def set_proof_draft(course_id: str, proof_id: str, text: str) -> None:
    c = conn()
    c.execute(
        """INSERT INTO proof_draft (course_id, proof_id, text, updated_at) VALUES (?,?,?,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             text=excluded.text, updated_at=excluded.updated_at""",
        (course_id, proof_id, text, time.time()),
    )
    c.commit()


def count_review(course_id: str, proof_id: str) -> int:
    """Incremente et retourne le nombre de corrections demandees."""
    c = conn()
    c.execute(
        """INSERT INTO proof_draft (course_id, proof_id, reviews, updated_at)
           VALUES (?,?,1,?)
           ON CONFLICT(course_id, proof_id) DO UPDATE SET
             reviews=proof_draft.reviews+1, updated_at=excluded.updated_at""",
        (course_id, proof_id, time.time()),
    )
    c.commit()
    row = c.execute("SELECT reviews FROM proof_draft WHERE course_id=? AND proof_id=?",
                    (course_id, proof_id)).fetchone()
    return int(row["reviews"]) if row else 1


def proof_drafts(course_id: str) -> Dict[str, str]:
    rows = conn().execute(
        "SELECT proof_id, text FROM proof_draft WHERE course_id=?", (course_id,))
    return {r["proof_id"]: r["text"] for r in rows}


def proof_statuses(course_id: str) -> Dict[str, str]:
    rows = conn().execute(
        "SELECT proof_id, status FROM proof_state WHERE course_id=?", (course_id,)
    )
    return {r["proof_id"]: r["status"] for r in rows}


# ------------------------------------------------------------------- resume
@dataclass
class Progress:
    course_id: str
    generated: bool = False
    opened: bool = False
    attempts: int = 0
    best_pct: Optional[int] = None
    last_pct: Optional[int] = None
    proofs_done: int = 0
    proofs_total: int = 0

    @property
    def validated_by_quiz(self) -> bool:
        return self.best_pct is not None and self.best_pct >= 80


def progress_map() -> Dict[str, Progress]:
    c = conn()
    out: Dict[str, Progress] = {}
    for r in c.execute("SELECT * FROM course_state"):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.generated = r["generated_at"] is not None
        p.opened = (r["open_count"] or 0) > 0
    for r in c.execute(
        """SELECT course_id, COUNT(*) n,
                  MAX(CAST(correct AS REAL)/NULLIF(total,0)) best
           FROM quiz_attempt GROUP BY course_id"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.attempts = r["n"]
        p.best_pct = int(round((r["best"] or 0) * 100))
    for r in c.execute(
        """SELECT course_id, correct, total FROM quiz_attempt a
           WHERE finished_at = (SELECT MAX(finished_at) FROM quiz_attempt b
                                WHERE b.course_id = a.course_id)"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        if r["total"]:
            p.last_pct = int(round(100.0 * r["correct"] / r["total"]))
    for r in c.execute(
        """SELECT course_id, SUM(status='done') done, COUNT(*) total
           FROM proof_state GROUP BY course_id"""
    ):
        p = out.setdefault(r["course_id"], Progress(r["course_id"]))
        p.proofs_done = r["done"] or 0
        p.proofs_total = r["total"] or 0
    return out


# --------------------------------------------------------------------- chat
def create_thread(course_id: Optional[str], context_key: str, title: str) -> int:
    c = conn()
    now = time.time()
    cur = c.execute(
        "INSERT INTO chat_thread (course_id, context_key, title, created_at, updated_at) VALUES (?,?,?,?,?)",
        (course_id, context_key, title, now, now),
    )
    c.commit()
    return int(cur.lastrowid)


def find_thread(course_id: Optional[str], context_key: str) -> Optional[sqlite3.Row]:
    c = conn()
    if course_id is None:
        return c.execute(
            "SELECT * FROM chat_thread WHERE course_id IS NULL AND context_key=? ORDER BY updated_at DESC LIMIT 1",
            (context_key,),
        ).fetchone()
    return c.execute(
        "SELECT * FROM chat_thread WHERE course_id=? AND context_key=? ORDER BY updated_at DESC LIMIT 1",
        (course_id, context_key),
    ).fetchone()


def set_thread_session(thread_id: int, session_id: str) -> None:
    c = conn()
    c.execute("UPDATE chat_thread SET session_id=?, updated_at=? WHERE id=?",
              (session_id, time.time(), thread_id))
    c.commit()


def add_message(thread_id: int, role: str, content: str) -> None:
    c = conn()
    c.execute("INSERT INTO chat_message (thread_id, role, content, created_at) VALUES (?,?,?,?)",
              (thread_id, role, content, time.time()))
    c.execute("UPDATE chat_thread SET updated_at=? WHERE id=?", (time.time(), thread_id))
    c.commit()


def messages(thread_id: int) -> List[sqlite3.Row]:
    return list(conn().execute(
        "SELECT * FROM chat_message WHERE thread_id=? ORDER BY id", (thread_id,)))


def clear_thread(thread_id: int) -> None:
    c = conn()
    c.execute("DELETE FROM chat_message WHERE thread_id=?", (thread_id,))
    c.execute("UPDATE chat_thread SET session_id=NULL WHERE id=?", (thread_id,))
    c.commit()
