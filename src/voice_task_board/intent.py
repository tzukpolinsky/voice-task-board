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


class ResolvedIntent(BaseModel):
    """Layer-2 result: given the transcription + current tasks, decide what to do."""
    action: Literal["edit", "delete", "unknown"]
    target_id: int | None = None
    title: str | None = None
    content: str | None = None
    category: str | None = None
