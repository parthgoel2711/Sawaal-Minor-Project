"""Database registry: discovers databases, introspects schemas and runs read-only queries."""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Literal

from sqlalchemy import create_engine, func, inspect, literal_column, select, table
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from .config import Settings
from .connections import ConnectionError_, ConnectionStore, display_url, normalize_url
from .importer import UploadError, check_sqlite_file, import_csv, slugify
from .schemas import (
    ColumnOut,
    DatabaseOut,
    ProfileColumn,
    ProfileOut,
    ProfileTable,
    QueryResult,
    SchemaOut,
    TableOut,
)
from .seed import SAMPLE_DATABASES
from .sql_guard import UnsafeSQLError, referenced_tables, to_sqlglot_dialect, validate_read_only

log = logging.getLogger(__name__)

SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
CSV_EXTENSIONS = {".csv", ".tsv", ".txt"}
SAMPLE_ROWS_PER_TABLE = 3
MAX_DISTINCT_VALUES = 12
MAX_CELL_CHARS_IN_PROMPT = 60


class DatabaseNotFound(KeyError):
    pass


class QueryError(Exception):
    """A query failed to run (bad SQL, timeout, database error)."""


@dataclass
class DatabaseInfo:
    id: str
    name: str
    kind: Literal["sample", "upload", "external"]
    dialect: str
    description: str = ""
    path: Path | None = None  # SQLite file
    url: str | None = None  # external SQLAlchemy URL (never sent to clients)
    saved: bool = False  # connected from the app (stored encrypted) rather than set in .env

    def to_out(self) -> DatabaseOut:
        return DatabaseOut(
            id=self.id,
            name=self.name,
            kind=self.kind,
            dialect=self.dialect,
            description=self.description,
            deletable=self.kind == "upload" or self.saved,
        )


def _sqlite_read_only_engine(path: Path) -> Engine:
    uri = path.resolve().as_uri() + "?mode=ro"

    def creator() -> sqlite3.Connection:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA trusted_schema = OFF")
        return conn

    # NullPool: no file handles stay open, so uploaded files can be deleted on Windows.
    return create_engine("sqlite://", creator=creator, poolclass=NullPool)


PERSONAL_COLUMN = re.compile(
    r"(^|_)(e?mail|phone|mobile|contact_no|password|passwd|pwd|aadhaar|aadhar|ssn|passport|pan_?(no|number)?|"
    r"card_?(no|number)|cvv|iban|account_?(no|number))($|_)",
    re.IGNORECASE,
)


def mask_personal_data(columns: list[str], rows: list[list[Any]]) -> list[str]:
    """Hide values in columns that look like personal data (in place). Returns the hidden column names."""
    hidden = [i for i, name in enumerate(columns) if PERSONAL_COLUMN.search(name)]
    for i in hidden:
        for row in rows:
            v = row[i]
            if v is None:
                continue
            text = str(v)
            if "@" in text:
                local, _, domain = text.partition("@")
                row[i] = f"{local[:1]}•••@{domain}"
            else:
                row[i] = "•••" + text[-2:] if len(text) > 4 else "••••"
    return [columns[i] for i in hidden]


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _column_type(values: list[Any]) -> Literal["number", "text", "boolean", "empty"]:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "empty"
    if all(isinstance(v, bool) for v in non_null):
        return "boolean"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "number"
    return "text"


class DatabaseRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._dbs: dict[str, DatabaseInfo] = {}
        self._engines: dict[str, Engine] = {}
        self._schemas: dict[str, SchemaOut] = {}
        self._prompts: dict[str, str] = {}
        self.connections = ConnectionStore(settings.data_dir)

    # ---------- discovery ----------

    def refresh(self) -> None:
        s = self.settings
        dbs: dict[str, DatabaseInfo] = {}

        for sample in SAMPLE_DATABASES:
            sample_path = s.sample_dir / f"{sample.id}.db"
            if sample_path.exists():
                dbs[sample.id] = DatabaseInfo(
                    id=sample.id,
                    name=sample.name,
                    kind="sample",
                    dialect="sqlite",
                    description=sample.description,
                    path=sample_path,
                )

        for name, url in s.external_databases().items():
            db_id = self._unique_id(slugify(name, "db"), dbs)
            try:
                dialect = create_engine(url).dialect.name
            except Exception as e:  # bad URL or missing driver
                log.warning("Skipping external database %r: %s", name, e)
                continue
            dbs[db_id] = DatabaseInfo(
                id=db_id, name=name, kind="external", dialect=dialect, url=url,
                description=f"External {dialect} database",
            )

        for saved in self.connections.list():
            try:
                url = normalize_url(saved.url)
            except ConnectionError_ as e:
                log.warning("Skipping saved connection %r: %s", saved.name, e)
                continue
            db_id = self._unique_id(slugify(saved.name, "db"), dbs)
            dbs[db_id] = DatabaseInfo(
                id=db_id, name=saved.name, kind="external", dialect=url.get_backend_name(),
                url=url.render_as_string(hide_password=False), saved=True,
                description=f"Connected {url.get_backend_name()} database ({display_url(url)})",
            )

        if s.uploads_dir.exists():
            for path in sorted(s.uploads_dir.glob("*.db")):
                db_id = path.stem
                if db_id in dbs:
                    continue
                dbs[db_id] = DatabaseInfo(
                    id=db_id, name=path.stem, kind="upload", dialect="sqlite",
                    description="Uploaded database", path=path,
                )

        with self._lock:
            stale = set(self._dbs) - set(dbs)
            for db_id in stale:
                self._forget(db_id)
            self._dbs = dbs

    @staticmethod
    def _unique_id(base: str, taken: dict[str, Any] | set[str]) -> str:
        db_id, n = base, 1
        while db_id in taken:
            n += 1
            db_id = f"{base}_{n}"
        return db_id

    def _forget(self, db_id: str) -> None:
        engine = self._engines.pop(db_id, None)
        if engine is not None:
            engine.dispose()
        self._schemas.pop(db_id, None)
        self._prompts.pop(db_id, None)

    def list(self) -> list[DatabaseInfo]:
        with self._lock:
            order = {"sample": 0, "upload": 1, "external": 2}
            return sorted(self._dbs.values(), key=lambda d: (order[d.kind], d.name.lower()))

    def get(self, db_id: str) -> DatabaseInfo:
        with self._lock:
            info = self._dbs.get(db_id)
        if info is None:
            raise DatabaseNotFound(db_id)
        return info

    def engine(self, db_id: str) -> Engine:
        info = self.get(db_id)
        with self._lock:
            engine = self._engines.get(db_id)
            if engine is None:
                if info.dialect == "sqlite" and info.path is not None:
                    engine = _sqlite_read_only_engine(info.path)
                else:
                    engine = create_engine(info.url, pool_pre_ping=True, pool_size=2, max_overflow=2)
                self._engines[db_id] = engine
            return engine

    # ---------- schema ----------

    def schema(self, db_id: str) -> SchemaOut:
        with self._lock:
            cached = self._schemas.get(db_id)
        if cached is not None:
            return cached
        info = self.get(db_id)
        schema = self._introspect(info)
        with self._lock:
            self._schemas[db_id] = schema
        return schema

    def _introspect(self, info: DatabaseInfo) -> SchemaOut:
        engine = self.engine(info.id)
        insp = inspect(engine)
        is_sqlite = info.dialect == "sqlite"

        original_ddl: dict[str, str] = {}
        if is_sqlite:
            with engine.connect() as conn:
                for name, sql in conn.exec_driver_sql(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'"
                ):
                    if sql:
                        original_ddl[name] = sql.strip()

        entries = [(n, "table") for n in insp.get_table_names()]
        entries += [(n, "view") for n in insp.get_view_names()]

        tables: list[TableOut] = []
        with engine.connect() as conn:
            for name, kind in entries:
                tables.append(self._describe_table(conn, insp, name, kind, is_sqlite, original_ddl))
        return SchemaOut(database_id=info.id, dialect=info.dialect, tables=tables)

    def _describe_table(self, conn: Connection, insp, name: str, kind: str, is_sqlite: bool,
                        original_ddl: dict[str, str]) -> TableOut:
        try:
            raw_cols = insp.get_columns(name)
        except SQLAlchemyError:
            raw_cols = []
        pk_cols: set[str] = set()
        fk_map: dict[str, str] = {}
        if kind == "table":
            try:
                pk_cols = set(insp.get_pk_constraint(name).get("constrained_columns") or [])
                for fk in insp.get_foreign_keys(name):
                    for local, remote in zip(fk["constrained_columns"], fk["referred_columns"]):
                        fk_map[local] = f"{fk['referred_table']}.{remote}"
            except SQLAlchemyError:
                pass

        tbl = table(name)
        row_count: int | None = None
        sample_rows: list[list[Any]] = []
        try:
            row_count = conn.execute(select(func.count()).select_from(tbl)).scalar()
            rows = conn.execute(
                select(literal_column("*")).select_from(tbl).limit(SAMPLE_ROWS_PER_TABLE)
            ).fetchall()
            sample_rows = [[to_jsonable(v) for v in r] for r in rows]
        except SQLAlchemyError as e:
            log.info("Could not sample %s: %s", name, e)
        finally:
            conn.rollback()

        columns: list[ColumnOut] = []
        for c in raw_cols:
            col_type = str(c["type"]) if c.get("type") is not None else ""
            values = None
            if (is_sqlite and kind == "table" and row_count and self._looks_textual(col_type)
                    and c["name"] not in pk_cols):
                values = self._distinct_values(conn, name, c["name"])
                # List values of categorical columns (values repeat) and of small lookup tables
                # (e.g. exam names), but not names/ids in bigger tables.
                if values and row_count < 2 * len(values) and row_count > MAX_DISTINCT_VALUES:
                    values = None
            columns.append(ColumnOut(
                name=c["name"],
                type=col_type or "ANY",
                nullable=bool(c.get("nullable", True)),
                primary_key=c["name"] in pk_cols,
                foreign_key=fk_map.get(c["name"]),
                values=values,
            ))

        ddl = original_ddl.get(name) or self._synthesize_ddl(name, kind, columns)
        return TableOut(name=name, kind=kind, row_count=row_count, columns=columns,
                        ddl=ddl, sample_rows=sample_rows)

    @staticmethod
    def _looks_textual(col_type: str) -> bool:
        t = col_type.upper()
        return t == "" or any(k in t for k in ("CHAR", "TEXT", "CLOB", "STRING"))

    @staticmethod
    def _distinct_values(conn: Connection, table_name: str, column: str) -> list[str] | None:
        quoted_t = '"' + table_name.replace('"', '""') + '"'
        quoted_c = '"' + column.replace('"', '""') + '"'
        try:
            rows = conn.exec_driver_sql(
                f"SELECT DISTINCT {quoted_c} FROM {quoted_t} WHERE {quoted_c} IS NOT NULL "
                f"LIMIT {MAX_DISTINCT_VALUES + 1}"
            ).fetchall()
        except SQLAlchemyError:
            return None
        if not rows or len(rows) > MAX_DISTINCT_VALUES:
            return None
        values = [str(r[0]) for r in rows]
        if any(len(v) > 40 for v in values):
            return None
        return sorted(values)

    @staticmethod
    def _synthesize_ddl(name: str, kind: str, columns: list[ColumnOut]) -> str:
        if kind == "view":
            return f"-- VIEW {name}({', '.join(c.name for c in columns)})"
        lines = []
        for c in columns:
            parts = [f"  {c.name} {c.type}"]
            if c.primary_key:
                parts.append("PRIMARY KEY")
            if not c.nullable and not c.primary_key:
                parts.append("NOT NULL")
            if c.foreign_key:
                ref_table, ref_col = c.foreign_key.rsplit(".", 1)
                parts.append(f"REFERENCES {ref_table}({ref_col})")
            lines.append(" ".join(parts))
        return f"CREATE TABLE {name} (\n" + ",\n".join(lines) + "\n)"

    def schema_prompt(self, db_id: str, hide: frozenset[str] = frozenset()) -> str:
        """Compact, LLM-friendly description of the schema (DDL + sample rows + known values).
        Tables named in `hide` are left out, so a restricted user's questions never even see them."""
        if not hide:
            with self._lock:
                cached = self._prompts.get(db_id)
            if cached is not None:
                return cached
        schema = self.schema(db_id)
        parts: list[str] = []
        for t in schema.tables:
            if t.name.lower() in hide:
                continue
            block = [t.ddl.rstrip(";") + ";"]
            if t.row_count is not None:
                block.append(f"-- {t.row_count} rows")
            for c in t.columns:
                if c.values:
                    vals = ", ".join(f"'{v}'" for v in c.values)
                    block.append(f"-- {t.name}.{c.name} values: {vals}")
            if t.sample_rows:
                block.append("-- sample rows (" + ", ".join(c.name for c in t.columns) + "):")
                for row in t.sample_rows:
                    cells = []
                    for v in row:
                        s = repr(v) if isinstance(v, str) else str(v)
                        if len(s) > MAX_CELL_CHARS_IN_PROMPT:
                            s = s[:MAX_CELL_CHARS_IN_PROMPT] + "…"
                        cells.append(s)
                    block.append("--   (" + ", ".join(cells) + ")")
            parts.append("\n".join(block))
        prompt = "\n\n".join(parts)
        if not hide:
            with self._lock:
                self._prompts[db_id] = prompt
        return prompt

    def catalog_text(self, exclude: str | None = None, max_tables: int = 40, max_columns: int = 20) -> str:
        """Short description of every database (id, about, tables and columns), used to pick
        which database can answer a question."""
        blocks = []
        for info in self.list():
            if info.id == exclude:
                continue
            try:
                schema = self.schema(info.id)
            except Exception as e:  # an unreachable external database shouldn't break routing
                log.info("Skipping %s in catalog: %s", info.id, e)
                continue
            tables = "; ".join(
                f"{t.name}({', '.join(c.name for c in t.columns[:max_columns])})" for t in schema.tables[:max_tables]
            )
            blocks.append(f"- id: {info.id}\n  name: {info.name}\n  about: {info.description}\n  tables: {tables}")
        return "\n".join(blocks)

    # ---------- execution ----------

    def execute(
        self, db_id: str, sql: str, blocked_tables: frozenset[str] = frozenset()
    ) -> tuple[str, QueryResult]:
        """Validate and run `sql` read-only. Returns (cleaned_sql, result).

        Raises UnsafeSQLError for disallowed SQL and QueryError for runtime failures.
        """
        info = self.get(db_id)
        cleaned = validate_read_only(sql, to_sqlglot_dialect(info.dialect))
        if blocked_tables:
            denied = sorted(referenced_tables(cleaned, to_sqlglot_dialect(info.dialect)) & blocked_tables)
            if denied:
                raise QueryError(f"Your account is not allowed to read the table {', '.join(denied)}.")
        engine = self.engine(db_id)
        max_rows = self.settings.max_rows
        timeout = self.settings.query_timeout_seconds

        start = time.perf_counter()
        try:
            with engine.connect().execution_options(no_parameters=True) as conn:
                try:
                    self._prepare_connection(conn, info.dialect, timeout)
                    result = conn.exec_driver_sql(cleaned)
                    if not result.returns_rows:
                        raise QueryError("The statement did not return any rows.")
                    columns = list(result.keys())
                    raw_rows = result.fetchmany(max_rows + 1)
                finally:
                    self._reset_connection(conn, info.dialect)
                    conn.rollback()
        except DBAPIError as e:
            message = str(e.orig) if e.orig is not None else str(e)
            if "interrupted" in message.lower() or "statement timeout" in message.lower() \
                    or "max_execution_time" in message.lower():
                raise QueryError(f"The query took longer than {timeout:g}s and was stopped.") from e
            raise QueryError(message) from e
        except SQLAlchemyError as e:
            raise QueryError(str(e)) from e
        elapsed_ms = (time.perf_counter() - start) * 1000

        truncated = len(raw_rows) > max_rows
        rows = [[to_jsonable(v) for v in r] for r in raw_rows[:max_rows]]
        masked = mask_personal_data(columns, rows) if self.settings.mask_pii else []
        column_types = [_column_type([r[i] for r in rows]) for i in range(len(columns))]
        return cleaned, QueryResult(
            columns=columns,
            column_types=column_types,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=round(elapsed_ms, 2),
            masked_columns=masked,
        )

    # ---------- data profile ----------

    def profile(self, db_id: str, max_tables: int = 30, max_columns: int = 40) -> ProfileOut:
        """Per-column data quality: empty values, distinct values, range. Plain SQL, no AI."""
        info = self.get(db_id)
        quote = self.engine(db_id).dialect.identifier_preparer.quote
        tables: list[ProfileTable] = []
        for tbl in self.schema(db_id).tables[:max_tables]:
            cols = tbl.columns[:max_columns]
            if not cols:
                continue
            parts = ["COUNT(*) AS n"]
            for i, c in enumerate(cols):
                q = quote(c.name)
                parts += [f"COUNT({q}) AS nn{i}", f"COUNT(DISTINCT {q}) AS d{i}",
                          f"MIN({q}) AS lo{i}", f"MAX({q}) AS hi{i}"]
            try:
                _, res = self.execute(db_id, f"SELECT {', '.join(parts)} FROM {quote(tbl.name)}")
            except (QueryError, UnsafeSQLError) as e:
                log.info("Profile skipped %s.%s: %s", db_id, tbl.name, e)
                continue
            row = dict(zip(res.columns, res.rows[0]))
            n = int(row["n"] or 0)
            out_cols: list[ProfileColumn] = []
            for i, c in enumerate(cols):
                nulls = n - int(row[f"nn{i}"] or 0)
                distinct = int(row[f"d{i}"] or 0)
                flags = []
                if n and nulls / n >= 0.5:
                    flags.append("mostly empty")
                if n > 1 and distinct <= 1 and nulls < n:
                    flags.append("constant")
                if n > 1 and distinct == n and nulls == 0:
                    flags.append("unique")
                out_cols.append(ProfileColumn(
                    name=c.name, type=c.type, nulls=nulls, null_pct=round(100 * nulls / n, 1) if n else 0.0,
                    distinct=distinct, min=row[f"lo{i}"], max=row[f"hi{i}"], flags=flags,
                ))
            cells = n * len(out_cols)
            filled = sum(n - c.nulls for c in out_cols)
            tables.append(ProfileTable(name=tbl.name, row_count=n, columns=out_cols,
                                       completeness=round(100 * filled / cells, 1) if cells else 100.0))
        cells = sum(t.row_count * len(t.columns) for t in tables)
        filled = sum(t.row_count * len(t.columns) * t.completeness / 100 for t in tables)
        issues = sum(1 for t in tables for c in t.columns if set(c.flags) & {"mostly empty", "constant"})
        return ProfileOut(database_id=info.id, tables=tables, issues=issues,
                          completeness=round(100 * filled / cells, 1) if cells else 100.0)

    @staticmethod
    def _prepare_connection(conn: Connection, dialect: str, timeout: float) -> None:
        ms = int(timeout * 1000)
        if dialect == "sqlite":
            raw = conn.connection.driver_connection
            deadline = time.monotonic() + timeout
            raw.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        elif dialect == "postgresql":
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {ms}")
        elif dialect in ("mysql", "mariadb"):
            conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {ms}")
            conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")

    @staticmethod
    def _reset_connection(conn: Connection, dialect: str) -> None:
        if dialect == "sqlite":
            try:
                conn.connection.driver_connection.set_progress_handler(None, 0)
            except Exception:
                pass

    # ---------- uploads ----------

    def add_upload(self, filename: str, stream: BinaryIO, target_db: str | None = None) -> DatabaseInfo:
        """Store an uploaded SQLite file, or import a CSV into a new or existing uploaded database."""
        suffix = Path(filename).suffix.lower()
        if suffix not in SQLITE_EXTENSIONS | CSV_EXTENSIONS:
            raise UploadError("Upload a SQLite database (.db, .sqlite, .sqlite3) or a CSV file (.csv, .tsv).")

        uploads = self.settings.uploads_dir
        uploads.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=uploads, suffix=".part")
        tmp = Path(tmp_name)
        try:
            limit = self.settings.max_upload_mb * 1024 * 1024
            size = 0
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise UploadError(f"File is larger than {self.settings.max_upload_mb} MB.")
                    out.write(chunk)
            if size == 0:
                raise UploadError("The uploaded file is empty.")

            stem = slugify(Path(filename).stem, fallback="upload")
            if suffix in SQLITE_EXTENSIONS:
                if target_db:
                    raise UploadError("SQLite files are added as a new database, not merged into another one.")
                check_sqlite_file(tmp)
                db_id = self._unique_id(stem, self._taken_ids())
                dest = uploads / f"{db_id}.db"
                os.replace(tmp, dest)
            elif target_db:
                info = self.get(target_db)
                if info.kind != "upload" or info.path is None:
                    raise UploadError("CSV files can only be added to databases you uploaded.")
                with self._lock:
                    self._forget(target_db)  # release cached engine before writing
                import_csv(tmp, info.path, stem)
                db_id = target_db
            else:
                db_id = self._unique_id(stem, self._taken_ids())
                dest = uploads / f"{db_id}.db"
                building = uploads / f"{db_id}.building"
                try:
                    import_csv(tmp, building, stem)
                    os.replace(building, dest)
                finally:
                    if building.exists():
                        building.unlink()
        finally:
            if tmp.exists():
                tmp.unlink()

        self.refresh()
        with self._lock:
            self._forget(db_id)  # make sure the schema is re-read
        return self.get(db_id)

    def _taken_ids(self) -> set[str]:
        with self._lock:
            taken = set(self._dbs)
        if self.settings.uploads_dir.exists():
            taken |= {p.stem for p in self.settings.uploads_dir.glob("*.db")}
        return taken

    def add_connection(self, name: str, raw_url: str) -> DatabaseInfo:
        """Connect to a PostgreSQL/MySQL database, check it works, and remember it (encrypted)."""
        name = (name or "").strip()
        if not name:
            raise ConnectionError_("Give the connection a name.")
        if any(d.name.lower() == name.lower() for d in self.list()):
            raise ConnectionError_(f"A database called \u201c{name}\u201d already exists. Choose another name.")
        url = normalize_url(raw_url)
        self._probe(url)
        self.connections.add(name, url.render_as_string(hide_password=False))
        self.refresh()
        return next(d for d in self.list() if d.name == name)

    @staticmethod
    def _probe(url) -> None:
        """Open one connection and run SELECT 1, with a short timeout, so a bad URL fails here and not later."""
        engine = create_engine(url, connect_args=_connect_timeout(url.get_backend_name()), pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
        except ModuleNotFoundError as e:
            raise ConnectionError_(f"The database driver is not installed: {e.name}.") from e
        except SQLAlchemyError as e:
            msg = str(getattr(e, "orig", None) or e).strip().splitlines()[0]
            raise ConnectionError_(f"Could not connect: {msg}") from e
        finally:
            engine.dispose()

    def delete_connection(self, db_id: str) -> None:
        info = self.get(db_id)
        if not info.saved:
            raise UploadError("Only databases you connected from the app can be removed here.")
        with self._lock:
            self._forget(db_id)
        self.connections.remove(info.name)
        self.refresh()

    def delete_upload(self, db_id: str) -> None:
        info = self.get(db_id)
        if info.kind != "upload" or info.path is None:
            raise UploadError("Only uploaded databases can be deleted.")
        with self._lock:
            self._forget(db_id)
        for p in (info.path, info.path.with_name(info.path.name + "-wal"),
                  info.path.with_name(info.path.name + "-shm")):
            if p.exists():
                p.unlink()
        self.refresh()


def _connect_timeout(backend: str) -> dict[str, int]:
    return {"connect_timeout": 8}
