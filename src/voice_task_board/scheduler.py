from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from voice_task_board.db import get_db, Task


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
        due_tasks = db.list_tasks_due_for_reminder(now_utc)
        for task in due_tasks:
            db.set_reminder_fired(task.id)
            if _notify_callback:
                _notify_callback(task)
            _maybe_spawn_next_recurrence(task)
    except Exception:
        logger.exception("Error in reminder sweep")


def _maybe_spawn_next_recurrence(task: Task) -> None:
    """If the task is recurring, create the next instance."""
    if not task.recurrence_rule:
        return
    try:
        next_due = _next_due_from_rule(task.recurrence_rule, task.due_tz)
        if next_due is None:
            return
        db = get_db()
        db.add_task(
            title=task.title,
            category_name=task.category_name,
            description=task.description,
            due_at_utc=next_due,
            due_tz=task.due_tz,
            is_full_day=task.is_full_day,
            lead_time_minutes=task.lead_time_minutes,
            recurrence_rule=task.recurrence_rule,
            mirror_to_remote=task.mirror_to_remote,
        )
        logger.info(f"Spawned next recurrence for task {task.id}: due={next_due}")
    except Exception:
        logger.exception(f"Failed to spawn next recurrence for task {task.id}")


def _next_due_from_rule(rule: str, tz_str: str | None) -> str | None:
    """Parse a recurrence rule string and return the next ISO due datetime."""
    import re
    from datetime import timedelta

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_str) if tz_str else timezone.utc
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    rule_lower = rule.lower().strip()

    # Extract time component: "at HH:MM"
    time_match = re.search(r"at (\d{1,2}):(\d{2})", rule_lower)
    hour = int(time_match.group(1)) if time_match else now.hour
    minute = int(time_match.group(2)) if time_match else now.minute

    if "every day" in rule_lower or "daily" in rule_lower:
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=1)
    elif "weekday" in rule_lower or "workday" in rule_lower:
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=1)
        while next_dt.weekday() >= 5:  # skip Sat/Sun
            next_dt += timedelta(days=1)
    elif "week" in rule_lower:
        days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
        target_day: int | None = None
        for name, num in days_map.items():
            if name in rule_lower:
                target_day = num
                break
        if target_day is None:
            return None
        days_ahead = (target_day - now.weekday() + 7) % 7 or 7
        next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    else:
        return None

    return next_dt.strftime("%Y-%m-%dT%H:%M:%S")
