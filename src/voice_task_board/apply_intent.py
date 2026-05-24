from __future__ import annotations

import logging
from enum import Enum

from voice_task_board.intent import FirstPassIntent
from voice_task_board.db import get_db
from voice_task_board.gemini import GeminiBackend


logger = logging.getLogger(__name__)


class ApplyResult(Enum):
    CREATED = "created"
    DELETED = "deleted"
    EDITED = "edited"
    UNKNOWN = "unknown"
    NO_MATCH = "no_match"


def apply(first: FirstPassIntent, gemini: GeminiBackend) -> ApplyResult:
    db = get_db()

    if first.action == "add":
        db.add_task(first.title, first.category, first.content)
        logger.info(f"Added task: {first.title!r} ({first.category})")
        return ApplyResult.CREATED

    tasks = db.list_tasks()
    if not tasks:
        logger.info("Else-branch but no existing tasks to act on")
        return ApplyResult.NO_MATCH

    task_dicts = [
        {"id": t.id, "title": t.title, "description": t.description, "category": t.category_name}
        for t in tasks
    ]
    resolved = gemini.resolve_else(first.transcription, task_dicts)

    if resolved.action == "unknown" or resolved.target_id is None:
        logger.info(f"Layer-2 could not resolve: action={resolved.action} target_id={resolved.target_id}")
        return ApplyResult.UNKNOWN

    if not any(t.id == resolved.target_id for t in tasks):
        logger.warning(f"Layer-2 returned target_id={resolved.target_id} which is not in current tasks")
        return ApplyResult.NO_MATCH

    if resolved.action == "delete":
        db.delete_task(resolved.target_id)
        logger.info(f"Deleted task {resolved.target_id}")
        return ApplyResult.DELETED

    if resolved.action == "edit":
        updated = db.update_task(
            resolved.target_id,
            title=resolved.title,
            description=resolved.content,
            category_name=resolved.category,
        )
        if updated:
            logger.info(f"Edited task {resolved.target_id}")
            return ApplyResult.EDITED
        logger.warning(f"Edit produced no changes on task {resolved.target_id}")
        return ApplyResult.UNKNOWN

    return ApplyResult.UNKNOWN
