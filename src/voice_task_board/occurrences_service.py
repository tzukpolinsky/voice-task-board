"""Occurrence service: handles completion and series management."""

import logging
from voice_task_board.db import get_db


logger = logging.getLogger(__name__)


def complete_occurrence(occ_id: int) -> None:
    """Complete a single occurrence.
    
    This marks the occurrence as done, completes it on Google if mirrored,
    and advances the parent task's pointer to the next unfired occurrence.
    """
    db = get_db()
    
    # Get the occurrence
    cursor = db._conn.cursor()
    cursor.execute(
        """SELECT id, task_id, due_at_utc, external_id
           FROM occurrences WHERE id = ?""",
        (occ_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    
    occ_id_val, task_id, due_at_utc, external_id = row
    task = db.get_task(task_id)
    if not task:
        return
    
    # Mark the occurrence done
    db.mark_occurrence_done(occ_id)
    logger.info(f"Completed occurrence {occ_id}")
    
    # Complete it on Google if mirrored
    if external_id and task.mirror_to_remote:
        try:
            from voice_task_board import remote_sync
            remote_sync._google_complete_occurrence(external_id)
            logger.info(f"Completed google occurrence {external_id}")
        except Exception as e:
            logger.warning(f"Failed to complete google occurrence {external_id}: {e}")
    
    # Advance parent task pointer to next undone (is_done=0) occurrence
    curr_occ = db.current_occurrence(task_id)
    if curr_occ:
        db.update_task_due(
            task_id,
            due_at_utc=curr_occ.due_at_utc,
            due_tz=task.due_tz,
            is_full_day=task.is_full_day,
            lead_time_minutes=task.lead_time_minutes,
            recurrence_rule=task.recurrence_rule,
        )
        if curr_occ.external_id:
            db.set_external(
                task_id, task.external_provider, curr_occ.external_id,
                None, mirror_pending=False
            )
    else:
        # No more undone occurrences - but don't complete the task yet,
        # just make sure the pointer is cleared
        db.update_task_due(
            task_id,
            due_at_utc=None,
            due_tz=task.due_tz,
            is_full_day=task.is_full_day,
            lead_time_minutes=task.lead_time_minutes,
            recurrence_rule=task.recurrence_rule,
        )


def end_series(task_id: int) -> None:
    """End a recurring series.
    
    This marks the series as inactive, deletes all future occurrences,
    deletes them on Google if mirrored, and marks the parent task as done.
    """
    db = get_db()
    task = db.get_task(task_id)
    if not task:
        return
    
    # Get the current datetime for finding future occurrences
    import datetime
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    
    # Delete future occurrences and get their external IDs
    external_ids_to_delete = db.delete_future_occurrences(task_id, now_utc)
    
    # Delete them on Google
    if external_ids_to_delete and task.mirror_to_remote:
        try:
            from voice_task_board import remote_sync
            for ext_id in external_ids_to_delete:
                try:
                    remote_sync._google_delete_occurrence(ext_id)
                    logger.info(f"Deleted google occurrence {ext_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete google occurrence {ext_id}: {e}")
        except Exception as e:
            logger.warning(f"Failed to import remote_sync: {e}")
    
    # Mark the series as ended
    db.end_series(task_id)
    logger.info(f"Ended series for task {task_id}")
    
    # Mark the parent task as done
    db.complete_task(task_id)
    logger.info(f"Completed parent task {task_id}")
