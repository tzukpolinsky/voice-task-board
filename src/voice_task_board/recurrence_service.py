"""Recurrence service: orchestrates materialization of recurring tasks."""

import logging
from datetime import datetime, timezone

from voice_task_board.db import get_db
from voice_task_board.recurrence import generate_occurrences
from voice_task_board.notifications import show_status


logger = logging.getLogger(__name__)


def resolve_pile(task_id: int, done: bool = True, notified_date: str = "") -> None:
    """Mark all pending occurrences for a task as resolved.

    Args:
        task_id: The task whose pile to resolve
        done: If True, mark as done; if False (Dismiss), leave undone but throttle re-nag
        notified_date: Date to stamp for throttling; if empty uses today
    """
    db = get_db()
    db.mark_pile_resolved(task_id, done=done, notified_date=notified_date)
    action = "done" if done else "dismissed"
    logger.info(f"Marked all pending occurrences {action} for task {task_id}")


def materialize(task_id: int, gemini_backend=None) -> None:
    """
    Materialize a recurring task: generate occurrences and sync to Google if needed.
    
    Args:
        task_id: The task ID to materialize
        gemini_backend: Optional GeminiBackend instance for AI text→RRULE conversion
    """
    db = get_db()
    task = db.get_task(task_id)
    
    if not task or not task.recurrence_rule:
        return
    
    # If recurrence_rule is free text (not yet an RRULE), convert it
    if task.recurrence_rule and not task.recurrence_rule.startswith("FREQ="):
        # Need to convert via AI
        if gemini_backend is None:
            from voice_task_board.gemini import GeminiBackend
            from voice_task_board.config import get_config
            config = get_config()
            if not config.gemini_api_key:
                logger.warning(f"Cannot materialize task {task_id}: no Gemini API key for text→RRULE conversion")
                return
            gemini_backend = GeminiBackend(config.gemini_api_key)
        
        try:
            rrule, ai_until = gemini_backend.text_to_rrule(task.recurrence_rule)
            if rrule is None:
                # Not a recurring task after all
                db.set_recurrence(task_id, None, None)
                logger.info(f"Task {task_id} marked as non-recurring")
                return
            # A user-supplied until (from the edit form) wins over the AI's guess;
            # only fall back to the AI-extracted until when the user didn't set one.
            until = task.recurrence_until or ai_until
            db.set_recurrence(task_id, rrule, until)
            task = db.get_task(task_id)  # Reload with new values
        except Exception as e:
            logger.error(f"Failed to convert recurrence text for task {task_id}: {e}")
            return
    
    # Now generate occurrences using the RRULE
    rrule = task.recurrence_rule
    start_utc = task.due_at_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    until_utc = task.recurrence_until
    
    try:
        occurrences = generate_occurrences(rrule, start_utc, task.due_tz, until_utc)
    except Exception as e:
        logger.error(f"Failed to generate occurrences for task {task_id}: {e}")
        return
    
    if not occurrences:
        logger.warning(f"No occurrences generated for task {task_id}")
        return

    # Idempotency: clear the previously-materialized UNDONE schedule before
    # regenerating, so (re)materializing a rule doesn't stack a second window on
    # top of the old one. Done occurrences (history) are kept; this also removes
    # the boundary occurrence at exactly the start so it isn't duplicated.
    stale_external_ids = db.delete_unfinished_occurrences(task_id)
    if stale_external_ids and task.mirror_to_remote:
        from voice_task_board import remote_sync
        for ext_id in stale_external_ids:
            remote_sync.delete_occurrence_external(ext_id)

    # Add them to the database
    db.add_occurrences(task_id, occurrences)
    logger.info(f"Materialized {len(occurrences)} occurrences for task {task_id}")

    # Clear the parent's mirror_pending flag (avoid double-mirror after push_occurrences below)
    db.set_external(task_id, task.external_provider, task.external_id, None, mirror_pending=False)

    # Update parent task to point to the first occurrence
    db.update_task_due(
        task_id,
        due_at_utc=occurrences[0],
        due_tz=task.due_tz,
        is_full_day=task.is_full_day,
        lead_time_minutes=task.lead_time_minutes,
        recurrence_rule=rrule,
    )
    
    # If mirrored, push all occurrences to Google
    if task.mirror_to_remote:
        def toast_callback():
            until_date = task.recurrence_until
            if until_date:
                # Extract just the date part
                until_display = until_date[:10] if "T" in until_date else until_date
                show_status(f"Repeating task synced — {len(occurrences)} occurrences until {until_display}")
            else:
                show_status(f"Repeating task synced — {len(occurrences)} occurrences for the next year")
        
        # Import here to avoid circular dependency
        from voice_task_board import remote_sync
        remote_sync.push_occurrences_for_task(task_id, done_callback=toast_callback)
    else:
        # No mirror, just log
        logger.info(f"Task {task_id} not mirrored, skipping Google push")
