"""Agent memory: what the app has been taught about a database, used to make later answers better.

Two kinds of knowledge, both kept per database:

* examples: a question together with SQL a person confirmed was right. When a similar question comes in later,
  the closest examples are shown to the model, so it copies the team's own table joins and spellings.
* notes: plain-language business rules ("an active customer ordered in the last 90 days", "revenue means
  quantity * unit_price after discount"). Notes are shown to the model with every question on that database.

This is the idea behind Vanna's training data and agent memory, built to be small and inspectable: everything is
a row in one SQLite table that a person can read, edit and delete in the Training page.
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .documents import tokenize

Kind = Literal["example", "note"]
MAX_NOTES_IN_PROMPT = 8
MAX_EXAMPLES_IN_PROMPT = 3


@dataclass
class MemoryItem:
    id: int
    database_id: str
    kind: Kind
    question: str | None
    sql: str | None
    text: str | None
    created_by: str
    created_at: str
    uses: int


@dataclass
class Recall:
    examples: list[MemoryItem] = field(default_factory=list)
    notes: list[MemoryItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.examples) + len(self.notes)

    def to_prompt(self) -> str:
        """The text added to the model's input. Empty when there is nothing relevant."""
        parts: list[str] = []
        if self.notes:
            parts.append("Rules and definitions this team uses (follow them):")
            parts.extend(f"- {n.text}" for n in self.notes)
        if self.examples:
            if parts:
                parts.append("")
            parts.append("Similar questions that were answered correctly before (reuse their approach if it fits):")
            for e in self.examples:
                parts.append(f"Question: {e.question}")
                parts.append(f"SQL: {e.sql}")
        return "\n".join(parts)


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def rank(query: str, texts: list[str]) -> list[tuple[int, float]]:
    """BM25 score of each text for the query; only texts that share a word with the query are returned."""
    q = tokenize(query)
    if not q or not texts:
        return []
    docs = [Counter(tokenize(t)) for t in texts]
    lengths = [sum(d.values()) or 1 for d in docs]
    avg = sum(lengths) / len(lengths)
    n = len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    out: list[tuple[int, float]] = []
    for i, d in enumerate(docs):
        score = 0.0
        for w in q:
            f = d.get(w)
            if f:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                score += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * lengths[i] / avg))
        if score > 0:
            out.append((i, score))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


class AgentMemory:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, database_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('example', 'note')),
                    question TEXT, sql TEXT, text TEXT,
                    created_by TEXT NOT NULL DEFAULT 'local', created_at TEXT NOT NULL,
                    uses INTEGER NOT NULL DEFAULT 0)"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS memory_db ON memory(database_id, kind)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _item(r: sqlite3.Row) -> MemoryItem:
        return MemoryItem(r["id"], r["database_id"], r["kind"], r["question"], r["sql"], r["text"],
                          r["created_by"], r["created_at"], r["uses"])

    def list(self, database_id: str | None = None) -> list[MemoryItem]:
        sql = "SELECT * FROM memory" + (" WHERE database_id = ?" if database_id else "") + " ORDER BY id DESC"
        with self._connect() as conn:
            return [self._item(r) for r in conn.execute(sql, (database_id,) if database_id else ())]

    def add_example(self, database_id: str, question: str, sql: str, user: str = "local") -> MemoryItem:
        """Save a confirmed question/SQL pair. The same pair saved twice is kept once."""
        question, sql = question.strip(), sql.strip().rstrip(";").strip()
        with self._lock, self._connect() as conn:
            for r in conn.execute(
                "SELECT * FROM memory WHERE database_id = ? AND kind = 'example'", (database_id,)
            ):
                if _norm(r["question"] or "") == _norm(question) and _norm(r["sql"] or "") == _norm(sql):
                    return self._item(r)
            now = datetime.now(UTC).isoformat(timespec="seconds")
            cur = conn.execute(
                "INSERT INTO memory (database_id, kind, question, sql, created_by, created_at) "
                "VALUES (?, 'example', ?, ?, ?, ?)", (database_id, question, sql, user, now))
            return self._item(conn.execute("SELECT * FROM memory WHERE id = ?", (cur.lastrowid,)).fetchone())

    def add_note(self, database_id: str, text: str, user: str = "local") -> MemoryItem:
        text = " ".join(text.split())
        with self._lock, self._connect() as conn:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            cur = conn.execute(
                "INSERT INTO memory (database_id, kind, text, created_by, created_at) VALUES (?, 'note', ?, ?, ?)",
                (database_id, text, user, now))
            return self._item(conn.execute("SELECT * FROM memory WHERE id = ?", (cur.lastrowid,)).fetchone())

    def delete(self, item_id: int) -> bool:
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM memory WHERE id = ?", (item_id,)).rowcount > 0

    def forget_database(self, database_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM memory WHERE database_id = ?", (database_id,))

    def recall(self, database_id: str, question: str) -> Recall:
        """The notes and examples most relevant to `question` on this database."""
        items = self.list(database_id)
        examples = [i for i in items if i.kind == "example"]
        notes = [i for i in items if i.kind == "note"]
        best_examples = [examples[i] for i, _ in rank(question, [e.question or "" for e in examples])
                         [:MAX_EXAMPLES_IN_PROMPT]]
        # Notes are rules: keep the ones that match the question first, then the newest, up to a small cap.
        matched = [notes[i] for i, _ in rank(question, [n.text or "" for n in notes])]
        rest = [n for n in notes if n not in matched]
        chosen_notes = (matched + rest)[:MAX_NOTES_IN_PROMPT]
        used = best_examples + chosen_notes
        if used:
            with self._lock, self._connect() as conn:
                conn.executemany("UPDATE memory SET uses = uses + 1 WHERE id = ?", [(i.id,) for i in used])
        return Recall(examples=best_examples, notes=chosen_notes)
