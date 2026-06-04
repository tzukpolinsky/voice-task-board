from __future__ import annotations

import logging
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from voice_task_board.intent import FirstPassIntent
from voice_task_board.db import get_db
from voice_task_board.gemini import GeminiBackend
from voice_task_board import recurrence_service


logger = logging.getLogger(__name__)


class ApplyResult(Enum):
    CREATED = "created"
    DELETED = "deleted"
    EDITED = "edited"
    UNKNOWN = "unknown"
    NO_MATCH = "no_match"


def _parse_due(intent: FirstPassIntent) -> tuple[str | None, str | None]:
    """Return (due_at_utc, due_tz) from the intent's due_at field.

    The AI returns local wall-clock times so we store them as-is in UTC column
    but record the system timezone so the scheduler can interpret them correctly.
    For recurring rules we always use wall-clock + zone, not UTC offsets.
    """
    if not intent.due_at:
        return None, None
    try:
        import datetime as dt
        from datetime import timezone

        # Determine local system timezone
        local_zone_str: str
        try:
            import tzlocal  # type: ignore
            local_zone_str = str(tzlocal.get_localzone())
        except Exception:
            local_zone_str = "UTC"

        due = intent.due_at
        # Normalize to a consistent format for storage; keep as-is (wall clock)
        # We store the raw value returned by AI; scheduler interprets with due_tz
        return due, local_zone_str
    except Exception as e:
        logger.warning(f"Failed to parse due_at {intent.due_at!r}: {e}")
        return None, None


def apply(first: FirstPassIntent, gemini: GeminiBackend) -> tuple[ApplyResult, int | None]:
    """Apply first-pass intent. Returns (result, task_id) where task_id is set on CREATED."""
    db = get_db()

    if first.action == "add":
        due_at_utc, due_tz = _parse_due(first)
        task_id = db.add_task(
            title=first.title,
            category_name=first.category,
            description=first.content,
            due_at_utc=due_at_utc,
            due_tz=due_tz,
            is_full_day=first.is_full_day,
            lead_time_minutes=first.lead_time_minutes,
            recurrence_rule=first.recurrence_rule,
            mirror_to_remote=first.mirror_to_remote,
        )
        logger.info(f"Added task {task_id}: {first.title!r} ({first.category}) due={due_at_utc} mirror={first.mirror_to_remote}")
        
        # If recurring, materialize the occurrences
        if first.recurrence_rule:
            recurrence_service.materialize(task_id, gemini_backend=gemini)
        
        return ApplyResult.CREATED, task_id

    tasks = db.list_tasks()
    if not tasks:
        logger.info("Else-branch but no existing tasks to act on")
        return ApplyResult.NO_MATCH, None

    task_dicts = [
        {"id": t.id, "title": t.title, "description": t.description, "category": t.category_name}
        for t in tasks
    ]
    resolved = gemini.resolve_else(first.transcription, task_dicts)

    if resolved.action == "unknown" or resolved.target_id is None:
        logger.info(f"Layer-2 could not resolve: action={resolved.action} target_id={resolved.target_id}")
        return ApplyResult.UNKNOWN, None

    if not any(t.id == resolved.target_id for t in tasks):
        logger.warning(f"Layer-2 returned target_id={resolved.target_id} which is not in current tasks")
        return ApplyResult.NO_MATCH, None

    if resolved.action == "delete":
        db.delete_task(resolved.target_id)
        logger.info(f"Deleted task {resolved.target_id}")
        return ApplyResult.DELETED, resolved.target_id

    if resolved.action == "edit":
        updated = db.update_task(
            resolved.target_id,
            title=resolved.title,
            description=resolved.content,
            category_name=resolved.category,
        )

        # Layer-2 only resolves which task; schedule/mirror changes the user
        # asked for live on the Layer-1 intent. Apply them here so "move task X
        # to Thursday and mirror to calendar" actually updates due_at + mirror.
        schedule_changed = False
        if first.due_at:
            due_at_utc, due_tz = _parse_due(first)
            db.update_task_due(
                resolved.target_id,
                due_at_utc=due_at_utc,
                due_tz=due_tz,
                is_full_day=first.is_full_day,
                lead_time_minutes=first.lead_time_minutes,
                recurrence_rule=first.recurrence_rule,
            )
            schedule_changed = True
            
            # If recurrence_rule is set, materialize the occurrences
            if first.recurrence_rule:
                recurrence_service.materialize(resolved.target_id, gemini_backend=gemini)

        if first.mirror_to_remote:
            db.set_mirror_toggle(resolved.target_id, True)
            schedule_changed = True

        if updated or schedule_changed:
            logger.info(f"Edited task {resolved.target_id}")
            return ApplyResult.EDITED, resolved.target_id
        logger.warning(f"Edit produced no changes on task {resolved.target_id}")
        return ApplyResult.UNKNOWN, None

    return ApplyResult.UNKNOWN, None
