"""Pydantic models for API requests and responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------- Databases & schema ----------


class DatabaseOut(BaseModel):
    id: str
    name: str
    kind: Literal["sample", "upload", "external"]
    dialect: str
    description: str = ""
    deletable: bool = False


class ColumnOut(BaseModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: str | None = None  # "other_table.column"
    values: list[str] | None = None  # distinct values for low-cardinality text columns


class TableOut(BaseModel):
    name: str
    kind: Literal["table", "view"] = "table"
    row_count: int | None = None
    columns: list[ColumnOut]
    ddl: str = ""
    sample_rows: list[list[Any]] = Field(default_factory=list)


class SchemaOut(BaseModel):
    database_id: str
    dialect: str
    tables: list[TableOut]


# ---------- Queries ----------


class QueryResult(BaseModel):
    columns: list[str]
    column_types: list[Literal["number", "text", "boolean", "empty"]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    masked_columns: list[str] = Field(default_factory=list)  # hidden because they hold personal data


class HistoryTurn(BaseModel):
    """A previous question/SQL pair, sent back so follow-up questions have context."""

    question: str = Field(max_length=4000)
    sql: str = Field(default="", max_length=20000)


class GenerateRequest(BaseModel):
    database_id: str
    question: str = Field(min_length=1, max_length=4000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)
    execute: bool = True
    # If the selected database can't answer, look for another database that can.
    auto_route: bool = True
    # Also write a plain-language answer and suggest follow-up questions (one extra, cheap AI call).
    insights: bool = True


class Attempt(BaseModel):
    sql: str
    error: str


class GenerateResponse(BaseModel):
    used_memory: int = 0  # saved examples and rules that were added to the prompt
    question: str
    database_id: str  # the database that was actually queried
    routed_from: str | None = None  # set when the selected database couldn't answer and another one did
    answerable: bool
    sql: str
    explanation: str
    result: QueryResult | None = None
    error: str | None = None
    attempts: list[Attempt] = Field(default_factory=list)  # failed attempts that Claude repaired
    history_id: int | None = None
    summary: str = ""  # plain-language answer based on the result rows
    followups: list[str] = Field(default_factory=list)  # suggested next questions


class ExecuteRequest(BaseModel):
    database_id: str
    sql: str = Field(min_length=1, max_length=20000)
    question: str | None = Field(default=None, max_length=4000)
    save_to_history: bool = True


class ExecuteResponse(BaseModel):
    sql: str
    result: QueryResult | None = None
    error: str | None = None
    history_id: int | None = None


# ---------- History ----------


class HistoryItem(BaseModel):
    id: int
    database_id: str
    question: str | None
    sql: str
    explanation: str | None
    row_count: int | None
    error: str | None
    source: Literal["ai", "manual"]
    starred: bool
    created_at: str


class HistoryUpdate(BaseModel):
    starred: bool


# ---------- Misc ----------


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    llm_enabled: bool
    provider: Literal["anthropic", "groq", "demo"] | None = None
    model: str
    max_rows: int
    version: str


# ---------- Data profile ----------


class ProfileColumn(BaseModel):
    name: str
    type: str
    nulls: int
    null_pct: float
    distinct: int
    min: Any = None
    max: Any = None
    flags: list[str] = Field(default_factory=list)  # e.g. "mostly empty", "constant", "unique"


class ProfileTable(BaseModel):
    name: str
    row_count: int
    columns: list[ProfileColumn]
    completeness: float  # % of cells that are not empty


class ProfileOut(BaseModel):
    database_id: str
    tables: list[ProfileTable]
    completeness: float
    issues: int  # columns with at least one data-quality flag


# ---------- Usage stats ----------


class DayCount(BaseModel):
    day: str
    count: int


class StatsOut(BaseModel):
    total: int
    ai: int
    manual: int
    failed: int
    repaired: int  # AI answers that needed automatic error repair
    avg_seconds: float | None  # average time to answer an AI question
    success_rate: float | None
    daily: list[DayCount]


# ---------- Explain ----------


class ExplainRequest(BaseModel):
    database_id: str
    sql: str = Field(min_length=1, max_length=20000)


class ExplainResponse(BaseModel):
    summary: str
    steps: list[str]


# ---------- connections, documents, auto-dashboard ----------

class ConnectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=500)


class DocumentOut(BaseModel):
    id: int
    name: str
    pages: int
    chunks: int
    chars: int
    created_at: str


class DocAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[int] | None = None  # None = search every document
    database_id: str | None = None  # also pull numbers from this database


class DocSource(BaseModel):
    n: int
    kind: Literal["document", "database"] = "document"
    document: str
    page: int | None = None
    text: str
    score: float = 0.0


class DocAskResponse(BaseModel):
    question: str
    answer: str | None = None  # None when AI is off: only the passages are returned
    found: bool = True
    sources: list[DocSource]
    sql: str | None = None


class AutoDashboardRequest(BaseModel):
    count: int = Field(default=6, ge=2, le=8)
    use_ai: bool = True


class AutoWidget(BaseModel):
    title: str
    sql: str
    note: str = ""
    result: QueryResult


class AutoDashboardResponse(BaseModel):
    database_id: str
    source: Literal["ai", "rules"]
    widgets: list[AutoWidget]


# ---------- agent memory ----------

class MemoryItemOut(BaseModel):
    id: int
    database_id: str
    kind: Literal["example", "note"]
    question: str | None = None
    sql: str | None = None
    text: str | None = None
    created_by: str
    created_at: str
    uses: int


class MemoryExampleIn(BaseModel):
    database_id: str
    question: str = Field(min_length=1, max_length=2000)
    sql: str = Field(min_length=1, max_length=20000)


class MemoryNoteIn(BaseModel):
    database_id: str
    text: str = Field(min_length=3, max_length=1000)


# ---------- sign-in ----------

class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)


class NewUser(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=200)
    role: Literal["viewer", "analyst", "admin"]
