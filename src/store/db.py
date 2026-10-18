"""SQLite persistence layer.

Stores the memory the pipeline needs across runs: chosen topics (for dedup),
run/attempt bookkeeping (for re-runs and versioning), and sent alerts.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.errors import StoreError

__all__ = ["Database"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT    NOT NULL,
    title      TEXT    NOT NULL,
    url        TEXT,
    score      REAL    NOT NULL DEFAULT 0,
    run_id     TEXT,
    created_at TEXT    NOT NULL,
    UNIQUE (category, title)
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    language      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'created',
    chosen_topic  TEXT,
    quality_score REAL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT    NOT NULL,
    attempt_no INTEGER NOT NULL,
    scope      TEXT    NOT NULL,
    reason     TEXT,
    status     TEXT    NOT NULL DEFAULT 'created',
    output_dir TEXT,
    created_at TEXT    NOT NULL,
    UNIQUE (run_id, attempt_no),
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT,
    checkpoint TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Thin wrapper around a SQLite connection (all errors -> :class:`StoreError`)."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _exec(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        try:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur
        except sqlite3.Error as exc:
            raise StoreError(f"sqlite error: {exc}") from exc

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]
        except sqlite3.Error as exc:
            raise StoreError(f"sqlite error: {exc}") from exc

    # ------------------------------------------------------------------ #
    # schema
    # ------------------------------------------------------------------ #
    def migrate(self) -> None:
        """Create tables if missing. Safe to call repeatedly."""
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StoreError(f"migration failed: {exc}") from exc

    def tables(self) -> list[str]:
        return [
            row["name"]
            for row in self._query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]

    # ------------------------------------------------------------------ #
    # topics
    # ------------------------------------------------------------------ #
    def add_topic(
        self,
        category: str,
        title: str,
        *,
        url: str | None = None,
        score: float = 0.0,
        run_id: str | None = None,
    ) -> bool:
        """Insert a topic; return False if it was already recorded (dedup)."""
        cur = self._exec(
            "INSERT OR IGNORE INTO topics "
            "(category, title, url, score, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (category, title, url, score, run_id, _now()),
        )
        return cur.rowcount > 0

    def topic_seen(self, category: str, title: str) -> bool:
        rows = self._query(
            "SELECT 1 FROM topics WHERE category = ? AND title = ? LIMIT 1",
            (category, title),
        )
        return bool(rows)

    def topics_for_category(self, category: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM topics WHERE category = ? ORDER BY score DESC, id ASC",
            (category,),
        )

    # ------------------------------------------------------------------ #
    # runs
    # ------------------------------------------------------------------ #
    def create_run(self, run_id: str, category: str, language: str) -> None:
        self._exec(
            "INSERT INTO runs (id, category, language, status, created_at) "
            "VALUES (?, ?, ?, 'created', ?)",
            (run_id, category, language, _now()),
        )

    def set_run_status(self, run_id: str, status: str) -> None:
        self._exec("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    def set_run_topic(self, run_id: str, topic: str) -> None:
        self._exec("UPDATE runs SET chosen_topic = ? WHERE id = ?", (topic, run_id))

    def set_run_quality(self, run_id: str, score: float) -> None:
        self._exec("UPDATE runs SET quality_score = ? WHERE id = ?", (score, run_id))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM runs WHERE id = ?", (run_id,))
        return rows[0] if rows else None

    # ------------------------------------------------------------------ #
    # attempts
    # ------------------------------------------------------------------ #
    def add_attempt(
        self,
        run_id: str,
        scope: str,
        *,
        reason: str | None = None,
        output_dir: str | None = None,
    ) -> int:
        """Append an attempt and return its 1-based attempt number."""
        row = self._query(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS n FROM attempts WHERE run_id = ?",
            (run_id,),
        )
        attempt_no = int(row[0]["n"])
        self._exec(
            "INSERT INTO attempts "
            "(run_id, attempt_no, scope, reason, status, output_dir, created_at) "
            "VALUES (?, ?, ?, ?, 'created', ?, ?)",
            (run_id, attempt_no, scope, reason, output_dir, _now()),
        )
        return attempt_no

    def attempts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY attempt_no ASC", (run_id,)
        )

    # ------------------------------------------------------------------ #
    # alerts
    # ------------------------------------------------------------------ #
    def record_alert(self, checkpoint: str, message: str, *, run_id: str | None = None) -> int:
        cur = self._exec(
            "INSERT INTO alerts (run_id, checkpoint, message, created_at) VALUES (?, ?, ?, ?)",
            (run_id, checkpoint, message, _now()),
        )
        return int(cur.lastrowid or 0)

    def alerts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM alerts WHERE run_id = ? ORDER BY id ASC", (run_id,))

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
