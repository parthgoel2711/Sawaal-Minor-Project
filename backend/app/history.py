"""Query history, stored in a small SQLite file (data/app.db)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .schemas import DayCount, HistoryItem, StatsOut

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    database_id  TEXT NOT NULL,
    question     TEXT,
    sql          TEXT NOT NULL,
    explanation  TEXT,
    row_count    INTEGER,
    error        TEXT,
    source       TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
    starred      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_db ON history(database_id, id DESC);
"""

MAX_ENTRIES = 500  # oldest un-starred entries are pruned beyond this


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            existing = {r["name"] for r in conn.execute("PRAGMA table_info(history)")}
            for column, ddl in (("repairs", "INTEGER NOT NULL DEFAULT 0"), ("elapsed_ms", "REAL")):
                if column not in existing:  # databases created by an older version
                    conn.execute(f"ALTER TABLE history ADD COLUMN {column} {ddl}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _to_item(row: sqlite3.Row) -> HistoryItem:
        return HistoryItem(
            id=row["id"],
            database_id=row["database_id"],
            question=row["question"],
            sql=row["sql"],
            explanation=row["explanation"],
            row_count=row["row_count"],
            error=row["error"],
            source=row["source"],
            starred=bool(row["starred"]),
            created_at=row["created_at"],
        )

    def add(
        self,
        *,
        database_id: str,
        sql: str,
        source: str,
        question: str | None = None,
        explanation: str | None = None,
        row_count: int | None = None,
        error: str | None = None,
        repairs: int = 0,
        elapsed_ms: float | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO history (database_id, question, sql, explanation, row_count, error, source, created_at, "
                "repairs, elapsed_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (database_id, question, sql, explanation, row_count, error, source, now, repairs, elapsed_ms),
            )
            conn.execute(
                "DELETE FROM history WHERE starred = 0 AND id NOT IN "
                "(SELECT id FROM history ORDER BY id DESC LIMIT ?)",
                (MAX_ENTRIES,),
            )
            return int(cur.lastrowid)

    def list(self, database_id: str | None = None, starred_only: bool = False, limit: int = 100) -> list[HistoryItem]:
        clauses, args = [], []
        if database_id:
            clauses.append("database_id = ?")
            args.append(database_id)
        if starred_only:
            clauses.append("starred = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM history {where} ORDER BY id DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [self._to_item(r) for r in rows]

    def get(self, item_id: int) -> HistoryItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM history WHERE id = ?", (item_id,)).fetchone()
        return self._to_item(row) if row else None

    def set_starred(self, item_id: int, starred: bool) -> HistoryItem | None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE history SET starred = ? WHERE id = ?", (int(starred), item_id))
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM history WHERE id = ?", (item_id,)).rowcount > 0

    def clear(self, database_id: str | None = None, keep_starred: bool = True) -> int:
        clauses, args = [], []
        if database_id:
            clauses.append("database_id = ?")
            args.append(database_id)
        if keep_starred:
            clauses.append("starred = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock, self._connect() as conn:
            return conn.execute(f"DELETE FROM history {where}", args).rowcount

    def stats(self, database_id: str | None = None, days: int = 14) -> StatsOut:
        where, args = ("WHERE database_id = ?", [database_id]) if database_id else ("", [])
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total, "
                f"COALESCE(SUM(source = 'ai'), 0) AS ai, COALESCE(SUM(source = 'manual'), 0) AS manual, "
                f"COALESCE(SUM(error IS NOT NULL), 0) AS failed, "
                f"COALESCE(SUM(source = 'ai' AND repairs > 0), 0) AS repaired, "
                f"AVG(CASE WHEN source = 'ai' THEN elapsed_ms END) AS avg_ms "
                f"FROM history {where}", args).fetchone()
            by_day = {
                r["day"]: r["n"]
                for r in conn.execute(
                    f"SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM history {where} GROUP BY day", args)
            }
        today = datetime.now(UTC).date()
        daily = [
            DayCount(day=(d := (today - timedelta(days=i)).isoformat()), count=by_day.get(d, 0))
            for i in range(days - 1, -1, -1)
        ]
        total = row["total"]
        return StatsOut(
            total=total, ai=row["ai"], manual=row["manual"], failed=row["failed"], repaired=row["repaired"],
            avg_seconds=round(row["avg_ms"] / 1000, 1) if row["avg_ms"] else None,
            success_rate=round(1 - row["failed"] / total, 3) if total else None,
            daily=daily,
        )
