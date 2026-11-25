"""Optional sign-in, roles and a per-role table restriction.

Turned on with AUTH_ENABLED=true. Three roles, from least to most able:

* viewer: ask questions and read answers. Cannot read tables listed in RESTRICTED_TABLES.
* analyst: everything a viewer can, plus teach the app, add documents, upload files and pin charts.
* admin: everything, including connecting databases, managing users and reading the audit log.

With auth off, everyone is a local admin so the app works out of the box.
Passwords are hashed with scrypt. Sessions are random tokens in an HttpOnly cookie; only their hash is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROLES = ("viewer", "analyst", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
COOKIE = "sawaal_session"
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str

    def can(self, role: str) -> bool:
        return RANK[self.role] >= RANK[role]


LOCAL_ADMIN = User(0, "local", "admin")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def required_role(method: str, path: str) -> str | None:
    """The lowest role allowed to call this endpoint, or None when it is public."""
    if path in ("/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me"):
        return None
    if path.startswith(("/api/users", "/api/audit")):
        return "admin"
    if path == "/api/databases/connect" or (method == "DELETE" and path.startswith("/api/databases/")):
        return "admin"
    if method == "GET" or path in ("/api/generate", "/api/generate/stream", "/api/execute", "/api/explain",
                                   "/api/documents/ask") or path.endswith("/auto-dashboard"):
        return "viewer"
    return "analyst"  # uploads, teaching, documents, pins and other changes


class AuthError(Exception):
    """Wrong username/password, or too many attempts."""


class UserStore:
    def __init__(self, path: Path, session_hours: int = 12):
        self.path = path
        self.session_hours = session_hours
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL);"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def list(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id")]

    def create(self, username: str, password: str, role: str) -> User:
        if not USERNAME.match(username or ""):
            raise ValueError("Usernames are 3 to 32 letters, numbers, dots, dashes or underscores.")
        if role not in RANK:
            raise ValueError("Role must be viewer, analyst or admin.")
        if len(password or "") < 8:
            raise ValueError("The password needs at least 8 characters.")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), role, now))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"The username {username} is already taken.") from e
            return User(int(cur.lastrowid), username, role)

    def delete(self, user_id: int) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return False
            if row["role"] == "admin" and conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] <= 1:
                raise ValueError("The last admin cannot be deleted.")
            return conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount > 0

    def login(self, username: str, password: str) -> tuple[User, str]:
        """Check the password and open a session. The same error for an unknown user and a wrong password."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username or "",)).fetchone()
        stored = row["password_hash"] if row else hash_password("not-a-real-password")  # keep timing similar
        ok = verify_password(password or "", stored)
        if not row or not ok:
            raise AuthError("Wrong username or password.")
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(UTC) + timedelta(hours=self.session_hours)).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                         (hashlib.sha256(token.encode()).hexdigest(), row["id"], expires))
        return User(row["id"], row["username"], row["role"]), token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT u.id, u.username, u.role, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or row["expires_at"] < datetime.now(UTC).isoformat(timespec="seconds"):
            return None
        return User(row["id"], row["username"], row["role"])

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
