"""Suggest a starter dashboard for a database: a handful of charts that say something about its data.

Two sources, same output. With an AI key the model proposes charts from the schema. Without one (or when the model
gives too few usable charts) a rule-based planner builds them from the column types. Every query is run through the
same read-only guard as any other, and charts that fail or come back empty are dropped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .database import DatabaseRegistry, QueryError
from .llm import LLMError, SQLGenerator
from .schemas import QueryResult, SchemaOut, TableOut
from .sql_guard import UnsafeSQLError

log = logging.getLogger(__name__)

MAX_WIDGETS = 6
DATE_TYPE = re.compile(r"date|time", re.I)
NUMBER_TYPE = re.compile(r"int|real|float|double|numeric|decimal|number|money", re.I)
TEXT_TYPE = re.compile(r"char|text|clob|string|enum", re.I)
RATE_NAME = re.compile(r"(price|rate|rating|score|percent|pct|discount|age|marks|grade)", re.I)
ID_NAME = re.compile(r"(^id$|_id$|_key$|_code$|^code$|zip|pin|phone|number$)", re.I)


@dataclass
class Widget:
    title: str
    sql: str
    note: str
    result: QueryResult


def q(dialect: str, name: str) -> str:
    """Quote an identifier for the dialect."""
    if dialect in ("mysql", "mariadb"):
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def month_of(dialect: str, col: str) -> str:
    if dialect == "postgresql":
        return f"to_char({col}, 'YYYY-MM')"
    if dialect in ("mysql", "mariadb"):
        return f"DATE_FORMAT({col}, '%Y-%m')"
    return f"strftime('%Y-%m', {col})"


def nice(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def plan_rules(schema: SchemaOut, dialect: str) -> list[tuple[str, str, str]]:
    """(title, sql, note) candidates built from the schema alone, most useful first."""
    tables = [t for t in schema.tables if t.kind == "table" and (t.row_count or 0) > 0]
    tables.sort(key=lambda t: t.row_count or 0, reverse=True)
    plans: list[tuple[str, str, str]] = []

    if len(tables) >= 2:
        union = " UNION ALL ".join(
            f"SELECT '{t.name.replace(chr(39), chr(39) * 2)}' AS table_name, "
            f"COUNT(*) AS records FROM {q(dialect, t.name)}"
            for t in tables[:8]
        )
        plans.append(("Records per table", f"SELECT * FROM ({union}) AS sizes ORDER BY records DESC",
                      "How big each table is."))

    # Interleave tables so the first few charts come from different parts of the database.
    per_table = [_table_plans(t, dialect) for t in tables[:6]]
    trends = 0
    for i in range(3):
        for p in per_table:
            if len(p) <= i:
                continue
            if p[i][0].endswith(" by month"):  # time charts all look alike; keep the two on the biggest tables
                trends += 1
                if trends > 2:
                    continue
            plans.append(p[i])
    return plans


def _table_plans(t: TableOut, dialect: str) -> list[tuple[str, str, str]]:
    tn = q(dialect, t.name)
    out: list[tuple[str, str, str]] = []
    cats = [c for c in t.columns if c.values and 2 <= len(c.values) <= 12 and not c.primary_key]
    measures = [
        c for c in t.columns
        if NUMBER_TYPE.search(c.type) and not c.primary_key and not c.foreign_key and not ID_NAME.search(c.name)
    ]
    dates = [c for c in t.columns if DATE_TYPE.search(c.type) or re.search(r"(_date|_at)$", c.name, re.I)]

    if cats:
        c = q(dialect, cats[0].name)
        out.append((f"{nice(t.name)} by {cats[0].name.replace('_', ' ')}",
                    f"SELECT {c}, COUNT(*) AS records FROM {tn} WHERE {c} IS NOT NULL "
                    f"GROUP BY {c} ORDER BY records DESC",
                    f"How {t.name} split across {cats[0].name}."))
    if cats and measures:
        c, m = q(dialect, cats[0].name), q(dialect, measures[0].name)
        mn, cn = measures[0].name, cats[0].name
        if RATE_NAME.search(mn):
            agg, label, note = "ROUND(AVG({}), 2)", "Average", f"The typical {mn} in {t.name} for each {cn}."
        else:
            agg, label, note = "SUM({})", "Total", f"Where the {mn} in {t.name} adds up."
        out.append((f"{label} {mn.replace('_', ' ')} by {cn.replace('_', ' ')}",
                    f"SELECT {c}, {agg.format(m)} AS value FROM {tn} WHERE {c} IS NOT NULL "
                    f"GROUP BY {c} ORDER BY value DESC LIMIT 12", note))

    if dates:
        d = q(dialect, dates[0].name)
        m = month_of(dialect, d)
        out.append((f"{nice(t.name)} by month",
                    f"SELECT {m} AS month, COUNT(*) AS records FROM {tn} "
                    f"WHERE {d} IS NOT NULL GROUP BY {m} ORDER BY {m}",
                    f"Records in {t.name} over time, by {dates[0].name}."))
    return out


def suggest(
    registry: DatabaseRegistry, db_id: str, generator: SQLGenerator | None, use_ai: bool, count: int = MAX_WIDGETS,
    blocked: frozenset[str] = frozenset(),
) -> tuple[list[Widget], str]:
    """Return (widgets, source) where source is 'ai' or 'rules'."""
    info = registry.get(db_id)
    schema = registry.schema(db_id)
    if blocked:
        schema = schema.model_copy(update={"tables": [t for t in schema.tables if t.name.lower() not in blocked]})
    widgets: list[Widget] = []
    source = "rules"

    if use_ai and generator is not None and hasattr(generator, "dashboard"):
        try:
            prompt = registry.schema_prompt(db_id, hide=blocked)
            ideas = generator.dashboard(dialect=info.dialect, schema=prompt, count=count)
        except LLMError as e:
            log.info("AI dashboard skipped: %s", e.message)
            ideas = []
        except Exception:  # noqa: BLE001 - fall back to rules instead of failing the page
            log.exception("AI dashboard failed")
            ideas = []
        widgets = _run(registry, db_id, [(i.title, i.sql, i.note) for i in ideas], count, blocked)
        if len(widgets) >= 2:
            source = "ai"

    if source != "ai":
        widgets = _run(registry, db_id, plan_rules(schema, info.dialect), count, blocked)
    return widgets, source


def _run(
    registry: DatabaseRegistry, db_id: str, plans: list[tuple[str, str, str]], count: int,
    blocked: frozenset[str] = frozenset(),
) -> list[Widget]:
    widgets: list[Widget] = []
    seen: set[str] = set()
    for title, sql, note in plans:
        if len(widgets) >= count:
            break
        try:
            cleaned, result = registry.execute(db_id, sql, blocked)
        except (UnsafeSQLError, QueryError) as e:
            log.info("Dropped suggested chart %r: %s", title, e)
            continue
        if result.row_count == 0 or cleaned in seen:
            continue
        seen.add(cleaned)
        widgets.append(Widget(title=title.strip()[:120], sql=cleaned, note=note.strip()[:200], result=result))
    return widgets
