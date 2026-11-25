"""Saved connections to real databases (PostgreSQL, MySQL, MariaDB).

Connection strings contain passwords, so they are stored encrypted (Fernet) in `data/connections.json`.
The key lives next to it in `data/.connection_key`, readable only by the owner.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.engine import URL, make_url

# What the user may type -> the driver we actually use.
DRIVERS = {
    "postgresql": "postgresql+psycopg",
    "postgres": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
    "mariadb": "mysql+pymysql",
}
ALLOWED_DRIVERS = {"postgresql+psycopg", "mysql+pymysql"}


class ConnectionError_(ValueError):  # noqa: N818 - avoids shadowing the builtin ConnectionError
    """The connection details are not usable."""


def normalize_url(raw: str) -> URL:
    """Parse a user-supplied URL and pick the right driver. Only PostgreSQL and MySQL are accepted:
    a SQLite URL would let a caller point the app at any file on this machine."""
    raw = (raw or "").strip()
    if not raw:
        raise ConnectionError_("Enter a connection URL.")
    try:
        url = make_url(raw)
    except Exception as e:
        raise ConnectionError_(
            "That doesn't look like a connection URL. Example: postgresql://user:password@host:5432/dbname"
        ) from e
    backend = url.drivername.split("+", 1)[0].lower()
    driver = DRIVERS.get(backend) if "+" not in url.drivername else url.drivername.lower()
    if driver not in ALLOWED_DRIVERS:
        raise ConnectionError_("Only PostgreSQL and MySQL/MariaDB connections are supported.")
    if not url.host:
        raise ConnectionError_("The URL needs a host name.")
    if not url.database:
        raise ConnectionError_("The URL needs a database name at the end, like /mydb.")
    return url.set(drivername=driver)


def display_url(url: URL) -> str:
    """The URL without the password, safe to show."""
    return url.render_as_string(hide_password=True)


@dataclass
class SavedConnection:
    name: str
    url: str  # full URL including the password


class ConnectionStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "connections.json"
        self.key_path = data_dir / ".connection_key"
        self._lock = threading.Lock()

    def _fernet(self) -> Fernet:
        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        return Fernet(self.key_path.read_bytes().strip())

    def _read(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, items: list[dict[str, str]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(items, f)
        tmp.replace(self.path)

    def list(self) -> list[SavedConnection]:
        f = self._fernet()
        out: list[SavedConnection] = []
        with self._lock:
            for item in self._read():
                try:
                    out.append(SavedConnection(item["name"], f.decrypt(item["token"].encode()).decode()))
                except (KeyError, InvalidToken):
                    continue  # key changed or file damaged: skip rather than crash
        return out

    def add(self, name: str, url: str) -> None:
        f = self._fernet()
        with self._lock:
            items = [i for i in self._read() if i.get("name") != name]
            items.append({"name": name, "token": f.encrypt(url.encode()).decode()})
            self._write(items)

    def remove(self, name: str) -> None:
        with self._lock:
            self._write([i for i in self._read() if i.get("name") != name])
