"""The question -> SQL -> result pipeline, with automatic query repair and database routing."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .config import Settings
from .database import DatabaseRegistry, QueryError
from .llm import Failure, LLMError, SQLGenerator
from .memory import AgentMemory
from .schemas import Attempt, GenerateRequest, GenerateResponse, HistoryTurn
from .sql_guard import UnsafeSQLError, to_sqlglot_dialect, validate_read_only

log = logging.getLogger(__name__)


Emit = Callable[[str, dict], None]


def _noop(_event: str, _data: dict) -> None:
    pass


def answer_question(
    req: GenerateRequest,
    registry: DatabaseRegistry,
    generator: SQLGenerator,
    settings: Settings,
    memory: AgentMemory | None = None,
    blocked: frozenset[str] = frozenset(),
    emit: Emit = _noop,
    user: str = "local",
) -> GenerateResponse:
    """Answer on the selected database. If it doesn't have the data, find another database that does.

    `memory` adds taught examples and rules to the prompt, `blocked` lists tables this user may not read, and
    `emit` receives progress events (used by the streaming endpoint)."""
    emit("status", {"message": "Reading your tables"})
    response = _answer_on(req.database_id, req.question, req.history, req.execute, registry, generator, settings,
                          memory, blocked, emit)
    if not response.answerable and req.auto_route and settings.auto_route:
        target = _pick_other_database(req, registry, generator)
        if target is not None:
            emit("status", {"message": f"Looking in {registry.get(target).name} instead"})
            routed = _answer_on(target, req.question, [], req.execute, registry, generator, settings,
                                memory, blocked, emit)
            if routed.answerable:
                routed.routed_from = req.database_id
                response = routed
    if req.insights and response.result is not None:
        emit("status", {"message": "Writing the summary"})
        add_insight(response, generator)
    return response


def add_insight(response: GenerateResponse, generator: SQLGenerator) -> None:
    """Attach a plain-language summary and follow-up questions. Never fails the answer itself."""
    insight = getattr(generator, "insight", None)
    result = response.result
    if insight is None or not response.answerable or response.error or result is None or not result.rows:
        return
    try:
        out = insight(question=response.question, sql=response.sql, columns=result.columns,
                      rows=result.rows, row_count=result.row_count)
    except LLMError as e:
        log.info("Insight skipped: %s", e.message)
        return
    except Exception:  # noqa: BLE001 - a bad insight must never hide a correct answer
        log.exception("Insight failed")
        return
    response.summary = out.summary
    response.followups = out.followups


def _pick_other_database(req: GenerateRequest, registry: DatabaseRegistry, generator: SQLGenerator) -> str | None:
    others = {d.id for d in registry.list() if d.id != req.database_id}
    if not others:
        return None
    catalog = registry.catalog_text(exclude=req.database_id)
    if not catalog:
        return None
    try:
        target = generator.route(question=req.question, catalog=catalog)
    except LLMError as e:
        log.info("Routing failed: %s", e.message)
        return None
    return target if target in others else None


def _answer_on(
    database_id: str,
    question: str,
    history: list[HistoryTurn],
    execute: bool,
    registry: DatabaseRegistry,
    generator: SQLGenerator,
    settings: Settings,
    memory: AgentMemory | None = None,
    blocked: frozenset[str] = frozenset(),
    emit: Emit = _noop,
) -> GenerateResponse:
    """Ask for SQL on one database, run it, and if it fails let the AI fix it (up to max_fix_attempts times)."""
    info = registry.get(database_id)
    schema = registry.schema_prompt(info.id, hide=blocked)
    failures: list[Failure] = []
    attempts: list[Attempt] = []
    recall = memory.recall(info.id, question) if memory is not None else None
    context = recall.to_prompt() if recall else ""
    used = recall.count if recall else 0
    if used:
        emit("status", {"message": f"Using {used} saved {'item' if used == 1 else 'items'} from training"})

    for attempt in range(settings.max_fix_attempts + 1):
        emit("status", {"message": "Writing the SQL" if attempt == 0 else "Fixing the query"})
        gen = generator.generate(
            dialect=info.dialect,
            schema=schema,
            question=question,
            history=history,
            failures=failures,
            context=context,
        )
        if not gen.answerable or not gen.sql:
            return GenerateResponse(
                question=question,
                database_id=info.id,
                answerable=False,
                sql="",
                explanation=gen.explanation or "This question can't be answered from this database.",
                attempts=attempts,
                used_memory=used,
            )

        emit("sql", {"sql": gen.sql})
        try:
            if execute:
                emit("status", {"message": "Running it read-only"})
                sql, result = registry.execute(info.id, gen.sql, blocked)
            else:
                sql, result = validate_read_only(gen.sql, to_sqlglot_dialect(info.dialect)), None
        except (UnsafeSQLError, QueryError) as e:
            emit("repair", {"error": str(e)})
            attempts.append(Attempt(sql=gen.sql, error=str(e)))
            failures.append(Failure(generation=gen, error=str(e)))
            continue

        return GenerateResponse(
            question=question,
            database_id=info.id,
            answerable=True,
            sql=sql,
            explanation=gen.explanation,
            result=result,
            attempts=attempts,
            used_memory=used,
        )

    last = attempts[-1]
    return GenerateResponse(
        question=question,
        database_id=info.id,
        answerable=True,
        sql=last.sql,
        explanation=gen.explanation,
        error=last.error,
        attempts=attempts[:-1],
        used_memory=used,
    )
