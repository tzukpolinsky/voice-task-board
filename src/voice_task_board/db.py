from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import cast

from voice_task_board.paths import app_data_dir


logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: int
    title: str
    description: str
    category_id: int
    category_name: str
    status: str
    created_at: str
    updated_at: str
    due_at_utc: str | None = None
    due_tz: str | None = None
    is_full_day: bool = False
    lead_time_minutes: int = 30
    recurrence_rule: str | None = None
    mirror_to_remote: bool = False
    external_provider: str | None = None
    external_id: str | None = None
    external_updated_at: str | None = None
    mirror_pending: bool = False
    reminder_fired: bool = False
    is_recurrence: bool = False
    recurrence_until: str | None = None
    recurrence_active: bool = True


@dataclass
class Occurrence:
    id: int
    task_id: int
    due_at_utc: str
    fired: int = 0
    is_done: int = 0
    external_id: str | None = None
    mirror_pending: int = 0
    created_at: str = ""


class MatchResult(Enum):
    """Result of a task match operation."""
    @dataclass
    class Hit:
        id: int
    
    @dataclass
    class Ambiguous:
        count: int
    
    class NoMatch:
        pass


MIGRATIONS: list[str] = [
    "",
    """
CREATE TABLE categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tasks (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  status TEXT NOT NULL DEFAULT 'open',
  data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_tasks_title ON tasks(title);
CREATE INDEX idx_tasks_category ON tasks(category_id);
CREATE INDEX idx_tasks_status ON tasks(status);

INSERT INTO categories (name, sort_order) VALUES ('default', 0);
INSERT INTO categories (name, sort_order) VALUES ('Personal', 1);
INSERT INTO categories (name, sort_order) VALUES ('Work', 2);
    """,
    """
ALTER TABLE tasks ADD COLUMN description TEXT NOT NULL DEFAULT '';
    """,
    """
ALTER TABLE tasks ADD COLUMN due_at_utc TEXT;
ALTER TABLE tasks ADD COLUMN due_tz TEXT;
ALTER TABLE tasks ADD COLUMN is_full_day INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN lead_time_minutes INTEGER NOT NULL DEFAULT 30;
ALTER TABLE tasks ADD COLUMN recurrence_rule TEXT;
ALTER TABLE tasks ADD COLUMN mirror_to_remote INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN external_provider TEXT;
ALTER TABLE tasks ADD COLUMN external_id TEXT;
ALTER TABLE tasks ADD COLUMN external_updated_at TEXT;
ALTER TABLE tasks ADD COLUMN mirror_pending INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN reminder_fired INTEGER NOT NULL DEFAULT 0;
    """,
    """
CREATE TABLE occurrences (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  due_at_utc TEXT NOT NULL,
  fired INTEGER NOT NULL DEFAULT 0,
  is_done INTEGER NOT NULL DEFAULT 0,
  external_id TEXT,
  mirror_pending INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_occ_task ON occurrences(task_id);
CREATE INDEX idx_occ_due ON occurrences(due_at_utc);
CREATE INDEX idx_occ_fired ON occurrences(fired);

ALTER TABLE tasks ADD COLUMN is_recurrence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN recurrence_until TEXT;
ALTER TABLE tasks ADD COLUMN recurrence_active INTEGER NOT NULL DEFAULT 1;
    """,
]


class Database:
    def __init__(self) -> None:
        self._db_path = app_data_dir() / "tasks.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._run_migrations()

    def _run_migrations(self) -> None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA user_version")
            current_version = cursor.fetchone()[0]

            for version in range(current_version + 1, len(MIGRATIONS)):
                migration_sql = MIGRATIONS[version]
                logger.info(f"Running migration {version}")
                self._conn.execute("BEGIN")
                try:
                    for statement in migration_sql.split(";"):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    cursor.execute(f"PRAGMA user_version = {version}")
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise

    def add_task(
        self,
        title: str,
        category_name: str,
        description: str = "",
        due_at_utc: str | None = None,
        due_tz: str | None = None,
        is_full_day: bool = False,
        lead_time_minutes: int = 30,
        recurrence_rule: str | None = None,
        mirror_to_remote: bool = False,
    ) -> int:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (category_name,))
            row = cursor.fetchone()
            if row:
                category_id = row[0]
            else:
                cursor.execute("SELECT id FROM categories WHERE LOWER(name) = LOWER('default')")
                default_row = cursor.fetchone()
                category_id = default_row[0] if default_row else 1

            cursor.execute(
                """INSERT INTO tasks
                   (title, description, category_id, due_at_utc, due_tz, is_full_day,
                    lead_time_minutes, recurrence_rule, mirror_to_remote, mirror_pending)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, description, category_id, due_at_utc, due_tz,
                 1 if is_full_day else 0, lead_time_minutes, recurrence_rule,
                 1 if mirror_to_remote else 0, 1 if mirror_to_remote else 0),
            )
            self._conn.commit()
            return cast(int, cursor.lastrowid)

    def create_task(
        self,
        title: str,
        category_id: int,
        description: str = "",
        due_at_utc: str | None = None,
        due_tz: str | None = None,
        is_full_day: bool = False,
        lead_time_minutes: int = 30,
        recurrence_rule: str | None = None,
        mirror_to_remote: bool = False,
    ) -> int:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """INSERT INTO tasks
                   (title, description, category_id, due_at_utc, due_tz, is_full_day,
                    lead_time_minutes, recurrence_rule, mirror_to_remote, mirror_pending)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, description, category_id, due_at_utc, due_tz,
                 1 if is_full_day else 0, lead_time_minutes, recurrence_rule,
                 1 if mirror_to_remote else 0, 1 if mirror_to_remote else 0),
            )
            self._conn.commit()
            return cast(int, cursor.lastrowid)

    def update_task(self, task_id: int, title: str | None = None, description: str | None = None, category_name: str | None = None) -> bool:
        """Update any combination of fields on a task. Returns True if a row was updated."""
        sets: list[str] = []
        values: list = []
        if title is not None:
            sets.append("title = ?")
            values.append(title)
        if description is not None:
            sets.append("description = ?")
            values.append(description)
        with self._lock:
            cursor = self._conn.cursor()
            if category_name is not None:
                cursor.execute("SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (category_name,))
                cat_row = cursor.fetchone()
                if cat_row:
                    sets.append("category_id = ?")
                    values.append(cat_row[0])
            if not sets:
                return False
            sets.append("updated_at = datetime('now')")
            values.append(task_id)
            cursor.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", values)
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_task_matching(self, query: str) -> MatchResult.Hit | MatchResult.Ambiguous | MatchResult.NoMatch:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*), id FROM tasks WHERE title LIKE ?", (f"%{query}%",))
            row = cursor.fetchone()
            if row is None:
                return MatchResult.NoMatch()
            
            count, task_id = row[0], row[1]
            
            if count == 1:
                cursor.execute("DELETE FROM tasks WHERE title LIKE ?", (f"%{query}%",))
                self._conn.commit()
                logger.info(f"Deleted task {task_id}")
                return MatchResult.Hit(id=task_id)
            elif count > 1:
                logger.warning(f"Ambiguous delete: {count} tasks match '{query}'")
                return MatchResult.Ambiguous(count=count)
            else:
                return MatchResult.NoMatch()

    def edit_task_matching(self, query: str, new_title: str) -> MatchResult.Hit | MatchResult.Ambiguous | MatchResult.NoMatch:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*), id FROM tasks WHERE title LIKE ?", (f"%{query}%",))
            row = cursor.fetchone()
            if row is None:
                return MatchResult.NoMatch()
            
            count, task_id = row[0], row[1]

            if count == 1:
                cursor.execute(
                    "UPDATE tasks SET title = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_title, task_id),
                )
                self._conn.commit()
                logger.info(f"Edited task {task_id}")
                return MatchResult.Hit(id=task_id)
            elif count > 1:
                logger.warning(f"Ambiguous edit: {count} tasks match '{query}'")
                return MatchResult.Ambiguous(count=count)
            else:
                return MatchResult.NoMatch()

    def list_tasks(self, include_done: bool = False) -> list[Task]:
        with self._lock:
            cursor = self._conn.cursor()
            where = "" if include_done else "WHERE tasks.status != 'done'"
            cursor.execute(
                f"""SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at,
                          tasks.due_at_utc, tasks.due_tz, tasks.is_full_day, tasks.lead_time_minutes,
                          tasks.recurrence_rule, tasks.mirror_to_remote, tasks.external_provider,
                          tasks.external_id, tasks.external_updated_at, tasks.mirror_pending,
                          tasks.reminder_fired, tasks.is_recurrence, tasks.recurrence_until,
                          tasks.recurrence_active
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   {where}
                   ORDER BY tasks.created_at DESC"""
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]

    def list_tasks_due_for_reminder(self, now_utc: str) -> list[Task]:
        """Return open tasks whose reminder should fire: due_at_utc - lead_time_minutes <= now and not yet fired."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at,
                          tasks.due_at_utc, tasks.due_tz, tasks.is_full_day, tasks.lead_time_minutes,
                          tasks.recurrence_rule, tasks.mirror_to_remote, tasks.external_provider,
                          tasks.external_id, tasks.external_updated_at, tasks.mirror_pending,
                          tasks.reminder_fired, tasks.is_recurrence, tasks.recurrence_until,
                          tasks.recurrence_active
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   WHERE tasks.status = 'open'
                     AND tasks.due_at_utc IS NOT NULL
                     AND tasks.reminder_fired = 0
                     AND datetime(tasks.due_at_utc, '-' || tasks.lead_time_minutes || ' minutes') <= datetime(?)""",
                (now_utc,),
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]

    def list_mirrored_open_tasks(self) -> list[Task]:
        """Return open tasks that have an external_id (for drift detection)."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at,
                          tasks.due_at_utc, tasks.due_tz, tasks.is_full_day, tasks.lead_time_minutes,
                          tasks.recurrence_rule, tasks.mirror_to_remote, tasks.external_provider,
                          tasks.external_id, tasks.external_updated_at, tasks.mirror_pending,
                          tasks.reminder_fired, tasks.is_recurrence, tasks.recurrence_until,
                          tasks.recurrence_active
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   WHERE tasks.status = 'open' AND tasks.external_id IS NOT NULL"""
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]

    def list_pending_mirror_tasks(self) -> list[Task]:
        """Return tasks with mirror_pending=1 (failed sync, retry queue)."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at,
                          tasks.due_at_utc, tasks.due_tz, tasks.is_full_day, tasks.lead_time_minutes,
                          tasks.recurrence_rule, tasks.mirror_to_remote, tasks.external_provider,
                          tasks.external_id, tasks.external_updated_at, tasks.mirror_pending,
                          tasks.reminder_fired, tasks.is_recurrence, tasks.recurrence_until,
                          tasks.recurrence_active
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   WHERE tasks.mirror_pending = 1"""
            )
            return [self._row_to_task(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=int(row[0]),
            title=row[1],
            description=row[2] or "",
            category_id=int(row[3]),
            category_name=row[4],
            status=row[5],
            created_at=row[6],
            updated_at=row[7],
            due_at_utc=row[8],
            due_tz=row[9],
            is_full_day=bool(row[10]),
            lead_time_minutes=int(row[11]) if row[11] is not None else 30,
            recurrence_rule=row[12],
            mirror_to_remote=bool(row[13]),
            external_provider=row[14],
            external_id=row[15],
            external_updated_at=row[16],
            mirror_pending=bool(row[17]),
            reminder_fired=bool(row[18]),
            is_recurrence=bool(row[19]),
            recurrence_until=row[20],
            recurrence_active=bool(row[21]),
        )

    def list_categories(self) -> list[dict[str, int | str]]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT id, name FROM categories ORDER BY sort_order")
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    
    def get_category_names(self) -> list[str]:
        """Return just the category names for Gemini prompt."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT name FROM categories ORDER BY sort_order")
            return [row[0] for row in cursor.fetchall()]
    
    def add_category(self, name: str) -> int:
        """Add a new category and return its ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "INSERT INTO categories (name) VALUES (?)",
                (name,),
            )
            self._conn.commit()
            return cast(int, cursor.lastrowid)
    
    def delete_category(self, category_id: int) -> None:
        """Delete a category by ID. Raises error if it has tasks (foreign key constraint)."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
                self._conn.commit()
            except Exception as e:
                if "FOREIGN KEY constraint failed" in str(e):
                    raise ValueError(f"Cannot delete category: it has tasks in use.") from e
                raise
    
    def move_task(self, task_id: int, category_id: int) -> None:
        """Move a task to a different category."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE tasks SET category_id = ?, updated_at = datetime('now') WHERE id = ?",
                (category_id, task_id),
            )
            self._conn.commit()

    def delete_task(self, task_id: int) -> None:
        """Delete a task by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._conn.commit()

    def complete_task(self, task_id: int) -> None:
        """Mark a task as done."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE tasks SET status = 'done', updated_at = datetime('now') WHERE id = ?",
                (task_id,),
            )
            self._conn.commit()

    def get_task(self, task_id: int) -> Task | None:
        """Fetch a single task by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at,
                          tasks.due_at_utc, tasks.due_tz, tasks.is_full_day, tasks.lead_time_minutes,
                          tasks.recurrence_rule, tasks.mirror_to_remote, tasks.external_provider,
                          tasks.external_id, tasks.external_updated_at, tasks.mirror_pending,
                          tasks.reminder_fired, tasks.is_recurrence, tasks.recurrence_until,
                          tasks.recurrence_active
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   WHERE tasks.id = ?""",
                (task_id,),
            )
            row = cursor.fetchone()
            return self._row_to_task(row) if row else None

    def set_reminder_fired(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET reminder_fired = 1 WHERE id = ?", (task_id,)
            )
            self._conn.commit()

    def set_external(
        self,
        task_id: int,
        external_provider: str | None,
        external_id: str | None,
        external_updated_at: str | None,
        mirror_pending: bool = False,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE tasks SET external_provider = ?, external_id = ?,
                   external_updated_at = ?, mirror_pending = ?, mirror_to_remote = 1,
                   updated_at = datetime('now') WHERE id = ?""",
                (external_provider, external_id, external_updated_at,
                 1 if mirror_pending else 0, task_id),
            )
            self._conn.commit()

    def set_mirror_pending(self, task_id: int, pending: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET mirror_pending = ? WHERE id = ?",
                (1 if pending else 0, task_id),
            )
            self._conn.commit()

    def set_mirror_drift(self, task_id: int, has_drift: bool) -> None:
        """Store drift flag in external_updated_at as a sentinel '!drift' when drift detected."""
        with self._lock:
            val = "!drift" if has_drift else None
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT external_updated_at FROM tasks WHERE id = ?", (task_id,)
            )
            row = cursor.fetchone()
            if row and (row[0] == "!drift") == has_drift:
                return  # no change
            if has_drift:
                self._conn.execute(
                    "UPDATE tasks SET external_updated_at = '!drift' WHERE id = ?", (task_id,)
                )
            else:
                self._conn.execute(
                    "UPDATE tasks SET external_updated_at = NULL WHERE id = ? AND external_updated_at = '!drift'",
                    (task_id,),
                )
            self._conn.commit()

    def set_mirror_toggle(self, task_id: int, mirror: bool) -> None:
        """Enable or disable mirroring for an existing task."""
        with self._lock:
            if mirror:
                self._conn.execute(
                    "UPDATE tasks SET mirror_to_remote = 1, mirror_pending = 1, updated_at = datetime('now') WHERE id = ?",
                    (task_id,),
                )
            else:
                self._conn.execute(
                    """UPDATE tasks SET mirror_to_remote = 0, mirror_pending = 0,
                       external_provider = NULL, external_id = NULL, external_updated_at = NULL,
                       updated_at = datetime('now') WHERE id = ?""",
                    (task_id,),
                )
            self._conn.commit()

    def update_task_due(
        self,
        task_id: int,
        due_at_utc: str | None,
        due_tz: str | None,
        is_full_day: bool,
        lead_time_minutes: int,
        recurrence_rule: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE tasks SET due_at_utc = ?, due_tz = ?, is_full_day = ?,
                   lead_time_minutes = ?, recurrence_rule = ?, reminder_fired = 0,
                   updated_at = datetime('now') WHERE id = ?""",
                (due_at_utc, due_tz, 1 if is_full_day else 0, lead_time_minutes,
                 recurrence_rule or None, task_id),
            )
            self._conn.commit()

    # Occurrence-related methods
    def add_occurrences(self, task_id: int, due_list: list[str]) -> None:
        """Bulk insert occurrence rows."""
        with self._lock:
            cursor = self._conn.cursor()
            for due_at_utc in due_list:
                cursor.execute(
                    """INSERT INTO occurrences (task_id, due_at_utc, fired, is_done, mirror_pending)
                       VALUES (?, ?, 0, 0, 0)""",
                    (task_id, due_at_utc),
                )
            self._conn.commit()

    def next_occurrence(self, task_id: int) -> Occurrence | None:
        """Get the earliest occurrence with fired=0."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT id, task_id, due_at_utc, fired, is_done, external_id, mirror_pending, created_at
                   FROM occurrences
                   WHERE task_id = ? AND fired = 0
                   ORDER BY due_at_utc LIMIT 1""",
                (task_id,),
            )
            row = cursor.fetchone()
            if row:
                return Occurrence(
                    id=row[0], task_id=row[1], due_at_utc=row[2], fired=row[3],
                    is_done=row[4], external_id=row[5], mirror_pending=row[6], created_at=row[7]
                )
            return None

    def last_materialized_due(self, task_id: int) -> str | None:
        """Get the max due_at_utc for a task (the last materialized occurrence)."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MAX(due_at_utc) FROM occurrences WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def list_occurrences(self, task_id: int) -> list[Occurrence]:
        """Get all occurrences for a task, ordered by due."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT id, task_id, due_at_utc, fired, is_done, external_id, mirror_pending, created_at
                   FROM occurrences
                   WHERE task_id = ?
                   ORDER BY due_at_utc""",
                (task_id,),
            )
            result = []
            for row in cursor.fetchall():
                result.append(Occurrence(
                    id=row[0], task_id=row[1], due_at_utc=row[2], fired=row[3],
                    is_done=row[4], external_id=row[5], mirror_pending=row[6], created_at=row[7]
                ))
            return result

    def mark_occurrence_fired(self, occ_id: int) -> None:
        """Mark an occurrence as fired."""
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET fired = 1 WHERE id = ?",
                (occ_id,),
            )
            self._conn.commit()

    def mark_occurrence_done(self, occ_id: int) -> None:
        """Mark an occurrence as done."""
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET is_done = 1 WHERE id = ?",
                (occ_id,),
            )
            self._conn.commit()

    def set_occurrence_external(self, occ_id: int, external_id: str | None, mirror_pending: int) -> None:
        """Set external_id and mirror_pending for an occurrence."""
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET external_id = ?, mirror_pending = ? WHERE id = ?",
                (external_id, mirror_pending, occ_id),
            )
            self._conn.commit()

    def list_unpushed_occurrences(self, task_id: int) -> list[Occurrence]:
        """Get occurrences with external_id IS NULL."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT id, task_id, due_at_utc, fired, is_done, external_id, mirror_pending, created_at
                   FROM occurrences
                   WHERE task_id = ? AND external_id IS NULL
                   ORDER BY due_at_utc""",
                (task_id,),
            )
            result = []
            for row in cursor.fetchall():
                result.append(Occurrence(
                    id=row[0], task_id=row[1], due_at_utc=row[2], fired=row[3],
                    is_done=row[4], external_id=row[5], mirror_pending=row[6], created_at=row[7]
                ))
            return result

    def delete_future_occurrences(self, task_id: int, after_utc: str) -> list[str]:
        """Delete occurrences with due_at_utc > after_utc, return list of deleted external_ids."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT external_id FROM occurrences WHERE task_id = ? AND due_at_utc > ? AND external_id IS NOT NULL",
                (task_id, after_utc),
            )
            external_ids = [row[0] for row in cursor.fetchall()]
            
            cursor.execute(
                "DELETE FROM occurrences WHERE task_id = ? AND due_at_utc > ?",
                (task_id, after_utc),
            )
            self._conn.commit()
            return external_ids

    def end_series(self, task_id: int) -> None:
        """Mark a recurring task series as ended."""
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET recurrence_active = 0 WHERE id = ?",
                (task_id,),
            )
            self._conn.commit()

    def count_done_occurrences(self, task_id: int) -> int:
        """Count how many occurrences are done."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM occurrences WHERE task_id = ? AND is_done = 1",
                (task_id,),
            )
            return cursor.fetchone()[0]

    def last_done_due(self, task_id: int) -> str | None:
        """Get the due_at_utc of the most recent done occurrence."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MAX(due_at_utc) FROM occurrences WHERE task_id = ? AND is_done = 1",
                (task_id,),
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None

    def set_recurrence(self, task_id: int, rrule: str | None, until: str | None) -> None:
        """Set recurrence info on a task."""
        with self._lock:
            self._conn.execute(
                """UPDATE tasks SET is_recurrence = ?, recurrence_rule = ?, recurrence_until = ?,
                   recurrence_active = 1, updated_at = datetime('now') WHERE id = ?""",
                (1 if rrule else 0, rrule, until, task_id),
            )
            self._conn.commit()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
