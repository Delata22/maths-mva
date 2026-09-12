"""Preferences persistantes (QSettings)."""
from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "maths-mva"
APP = "MathsMVA"

DEFAULTS = {
    "model/course": "opus",
    "model/exercises": "sonnet",
    "model/chat": "opus",
    "model/sheet": "sonnet",
    "gen/concurrency": 1,
    "gen/section_parallel": 3,
    "gen/auto_sheet": True,
    "gen/max_sections": 9,
    "ui/mastery_threshold": 80,
    "goal/bricks": 1,
    "goal/review_batch": 20,
    "ui/font_scale": 100,
    "claude/binary": "claude",
    "claude/timeout": 1800,
    "claude/retries": 3,
    "claude/stall_timeout": 240,
}


def settings() -> QSettings:
    return QSettings(ORG, APP)


def get(key: str):
    s = settings()
    default = DEFAULTS.get(key)
    value = s.value(key, default)
    if isinstance(default, int) and not isinstance(value, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
    return value


def put(key: str, value) -> None:
    settings().setValue(key, value)
