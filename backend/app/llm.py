"""Natural language -> SQL with Claude (Anthropic) or Groq.

Claude uses structured outputs so every response is JSON matching OUTPUT_SCHEMA,
and prompt caching on the system prompt (instructions + database schema), which
is identical for every question about the same database. Groq uses JSON mode
with the same prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import anthropic
import groq

from .config import Settings
from .schemas import HistoryTurn

log = logging.getLogger(__name__)

DIALECT_LABELS = {
    "sqlite": "SQLite",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mssql": "SQL Server (T-SQL)",
    "oracle": "Oracle",
    "duckdb": "DuckDB",
}

DIALECT_TIPS = {
    "sqlite": (
        "SQLite tips: dates are stored as ISO-8601 TEXT, so use strftime('%Y', col), "
        "strftime('%Y-%m', col), date(col, '-30 day') and date('now'). "
        "Use || for string concatenation and CAST(x AS REAL) to avoid integer division. "
        "There is no ILIKE (LIKE is already case-insensitive for ASCII)."
    ),
    "postgresql": (
        "PostgreSQL tips: use date_trunc('month', col), EXTRACT(YEAR FROM col), "
        "ILIKE for case-insensitive matching, and ::numeric before ROUND(x, 2)."
    ),
    "mysql": "MySQL tips: use DATE_FORMAT(col, '%Y-%m'), YEAR(col), CONCAT(a, b) and backtick-quoted identifiers.",
}

SYSTEM_TEMPLATE = """\
You are an expert data analyst. You turn questions about a {dialect} database into one correct, \
efficient SQL query, and you explain the result in plain language.

<schema>
{schema}
</schema>

How to write the query:
- Write exactly one read-only query: SELECT, or WITH ... SELECT. Never write statements that change data or schema; they are blocked anyway.
- Use only the tables and columns in the schema above. Quote identifiers that contain spaces, capitals or reserved words.
- Use {dialect} syntax and functions. {tips}
- Join tables on their foreign keys. Give every computed column a short, readable alias (e.g. total_revenue).
- Round money and averages to 2 decimal places. Use the known column values listed in the schema for filters (match their exact spelling and case).
- For "top N", "most", "highest" or "lowest" questions, sort the results and add a LIMIT. Otherwise return all matching rows; the app limits how many rows it displays.
- Questions about trends over time should return one row per period, ordered by period.
- If a question is ambiguous (e.g. what counts as revenue, whether cancelled orders count), choose the most sensible business interpretation and mention it in the explanation.

When the question can't be answered:
- If the schema doesn't contain the data needed, or the message isn't a question about this data, set answerable to false, leave sql empty, and use the explanation to say briefly what the database does contain.

The explanation:
- One to three short sentences for a non-technical reader: what the query returns and any assumptions you made. Don't restate the SQL.
- Write it in the same language the user wrote the question in.
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answerable": {
            "type": "boolean",
            "description": "False if the question can't be answered from this database.",
        },
        "sql": {
            "type": "string",
            "description": "A single read-only SQL query, or an empty string if not answerable.",
        },
        "explanation": {
            "type": "string",
            "description": "Plain-language summary of what the query returns and any assumptions.",
        },
    },
    "required": ["answerable", "sql", "explanation"],
    "additionalProperties": False,
}

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Claude could not produce SQL. `status_code` is what the API route should return."""

    def __init__(self, message: str, status_code: int = 502, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable  # worth retrying with a different model


@dataclass
class Generation:
    answerable: bool
    sql: str
    explanation: str
    # Full assistant content blocks, passed back unchanged when asking Claude to repair a query.
    raw_content: Any = field(default=None, repr=False)


@dataclass
class Failure:
    generation: Generation
    error: str


class SQLGenerator(Protocol):
    def generate(
        self,
        *,
        dialect: str,
        schema: str,
        question: str,
        history: list[HistoryTurn],
        failures: list[Failure],
        context: str = "",
    ) -> Generation: ...

    def route(self, *, question: str, catalog: str) -> str | None:
        """Return the id of the database (from `catalog`) that can answer `question`, or None."""
        ...

    def insight(self, *, question: str, sql: str, columns: list[str], rows: list[list[Any]],
                row_count: int) -> Insight:
        """Explain a query result in plain language and suggest follow-up questions."""
        ...

    def explain(self, *, dialect: str, schema: str, sql: str) -> Explanation:
        """Explain what a SQL query does, step by step."""
        ...

    def dashboard(self, *, dialect: str, schema: str, count: int) -> list[ChartIdea]:
        """Propose starter charts for a database."""
        ...

    def answer_documents(self, *, question: str, passages: list[str], data_context: str | None) -> DocAnswer:
        """Answer from document passages, citing them by number."""
        ...


ROUTE_SYSTEM = """\
You decide which database can answer a question. Each database is listed with its id, a short \
description, and its tables and columns. Pick the one whose tables hold the data the question needs. \
The question may be in English, Hindi or Hinglish. If none of the databases has that data, pick none.
Reply with only a JSON object: {"database_id": "<id>"}, or {"database_id": ""} if none fits."""

ROUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"database_id": {"type": "string", "description": "Database id, or empty string if none fits."}},
    "required": ["database_id"],
    "additionalProperties": False,
}


def route_message(question: str, catalog: str) -> str:
    return f"Databases:\n{catalog}\n\nQuestion: {question}"


def _error_detail(e: Exception) -> str:
    """The human-readable message inside an API error body, without the SDK's wrapper text."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(err.get("message"), str):
            return err["message"]
    return str(getattr(e, "message", e))


def parse_answer(text: str) -> dict[str, Any]:
    """Parse the model's JSON answer, tolerating code fences or reasoning text around it."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("The AI returned a malformed answer. Try again.", 502) from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            raise LLMError("The AI returned a malformed answer. Try again.", 502) from None
    if not isinstance(data, dict):
        raise LLMError("The AI returned a malformed answer. Try again.", 502)
    return data


def _to_generation(data: dict[str, Any], raw_content: Any) -> Generation:
    return Generation(
        answerable=bool(data.get("answerable")),
        sql=str(data.get("sql") or "").strip(),
        explanation=str(data.get("explanation") or "").strip(),
        raw_content=raw_content,
    )


def build_system_prompt(dialect: str, schema: str) -> str:
    label = DIALECT_LABELS.get(dialect, dialect)
    return SYSTEM_TEMPLATE.format(dialect=label, schema=schema, tips=DIALECT_TIPS.get(dialect, ""))


def build_user_message(question: str, history: list[HistoryTurn], today: date | None = None, context: str = "") -> str:
    parts = []
    if context:
        parts.append(context)
        parts.append("")
    if history:
        parts.append("Earlier in this conversation (the new question may refer to these):")
        for i, turn in enumerate(history, start=1):
            parts.append(f"{i}. Question: {turn.question}")
            if turn.sql:
                parts.append(f"   SQL: {turn.sql}")
        parts.append("")
    parts.append(f"Today's date: {(today or date.today()).isoformat()}")
    parts.append(f"Question: {question}")
    return "\n".join(parts)


def repair_message(error: str) -> str:
    return (
        "Running that query against the database failed with this error:\n"
        f"{error}\n\n"
        "Write a corrected query that answers the same question."
    )


INSIGHT_SYSTEM = """\
You are a data analyst explaining a query result to a non-technical reader. You get the user's question, the SQL \
that was run, and the result rows (possibly only the first rows of a longer result).
Write:
- "summary": one to three sentences that directly answer the question using the real numbers in the result \
(name the top item, the total, the trend). Never invent numbers that are not in the result. If the result is only a \
sample of more rows, say so. Write in the same language as the question.
- "followups": exactly three short, natural follow-up questions the user could ask next about the same data, \
each answerable with one SQL query. Do not repeat the original question.
Reply with only a JSON object: {"summary": "...", "followups": ["...", "...", "..."]}"""

INSIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Plain-language answer based on the result."},
        "followups": {"type": "array", "items": {"type": "string"}, "description": "Three follow-up questions."},
    },
    "required": ["summary", "followups"],
    "additionalProperties": False,
}

INSIGHT_MAX_ROWS = 25
INSIGHT_MAX_CELL = 60


@dataclass
class Insight:
    summary: str = ""
    followups: list[str] = field(default_factory=list)


def insight_message(question: str, sql: str, columns: list[str], rows: list[list[Any]], row_count: int) -> str:
    """A compact text version of a query result for the insight prompt."""

    def cell(v: Any) -> str:
        text = "NULL" if v is None else str(v).replace("\n", " ")
        return text if len(text) <= INSIGHT_MAX_CELL else text[: INSIGHT_MAX_CELL - 1] + "…"

    shown = rows[:INSIGHT_MAX_ROWS]
    lines = [" | ".join(columns)] + [" | ".join(cell(v) for v in row) for row in shown]
    note = f"Showing the first {len(shown)} of {row_count} rows." if row_count > len(shown) else f"{row_count} row(s)."
    return f"Question: {question}\n\nSQL:\n{sql}\n\nResult ({note}):\n" + "\n".join(lines)


def to_insight(data: dict[str, Any]) -> Insight:
    raw = data.get("followups")
    followups = [str(q).strip() for q in raw if str(q).strip()] if isinstance(raw, list) else []
    return Insight(summary=str(data.get("summary") or "").strip(), followups=followups[:3])


EXPLAIN_SYSTEM = """\
You explain SQL to someone who is learning it. You get a {dialect} query and the database schema it runs on.
Write:
- "summary": one or two plain sentences saying what question the query answers.
- "steps": between two and six short steps in the order the database does the work (which tables are read, how \
they are joined, what is filtered, grouped, sorted or limited). Use plain words and name the real tables and columns.
Reply with only a JSON object: {{"summary": "...", "steps": ["...", "..."]}}

<schema>
{schema}
</schema>"""

EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "steps"],
    "additionalProperties": False,
}


@dataclass
class Explanation:
    summary: str = ""
    steps: list[str] = field(default_factory=list)


def to_explanation(data: dict[str, Any]) -> Explanation:
    raw = data.get("steps")
    steps = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []
    return Explanation(summary=str(data.get("summary") or "").strip(), steps=steps[:8])


def explain_system(dialect: str, schema: str) -> str:
    return EXPLAIN_SYSTEM.format(dialect=DIALECT_LABELS.get(dialect, dialect), schema=schema)


DASHBOARD_SYSTEM = """\
You design a starter dashboard for a database. You get the {dialect} schema. Propose {count} charts that together \
give a good first picture of the data: totals, a trend over time if there is a date column, the biggest categories, \
and one comparison. For each chart write:
- "title": a short plain title (no trailing period).
- "sql": one read-only {dialect} SELECT that returns a category or time column first and one or two numeric columns, \
with at most 20 rows, and column aliases that read like labels.
- "note": one short sentence on what the chart shows.
Use only tables and columns from the schema. Reply with only a JSON object: \
{{"charts": [{{"title": "...", "sql": "...", "note": "..."}}]}}

<schema>
{schema}
</schema>"""

DASHBOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "charts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "sql": {"type": "string"}, "note": {"type": "string"}},
                "required": ["title", "sql", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["charts"],
    "additionalProperties": False,
}


@dataclass
class ChartIdea:
    title: str
    sql: str
    note: str = ""


def to_chart_ideas(data: dict[str, Any]) -> list[ChartIdea]:
    raw = data.get("charts")
    out: list[ChartIdea] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and str(item.get("sql") or "").strip() and str(item.get("title") or "").strip():
            out.append(ChartIdea(str(item["title"]).strip(), str(item["sql"]).strip(), str(item.get("note") or "").strip()))
    return out


def dashboard_system(dialect: str, schema: str, count: int) -> str:
    return DASHBOARD_SYSTEM.format(dialect=DIALECT_LABELS.get(dialect, dialect), schema=schema, count=count)


DOCS_SYSTEM = """\
You answer questions using only the numbered passages you are given, which come from the user's documents \
(and sometimes a database result). Rules:
- Answer in a few plain sentences. Do not use knowledge from outside the passages.
- After each claim, cite the passage numbers it came from like [1] or [2][3].
- If the passages do not contain the answer, set "found" to false and say briefly what is missing.
Reply with only a JSON object: {"answer": "...", "found": true}"""

DOCS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "found": {"type": "boolean"}},
    "required": ["answer", "found"],
    "additionalProperties": False,
}


@dataclass
class DocAnswer:
    answer: str
    found: bool = True


def docs_message(question: str, passages: list[str], data_context: str | None) -> str:
    parts = [f"[{i}] {text}" for i, text in enumerate(passages, start=1)]
    if data_context:
        parts.append(f"[{len(passages) + 1}] Database result: {data_context}")
    return "Passages:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"


def to_doc_answer(data: dict[str, Any]) -> DocAnswer:
    return DocAnswer(answer=str(data.get("answer") or "").strip(), found=bool(data.get("found", True)))


class ClaudeSQLGenerator:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.settings = settings
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            kwargs: dict[str, Any] = {"timeout": 180.0, "max_retries": 2}
            if self.settings.anthropic_api_key:
                kwargs["api_key"] = self.settings.anthropic_api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def generate(
        self,
        *,
        dialect: str,
        schema: str,
        question: str,
        history: list[HistoryTurn],
        failures: list[Failure],
        context: str = "",
    ) -> Generation:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_user_message(question, history, context=context)}
        ]
        for failure in failures:
            messages.append({"role": "assistant", "content": failure.generation.raw_content})
            messages.append({"role": "user", "content": repair_message(failure.error)})

        system = [{"type": "text", "text": build_system_prompt(dialect, schema), "cache_control": {"type": "ephemeral"}}]
        text, content = self._create(
            system=system, messages=messages, effort=self.settings.claude_effort, schema=OUTPUT_SCHEMA,
            max_tokens=16000,
        )
        return _to_generation(parse_answer(text), content)

    def route(self, *, question: str, catalog: str) -> str | None:
        text, _ = self._create(
            system=ROUTE_SYSTEM, messages=[{"role": "user", "content": route_message(question, catalog)}],
            effort="low", schema=ROUTE_SCHEMA, max_tokens=4000,
        )
        return str(parse_answer(text).get("database_id") or "").strip() or None

    def insight(self, *, question: str, sql: str, columns: list[str], rows: list[list[Any]],
                row_count: int) -> Insight:
        text, _ = self._create(
            system=INSIGHT_SYSTEM,
            messages=[{"role": "user", "content": insight_message(question, sql, columns, rows, row_count)}],
            effort="low", schema=INSIGHT_SCHEMA, max_tokens=4000,
        )
        return to_insight(parse_answer(text))

    def explain(self, *, dialect: str, schema: str, sql: str) -> Explanation:
        text, _ = self._create(
            system=[{"type": "text", "text": explain_system(dialect, schema), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"Explain this query:\n\n{sql}"}],
            effort="low", schema=EXPLAIN_SCHEMA, max_tokens=4000,
        )
        return to_explanation(parse_answer(text))

    def dashboard(self, *, dialect: str, schema: str, count: int) -> list[ChartIdea]:
        text, _ = self._create(
            system=[{"type": "text", "text": dashboard_system(dialect, schema, count), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "Propose the charts."}],
            effort="low", schema=DASHBOARD_SCHEMA, max_tokens=8000,
        )
        return to_chart_ideas(parse_answer(text))

    def answer_documents(self, *, question: str, passages: list[str], data_context: str | None) -> DocAnswer:
        text, _ = self._create(
            system=DOCS_SYSTEM, messages=[{"role": "user", "content": docs_message(question, passages, data_context)}],
            effort="low", schema=DOCS_SCHEMA, max_tokens=4000,
        )
        return to_doc_answer(parse_answer(text))

    def _create(self, *, system: Any, messages: list[dict[str, Any]], effort: str, schema: dict[str, Any],
                max_tokens: int) -> tuple[str, Any]:
        """Call Claude with a JSON-schema answer format; return (answer text, content blocks)."""
        params: dict[str, Any] = {
            "model": self.settings.claude_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        if self.settings.use_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"

        try:
            response = self.client.beta.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise LLMError("The Claude API key was rejected. Check ANTHROPIC_API_KEY in your .env file.", 502) from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f"The Claude API key doesn't have access to this model: {e.message}", 502) from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Model '{self.settings.claude_model}' was not found. Check CLAUDE_MODEL.", 502) from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude is rate limiting requests right now. Wait a moment and try again.", 429) from e
        except anthropic.BadRequestError as e:
            detail = _error_detail(e)
            if "credit balance" in detail.lower():
                raise LLMError(
                    "Your Anthropic account is out of credits. Add credits in the Anthropic Console "
                    "(Plans & Billing), then try again.",
                    402,
                ) from e
            raise LLMError(f"Claude rejected the request: {detail}", 502) from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error ({e.status_code}). Try again shortly.", 502) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Couldn't reach the Claude API. Check your internet connection.", 502) from e

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined to answer this question. Try rephrasing it.", 422)
        if response.stop_reason == "max_tokens":
            raise LLMError("Claude's answer was cut off. Try a simpler or more specific question.", 502)

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("Claude returned no answer. Try again.", 502)

        usage = response.usage
        log.info(
            "claude model=%s input=%s cache_read=%s output=%s",
            response.model, usage.input_tokens, getattr(usage, "cache_read_input_tokens", None),
            usage.output_tokens,
        )
        return text, response.content


JSON_INSTRUCTION = """
Reply with only a JSON object and no other text, in exactly this shape:
{"answerable": true, "sql": "SELECT ...", "explanation": "..."}
"""


class GroqSQLGenerator:
    """Uses Groq's API (free tier available) with open models such as gpt-oss or Llama."""

    def __init__(self, settings: Settings, client: groq.Groq | None = None, patient_retries: int = 2):
        self.settings = settings
        self._client = client
        self.patient_retries = patient_retries

    @property
    def client(self) -> groq.Groq:
        if self._client is None:
            self._client = groq.Groq(
                api_key=self.settings.groq_api_key or os.environ.get("GROQ_API_KEY"),
                timeout=120.0,
            )
        return self._client

    def generate(
        self,
        *,
        dialect: str,
        schema: str,
        question: str,
        history: list[HistoryTurn],
        failures: list[Failure],
        context: str = "",
    ) -> Generation:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(dialect, schema) + JSON_INSTRUCTION},
            {"role": "user", "content": build_user_message(question, history, context=context)},
        ]
        for failure in failures:
            messages.append({"role": "assistant", "content": failure.generation.raw_content})
            messages.append({"role": "user", "content": repair_message(failure.error)})

        data, text = self._complete_json(messages)
        return _to_generation(data, text)

    def route(self, *, question: str, catalog: str) -> str | None:
        messages = [
            {"role": "system", "content": ROUTE_SYSTEM},
            {"role": "user", "content": route_message(question, catalog)},
        ]
        data, _ = self._complete_json(messages, max_tokens=2048)
        return str(data.get("database_id") or "").strip() or None

    def insight(self, *, question: str, sql: str, columns: list[str], rows: list[list[Any]],
                row_count: int) -> Insight:
        messages = [
            {"role": "system", "content": INSIGHT_SYSTEM},
            {"role": "user", "content": insight_message(question, sql, columns, rows, row_count)},
        ]
        data, _ = self._complete_json(messages, max_tokens=2048)
        return to_insight(data)

    def explain(self, *, dialect: str, schema: str, sql: str) -> Explanation:
        messages = [
            {"role": "system", "content": explain_system(dialect, schema)},
            {"role": "user", "content": f"Explain this query:\n\n{sql}"},
        ]
        data, _ = self._complete_json(messages, max_tokens=2048)
        return to_explanation(data)

    def dashboard(self, *, dialect: str, schema: str, count: int) -> list[ChartIdea]:
        messages = [
            {"role": "system", "content": dashboard_system(dialect, schema, count)},
            {"role": "user", "content": "Propose the charts."},
        ]
        data, _ = self._complete_json(messages, max_tokens=4096)
        return to_chart_ideas(data)

    def answer_documents(self, *, question: str, passages: list[str], data_context: str | None) -> DocAnswer:
        messages = [
            {"role": "system", "content": DOCS_SYSTEM},
            {"role": "user", "content": docs_message(question, passages, data_context)},
        ]
        data, _ = self._complete_json(messages, max_tokens=2048)
        return to_doc_answer(data)

    def _models(self) -> list[str]:
        models = [self.settings.groq_model]
        fallback = self.settings.groq_fallback_model
        if fallback and fallback != self.settings.groq_model:
            models.append(fallback)
        return models

    def _complete_json(self, messages: list[dict[str, Any]], max_tokens: int = 8192) -> tuple[dict[str, Any], str]:
        """Ask for a JSON answer. If the main model is rate-limited, down, or answers badly, switch to the
        fallback model right away (each Groq model has its own free-tier limit). Only if every model is
        rate-limited, make one patient attempt that waits for the limit to reset."""
        models = self._models()
        last_error: LLMError | None = None
        for model in models:
            try:
                return self._complete_once(model, messages, max_tokens, retries=0)
            except LLMError as e:
                if not e.retryable:
                    raise
                last_error = e
                log.warning("groq model %s failed (%s)", model, e.message)
        assert last_error is not None
        if last_error.status_code == 429 and self.patient_retries > 0:
            log.info("all groq models are rate-limited; waiting for the limit to reset")
            return self._complete_once(models[0], messages, max_tokens, retries=self.patient_retries)
        raise last_error

    def _complete_once(self, model: str, messages: list[dict[str, Any]], max_tokens: int,
                       retries: int) -> tuple[dict[str, Any], str]:
        try:
            # The SDK honours the Retry-After header when it retries a rate-limited request.
            response = self.client.with_options(max_retries=retries).chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_completion_tokens=max_tokens,
            )
        except groq.AuthenticationError as e:
            raise LLMError("The Groq API key was rejected. Check GROQ_API_KEY in your .env file.", 502) from e
        except groq.NotFoundError as e:
            raise LLMError(f"Groq model '{model}' was not found. Check GROQ_MODEL.", 502, retryable=True) from e
        except groq.RateLimitError as e:
            raise LLMError("Groq's free-tier limit was reached. Wait a minute and try again.", 429,
                           retryable=True) from e
        except groq.BadRequestError as e:
            detail = _error_detail(e)
            if "json" in detail.lower():
                raise LLMError("The AI returned a malformed answer. Try again or rephrase the question.", 502,
                               retryable=True) from e
            raise LLMError(f"Groq rejected the request: {detail}", 502) from e
        except groq.APIStatusError as e:
            raise LLMError(f"Groq API error ({e.status_code}). Try again shortly.", 502,
                           retryable=e.status_code >= 500) from e
        except groq.APIConnectionError as e:
            raise LLMError("Couldn't reach the Groq API. Check your internet connection.", 502) from e

        if not response.choices:
            raise LLMError("The AI returned no answer. Try again.", 502, retryable=True)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise LLMError("The AI's answer was cut off. Try a simpler or more specific question.", 502,
                           retryable=True)
        text = choice.message.content or ""
        try:
            data = parse_answer(text)
        except LLMError as e:
            e.retryable = True
            raise
        if response.usage:
            log.info("groq model=%s input=%s output=%s",
                     response.model, response.usage.prompt_tokens, response.usage.completion_tokens)
        return data, text


def make_generator(settings: Settings) -> SQLGenerator:
    """Build the generator for the configured provider."""
    if settings.provider == "demo":
        from .demo import DemoGenerator

        return DemoGenerator()
    if settings.provider == "groq":
        return GroqSQLGenerator(settings)
    return ClaudeSQLGenerator(settings)
