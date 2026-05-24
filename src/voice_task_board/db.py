from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
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

    def add_task(self, title: str, category_name: str, description: str = "") -> int:
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
                "INSERT INTO tasks (title, description, category_id) VALUES (?, ?, ?)",
                (title, description, category_id),
            )
            self._conn.commit()
            return cast(int, cursor.lastrowid)

    def create_task(self, title: str, category_id: int, description: str = "") -> int:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "INSERT INTO tasks (title, description, category_id) VALUES (?, ?, ?)",
                (title, description, category_id),
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

    def list_tasks(self) -> list[Task]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """SELECT tasks.id, tasks.title, tasks.description, tasks.category_id, categories.name,
                          tasks.status, tasks.created_at, tasks.updated_at
                   FROM tasks JOIN categories ON tasks.category_id = categories.id
                   ORDER BY tasks.created_at DESC"""
            )
            return [
                Task(
                    id=int(row[0]),
                    title=row[1],
                    description=row[2] or "",
                    category_id=int(row[3]),
                    category_name=row[4],
                    status=row[5],
                    created_at=row[6],
                    updated_at=row[7],
                )
                for row in cursor.fetchall()
            ]

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


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
