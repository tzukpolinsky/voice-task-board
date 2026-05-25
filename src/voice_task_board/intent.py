from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class FirstPassIntent(BaseModel):
    """Layer-1 result: classify add vs anything-else, with the raw transcription for layer-2."""
    action: Literal["add", "else"]
    title: str
    content: str = ""
    category: str
    transcription: str
    due_at: str | None = None          # ISO 8601 date ("2026-05-28") or datetime ("2026-05-28T14:00:00")
    is_full_day: bool = False
    lead_time_minutes: int = 30
    recurrence_rule: str | None = None  # e.g. "every weekday at 09:00" or None
    mirror_to_remote: bool = False


class ResolvedIntent(BaseModel):
    """Layer-2 result: given the transcription + current tasks, decide what to do."""
    action: Literal["edit", "delete", "unknown"]
    target_id: int | None = None
    title: str | None = None
    content: str | None = None
    category: str | None = None
