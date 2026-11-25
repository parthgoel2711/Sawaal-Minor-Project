from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import DatabaseRegistry
from app.llm import ChartIdea, DocAnswer, Explanation, Failure, Generation, Insight
from app.main import create_app
from app.schemas import HistoryTurn
from app.seed import ensure_sample_databases


@pytest.fixture(scope="session")
def built_samples(tmp_path_factory) -> Path:
    """Build the sample databases once per test session."""
    sample_dir = tmp_path_factory.mktemp("sample")
    ensure_sample_databases(sample_dir)
    return sample_dir


@pytest.fixture
def settings(tmp_path: Path, built_samples: Path) -> Settings:
    data = tmp_path / "data"
    (data / "sample").mkdir(parents=True)
    for db_file in built_samples.glob("*.db"):
        (data / "sample" / db_file.name).write_bytes(db_file.read_bytes())
    return Settings(
        _env_file=None,
        anthropic_api_key=None,
        data_dir=data,
        frontend_dist=tmp_path / "no-frontend",
        max_rows=50,
        query_timeout_seconds=2,
        max_fix_attempts=2,
    )


@pytest.fixture
def registry(settings: Settings) -> DatabaseRegistry:
    reg = DatabaseRegistry(settings)
    reg.refresh()
    return reg


class FakeGenerator:
    """Stands in for Claude: returns scripted answers and records what it was asked."""

    def __init__(self, script: list[Generation] | Callable[..., Generation] | None = None):
        self.script = script
        self.calls: list[dict] = []
        self.route_to: str | None = None
        self.route_calls: list[dict] = []
        self.insight_calls: list[dict] = []
        self.insight_result: Insight | Exception = Insight(
            summary="There are 300 customers.", followups=["How many per city?", "Top spenders?", "Newest customers?"]
        )

    def dashboard(self, *, dialect, schema, count):
        self.dashboard_ideas = getattr(self, "dashboard_ideas", None) or [
            ChartIdea("Customers by city", "SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC", "Where customers live."),
            ChartIdea("Orders by status", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status", "Order outcomes."),
        ]
        return self.dashboard_ideas

    def answer_documents(self, *, question, passages, data_context) -> DocAnswer:
        self.doc_calls = getattr(self, "doc_calls", []) + [dict(question=question, passages=passages, data_context=data_context)]
        return DocAnswer(answer="The notice period is 30 days [1].", found=True)

    def explain(self, *, dialect, schema, sql) -> Explanation:
        self.explain_calls = getattr(self, "explain_calls", []) + [dict(dialect=dialect, schema=schema, sql=sql)]
        return Explanation(summary="Counts customers.", steps=["Read the customers table.", "Count the rows."])

    def insight(self, *, question, sql, columns, rows, row_count) -> Insight:
        self.insight_calls.append(dict(question=question, sql=sql, columns=columns, rows=rows, row_count=row_count))
        if isinstance(self.insight_result, Exception):
            raise self.insight_result
        return self.insight_result

    def route(self, *, question: str, catalog: str) -> str | None:
        self.route_calls.append(dict(question=question, catalog=catalog))
        return self.route_to

    def generate(self, *, dialect: str, schema: str, question: str,
                 history: list[HistoryTurn], failures: list[Failure], context: str = "") -> Generation:
        self.calls.append(dict(dialect=dialect, schema=schema, question=question,
                               history=history, failures=list(failures), context=context))
        if callable(self.script):
            return self.script(question=question, failures=failures, schema=schema)
        if self.script:
            return self.script[min(len(self.calls), len(self.script)) - 1]
        return Generation(answerable=True, sql="SELECT COUNT(*) AS n FROM customers",
                          explanation="Counts customers.")


@pytest.fixture
def fake_generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def client(settings: Settings, fake_generator: FakeGenerator) -> Iterator[TestClient]:
    app = create_app(settings, generator=fake_generator)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_without_llm(settings: Settings, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
