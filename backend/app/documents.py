"""Documents you can ask questions about: upload PDF/text, split into passages, find the relevant ones.

Retrieval is BM25 over passages, computed in memory. No embedding model or vector database is needed,
so it works offline and the ranking is easy to explain: passages that share rarer words with the
question score higher.
"""

from __future__ import annotations

import io
import math
import re
import sqlite3
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".log"}
CHUNK_CHARS = 900
MAX_CHUNKS_PER_DOC = 4000

STOPWORDS = frozenset(
    "a an and are as at be by for from has have how i in is it its of on or that the this to was were what when "
    "where which who why will with do does did can could should would about into than then there their they them "
    "me my we our you your not no yes if so but also any all some more most".split()
)
WORD = re.compile(r"[a-z0-9]+")


class DocumentError(ValueError):
    """The file can't be turned into searchable text."""


class DocumentNotFound(KeyError):
    pass


@dataclass
class DocumentInfo:
    id: int
    name: str
    pages: int
    chunks: int
    chars: int
    created_at: str


@dataclass
class Passage:
    chunk_id: int
    document_id: int
    document: str
    page: int
    text: str
    score: float = 0.0


def tokenize(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def extract_pages(filename: str, data: bytes) -> list[str]:
    """Return the text of each page (one 'page' for plain text files)."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ModuleNotFoundError as e:  # pragma: no cover - dependency is in requirements.txt
            raise DocumentError("PDF support needs the pypdf package.") from e
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentError("This PDF is password protected.")
            return [(page.extract_text() or "") for page in reader.pages]
        except DocumentError:
            raise
        except (PyPdfError, ValueError, OSError, KeyError) as e:
            raise DocumentError("That PDF could not be read. It may be damaged.") from e
    if suffix in TEXT_SUFFIXES:
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                return [data.decode(enc)]
            except UnicodeError:
                continue
    raise DocumentError("Upload a PDF, or a .txt, .md or .csv file.")


def chunk_page(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split a page into passages of about `size` characters, breaking on paragraph and sentence ends."""
    text = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    if not text:
        return []
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n|\n(?=[A-Z0-9•\-•])", text):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= size:
            pieces.append(para)
            continue
        pieces.extend(s for s in re.split(r"(?<=[.!?])\s+", para) if s)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        while len(piece) > size:  # one huge unbroken sentence
            cut = piece.rfind(" ", 0, size)
            if cut <= 0:
                cut = size
            chunks.append(piece[:cut])
            piece = piece[cut:].lstrip()
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


class DocumentStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._index: _Bm25 | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, pages INTEGER NOT NULL,
                    chars INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER NOT NULL, text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(document_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, filename: str, data: bytes) -> DocumentInfo:
        pages = extract_pages(filename, data)
        chunks = [(i, c) for i, text in enumerate(pages, start=1) for c in chunk_page(text)]
        if not chunks:
            raise DocumentError(
                "No text found in this file. If it is a scanned PDF, it needs OCR first; only text can be searched."
            )
        if len(chunks) > MAX_CHUNKS_PER_DOC:
            raise DocumentError("This document is too long. Split it into smaller files.")
        chars = sum(len(c) for _, c in chunks)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO documents (name, pages, chars, created_at) VALUES (?, ?, ?, ?)",
                (Path(filename).name, len(pages), chars, now),
            )
            doc_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO chunks (document_id, page, text) VALUES (?, ?, ?)",
                [(doc_id, page, text) for page, text in chunks],
            )
            self._index = None
        return DocumentInfo(doc_id, Path(filename).name, len(pages), len(chunks), chars, now)

    def list(self) -> list[DocumentInfo]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS n "
                "FROM documents d ORDER BY d.id DESC"
            ).fetchall()
        return [DocumentInfo(r["id"], r["name"], r["pages"], r["n"], r["chars"], r["created_at"]) for r in rows]

    def delete(self, doc_id: int) -> None:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            if cur.rowcount == 0:
                raise DocumentNotFound(doc_id)
            self._index = None

    def search(self, question: str, document_ids: list[int] | None = None, limit: int = 6) -> list[Passage]:
        with self._lock:
            if self._index is None:
                self._index = self._build()
            index = self._index
        return index.search(tokenize(question), set(document_ids) if document_ids else None, limit)

    def _build(self) -> _Bm25:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.id, c.document_id, d.name, c.page, c.text "
                "FROM chunks c JOIN documents d ON d.id = c.document_id"
            ).fetchall()
        return _Bm25([Passage(r["id"], r["document_id"], r["name"], r["page"], r["text"]) for r in rows])


class _Bm25:
    K1 = 1.5
    B = 0.75

    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self.terms = [Counter(tokenize(p.text)) for p in passages]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter[str] = Counter()
        for t in self.terms:
            df.update(t.keys())
        n = len(passages)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: list[str], only: set[int] | None, limit: int) -> list[Passage]:
        if not query:
            return []
        scored: list[Passage] = []
        for p, terms, length in zip(self.passages, self.terms, self.lengths):
            if only is not None and p.document_id not in only:
                continue
            score = 0.0
            for w in query:
                f = terms.get(w)
                if f:
                    score += self.idf[w] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * length / self.avg))
            if score > 0:
                scored.append(Passage(p.chunk_id, p.document_id, p.document, p.page, p.text, round(score, 3)))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
