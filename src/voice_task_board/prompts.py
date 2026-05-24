from __future__ import annotations

import logging
import sys
from pathlib import Path


logger = logging.getLogger(__name__)

_cache: dict[str, str] = {}


def _is_dev() -> bool:
    return not getattr(sys, "frozen", False)


def _prompts_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "resources" / "prompts"
    return Path(__file__).parent / "resources" / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt by name (without extension). Dev: reads from disk each call. Prod: cached after first load."""
    if not _is_dev() and name in _cache:
        return _cache[name]

    path = _prompts_dir() / f"{name}.txt"
    text = path.read_text(encoding="utf-8")

    if not _is_dev():
        _cache[name] = text
        logger.info(f"Cached prompt '{name}' ({len(text)} chars)")
    else:
        logger.debug(f"Loaded prompt '{name}' from disk ({len(text)} chars)")

    return text
