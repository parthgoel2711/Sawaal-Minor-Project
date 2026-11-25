"""Demo mode: a stand-in for the AI that answers a prepared set of questions, with no API key and no network.

For presentations and offline testing. It matches the question to the benchmark questions in eval/golden.json
(which come with known-correct SQL), then fills in the summary and explanation from the result itself. It does not
understand anything new, and the app says so everywhere ("Demo AI"). Set DEMO_MODE=true to use it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from .documents import tokenize
from .llm import ChartIdea, DocAnswer, Explanation, Failure, Generation, Insight
from .schemas import HistoryTurn

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden.json"
MATCH_THRESHOLD = 0.5


def _load() -> list[dict[str, str]]:
    return json.loads(GOLDEN_PATH.read_text())


def demo_questions(database_id: str) -> list[str]:
    return [c["question"] for c in _load() if c["database"] == database_id]


def _similarity(a: str, b: str) -> float:
    x, y = set(tokenize(a)), set(tokenize(b))
    return len(x & y) / len(x | y) if x and y else 0.0


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


class DemoGenerator:
    """Implements the same methods as the real generators."""

    def __init__(self) -> None:
        self.cases = _load()

    def _best(self, question: str, only_db: str | None = None, schema: str | None = None) -> tuple[dict | None, float]:
        best, score = None, 0.0
        for c in self.cases:
            if only_db and c["database"] != only_db:
                continue
            if schema is not None and not self._fits(c["gold_sql"], schema):
                continue
            s = _similarity(question, c["question"])
            if s > score:
                best, score = c, s
        return best, score

    @staticmethod
    def _fits(sql: str, schema: str) -> bool:
        have = {m.lower() for m in re.findall(r"CREATE TABLE\s+[\"`]?(\w+)", schema, flags=re.I)}
        try:
            need = {t.name.lower() for t in sqlglot.parse_one(sql).find_all(exp.Table)}
        except sqlglot.errors.SqlglotError:
            return False
        return bool(need) and need <= have

    def generate(self, *, dialect: str, schema: str, question: str, history: list[HistoryTurn],
                 failures: list[Failure], context: str = "") -> Generation:
        # A taught example for this very question wins over the prepared set.
        for q, sql in re.findall(r"Question: (.+)\nSQL: (.+)", context):
            if _similarity(question, q) >= 0.8:
                return Generation(True, sql, "Reused the SQL you confirmed earlier for this question.")
        case, score = self._best(question, schema=schema)
        if case is None or score < MATCH_THRESHOLD:
            return Generation(False, "", "Demo mode only knows the prepared questions. Pick one of the suggestions.")
        return Generation(True, case["gold_sql"], f"Prepared answer for: {case['question']}")

    def route(self, *, question: str, catalog: str) -> str | None:
        ids = set(re.findall(r"^- id: (\S+)", catalog, flags=re.M))
        case, score = self._best(question)
        return case["database"] if case and score >= MATCH_THRESHOLD and case["database"] in ids else None

    def insight(self, *, question: str, sql: str, columns: list[str], rows: list[list[Any]], row_count: int) -> Insight:
        case, _ = self._best(question)
        others = [c["question"] for c in self.cases if case and c["database"] == case["database"]
                  and c["question"] != case["question"]]
        if row_count == 1 and len(columns) == 1:
            summary = f"The answer is {_fmt(rows[0][0])}"
        elif len(columns) >= 2 and isinstance(rows[0][-1], (int, float)):
            top = rows[0]
            summary = (f"{_fmt(top[0])} comes first with {_fmt(top[-1])}"
                       + (f", then {_fmt(rows[1][0])} with {_fmt(rows[1][-1])}" if len(rows) > 1 else ""))
        else:
            summary = f"{row_count} rows, starting with {_fmt(rows[0][0])}"
        return Insight(summary=summary, followups=others[:3])

    def explain(self, *, dialect: str, schema: str, sql: str) -> Explanation:
        try:
            root = sqlglot.parse_one(sql)
        except sqlglot.errors.SqlglotError:
            return Explanation(summary="This query reads data from the database.", steps=["Run the query."])
        tables = list(dict.fromkeys(t.name for t in root.find_all(exp.Table)))
        steps = [f"Read the {', '.join(tables)} table{'s' if len(tables) > 1 else ''}."]
        if list(root.find_all(exp.Join)):
            steps.append("Join the tables on their matching keys.")
        if root.args.get("where"):
            steps.append("Keep only the rows that match the filter.")
        if root.args.get("group"):
            steps.append("Group the rows and calculate a figure for each group.")
        if root.args.get("order"):
            steps.append("Sort the result.")
        if root.args.get("limit"):
            steps.append("Keep only the first rows.")
        return Explanation(summary=f"Answers a question using {', '.join(tables)}.", steps=steps)

    def dashboard(self, *, dialect: str, schema: str, count: int) -> list[ChartIdea]:
        return []  # the rule-based planner builds the charts

    def answer_documents(self, *, question: str, passages: list[str], data_context: str | None) -> DocAnswer:
        if not passages:
            return DocAnswer("Nothing relevant was found in the documents.", False)
        best = max(passages, key=lambda p: _similarity(question, p) + len(set(tokenize(question)) & set(tokenize(p))))
        sentences = re.split(r"(?<=[.!?])\s+", best)
        pick = max(sentences, key=lambda s: len(set(tokenize(question)) & set(tokenize(s))))
        return DocAnswer(f"{pick.strip()} [{passages.index(best) + 1}]", True)
