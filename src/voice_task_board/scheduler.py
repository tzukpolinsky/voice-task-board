from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Callable
from collections import defaultdict

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from voice_task_board.db import get_db, Task
from voice_task_board import recurrence


logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_notify_callback: Callable[[Task], None] | None = None
_snooze_jobs: dict[int, str] = {}  # task_id -> apscheduler job_id for snooze


def set_notify_callback(fn: Callable[[Task], None]) -> None:
    global _notify_callback
    _notify_callback = fn


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _check_due_reminders,
        trigger=CronTrigger(second=0),
        id="reminder_sweep",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),  # fire immediately on start too
    )
    _scheduler.start()
    logger.info("Reminder scheduler started")


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def snooze(task_id: int, minutes: int = 10) -> None:
    """Re-schedule a reminder for a specific task after `minutes` from now."""
    if _scheduler is None:
        return
    job_id = f"snooze_{task_id}"
    _scheduler.add_job(
        _fire_snooze,
        "date",
        run_date=datetime.now(timezone.utc).replace(microsecond=0).__class__.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + minutes * 60, tz=timezone.utc
        ),
        args=[task_id],
        id=job_id,
        replace_existing=True,
    )
    logger.info(f"Snoozed task {task_id} for {minutes} minutes")


def _fire_snooze(task_id: int) -> None:
    db = get_db()
    task = db.get_task(task_id)
    if task and task.status == "open" and _notify_callback:
        _notify_callback(task)


def _check_due_reminders() -> None:
    try:
        db = get_db()
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Handle non-recurring tasks (legacy path - unchanged)
        due_tasks = db.list_tasks_due_for_reminder(now_utc)
        for task in due_tasks:
            db.set_reminder_fired(task.id)
            if _notify_callback:
                _notify_callback(task)

        # Handle recurring tasks (new occurrences path) with missed-pile collapse
        due_occurrences = db.list_occurrences_due_for_reminder(now_utc)

        # Group pending occurrences by task_id
        pending_by_task: dict[int, list] = defaultdict(list)
        task_objs: dict[int, Task] = {}

        for occ, task in due_occurrences:
            pending_by_task[task.id].append(occ)
            task_objs[task.id] = task

        # Process each task's pending occurrences
        for task_id, pending_occs in pending_by_task.items():
            task = task_objs[task_id]

            # Mark all as fired
            for occ in pending_occs:
                db.mark_occurrence_fired(occ.id)

            # Decide: if >=2 pending, show missed-summary; else show normal reminders
            if len(pending_occs) >= 2:
                # Show a single summary toast and let user choose
                from voice_task_board import notifications
                action = notifications.show_missed_summary(task.title, len(pending_occs))

                if action == "mark_done":
                    # Mark all pending for this task as done
                    from voice_task_board import recurrence_service
                    recurrence_service.resolve_pile(task_id)
                # else "dismiss": do nothing, re-nag will retry tomorrow
            else:
                # <=1 pending: show normal reminder for each
                for occ in pending_occs:
                    if _notify_callback:
                        _notify_callback(task)

            # Update last_notified_date for each
            for occ in pending_occs:
                db.set_occurrence_notified(occ.id, now_date)

            # Lazy top-up: if not past UNTIL, add next occurrence
            if task.recurrence_active:
                last_mat_due = db.last_materialized_due(task.id)
                if last_mat_due is None:
                    last_mat_due = pending_occs[0].due_at_utc if pending_occs else task.due_at_utc

                # Get the next occurrence after the last materialized one
                next_due = recurrence.next_after(
                    task.recurrence_rule or "",
                    last_mat_due,
                    task.due_tz,
                    task.recurrence_until,
                )

                if next_due:
                    db.add_occurrences(task.id, [next_due])

                    # If mirrored, push the new occurrence to Google
                    if task.mirror_to_remote:
                        from voice_task_board import remote_sync
                        # Get the newly added occurrence
                        new_occs = db.list_occurrences(task.id)
                        if new_occs:
                            new_occ = new_occs[-1]  # Last one added
                            remote_sync.push_occurrence(new_occ.id)

                # Update parent task's due_at_utc to the current (earliest undone) occurrence
                curr_occ = db.current_occurrence(task.id)
                if curr_occ:
                    db.update_task_due(
                        task.id,
                        due_at_utc=curr_occ.due_at_utc,
                        due_tz=task.due_tz,
                        is_full_day=task.is_full_day,
                        lead_time_minutes=task.lead_time_minutes,
                        recurrence_rule=task.recurrence_rule,
                    )
                    # Also update external_id pointer to the current occurrence
                    if curr_occ.external_id:
                        db.set_external(
                            task.id, task.external_provider, curr_occ.external_id,
                            None, mirror_pending=False
                        )

    except Exception:
        logger.exception("Error in reminder sweep")
