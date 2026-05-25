from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

from voice_task_board.paths import archive_db_path, app_data_dir
from voice_task_board.db import get_db


logger = logging.getLogger(__name__)

_archive_lock = threading.Lock()


ARCHIVE_MIGRATIONS: list[str] = [
    "",
    """
CREATE TABLE archived_tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    due_at_utc TEXT,
    due_tz TEXT,
    is_full_day INTEGER NOT NULL DEFAULT 0,
    lead_time_minutes INTEGER NOT NULL DEFAULT 30,
    recurrence_rule TEXT,
    mirror_to_remote INTEGER NOT NULL DEFAULT 0,
    external_provider TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT NOT NULL DEFAULT (datetime('now'))
);
    """,
]


def _get_archive_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(archive_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _run_archive_migrations(conn)
    return conn


def _run_archive_migrations(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    # If the DB already has an archived_tasks table but user_version=0, it was
    # created by the old CREATE TABLE IF NOT EXISTS path. Mark it as version 1
    # so we don't try to re-create the table.
    cursor.execute("PRAGMA user_version")
    current_version = cursor.fetchone()[0]
    if current_version == 0:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_tasks'"
        )
        if cursor.fetchone() is not None:
            cursor.execute("PRAGMA user_version = 1")
            conn.commit()
            current_version = 1

    for version in range(current_version + 1, len(ARCHIVE_MIGRATIONS)):
        logger.info(f"Running archive migration {version}")
        conn.execute("BEGIN")
        try:
            for statement in ARCHIVE_MIGRATIONS[version].split(";"):
                statement = statement.strip()
                if statement:
                    cursor.execute(statement)
            cursor.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def run_archive_sweep() -> None:
    """Move done tasks older than 30 days from live DB to archive DB. Thread-safe."""
    threading.Thread(target=_sweep, daemon=True).start()


def _sweep() -> None:
    with _archive_lock:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
            live_db = get_db()
            archive_conn = _get_archive_conn()

            with live_db._lock:
                cursor = live_db._conn.cursor()
                cursor.execute(
                    """SELECT t.id, t.title, t.description, c.name, t.status,
                              t.due_at_utc, t.due_tz, t.is_full_day, t.lead_time_minutes,
                              t.recurrence_rule, t.mirror_to_remote, t.external_provider,
                              t.external_id, t.created_at, t.updated_at
                       FROM tasks t JOIN categories c ON t.category_id = c.id
                       WHERE t.status = 'done' AND t.updated_at < ?""",
                    (cutoff,),
                )
                rows = cursor.fetchall()

                if not rows:
                    archive_conn.close()
                    return

                for row in rows:
                    archive_conn.execute(
                        """INSERT OR REPLACE INTO archived_tasks
                           (id, title, description, category_name, status,
                            due_at_utc, due_tz, is_full_day, lead_time_minutes,
                            recurrence_rule, mirror_to_remote, external_provider,
                            external_id, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        tuple(row),
                    )
                archive_conn.commit()

                ids = [row[0] for row in rows]
                cursor.executemany("DELETE FROM tasks WHERE id = ?", [(i,) for i in ids])
                live_db._conn.commit()
                logger.info(f"Archived {len(ids)} old done tasks")

            archive_conn.close()
        except Exception:
            logger.exception("Archive sweep failed")


def list_archived(category_name: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    """Return archived tasks, optionally filtered by category."""
    with _archive_lock:
        try:
            conn = _get_archive_conn()
            if category_name:
                cursor = conn.execute(
                    """SELECT * FROM archived_tasks WHERE category_name = ?
                       ORDER BY archived_at DESC LIMIT ? OFFSET ?""",
                    (category_name, limit, offset),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM archived_tasks ORDER BY archived_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception:
            logger.exception("Failed to list archived tasks")
            return []
