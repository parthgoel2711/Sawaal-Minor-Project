"""An append-only record of who did what: sign-ins, questions, SQL runs, uploads and changes.

Vanna calls this an audit logger. Each row says who, which role, what, on which database, how it ended, and a short
detail (the question, or the SQL). It is written for every request when auth is off too (as the user "local").
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT NOT NULL,
                    role TEXT NOT NULL, action TEXT NOT NULL, database_id TEXT, detail TEXT,
                    status TEXT NOT NULL, ip TEXT)""")
            conn.execute("CREATE INDEX IF NOT EXISTS audit_ts ON audit(id DESC)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, *, username: str, role: str, action: str, status: str = "ok", database_id: str | None = None,
            detail: str | None = None, ip: str | None = None) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO audit (ts, username, role, action, database_id, detail, status, ip) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, username, role, action, database_id, (detail or "")[:500] or None, status, ip))

    def list(self, limit: int = 200, action: str | None = None, username: str | None = None) -> list[dict]:
        where, args = [], []
        if action:
            where.append("action = ?")
            args.append(action)
        if username:
            where.append("username = ?")
            args.append(username)
        sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (*args, max(1, min(limit, 1000))))]
