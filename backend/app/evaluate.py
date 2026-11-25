"""Measure how accurate the AI is: run a fixed set of questions and compare with known-correct SQL.

The metric is *execution accuracy* (the standard used by the Spider benchmark): a generated query counts as
correct when it returns the same data as the gold query, no matter how the SQL is written.

    python -m app.evaluate                     # all questions
    python -m app.evaluate --db school         # one database
    python -m app.evaluate --difficulty hard --delay 3

Reports are written to data/eval/ as JSON and Markdown.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .database import DatabaseRegistry
from .llm import LLMError, SQLGenerator, make_generator
from .schemas import GenerateRequest, QueryResult
from .seed import ensure_sample_databases
from .service import answer_question

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden.json"


@dataclass
class Case:
    id: str
    database: str
    difficulty: str
    question: str
    gold_sql: str


@dataclass
class CaseResult:
    id: str
    database: str
    difficulty: str
    question: str
    correct: bool
    first_try: bool = False  # correct without the automatic error repair
    repairs: int = 0
    seconds: float = 0.0
    predicted_sql: str = ""
    error: str | None = None


@dataclass
class Report:
    model: str
    started: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return _rate(r.correct for r in self.results)

    def breakdown(self, key: str) -> dict[str, tuple[int, int]]:
        """{group: (correct, total)} grouped by a CaseResult attribute."""
        groups: dict[str, list[bool]] = {}
        for r in self.results:
            groups.setdefault(getattr(r, key), []).append(r.correct)
        return {k: (sum(v), len(v)) for k, v in groups.items()}


def _rate(flags) -> float:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else 0.0


def load_cases(path: Path = GOLDEN_PATH) -> list[Case]:
    return [Case(**c) for c in json.loads(path.read_text(encoding="utf-8"))]


# ---------- comparing results ----------


def _sort_key(v: Any) -> tuple:
    if v is None:
        return (0, 0, "")
    if isinstance(v, bool):
        return (1, int(v), "")
    if isinstance(v, int | float):
        return (1, float(v), "")
    return (2, 0, str(v).strip().lower())


def _same_value(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=1e-2, abs_tol=0.011)
    return str(a).strip().lower() == str(b).strip().lower()


def _column(result: QueryResult, i: int) -> list[Any]:
    return sorted((row[i] for row in result.rows), key=_sort_key)


def results_match(gold: QueryResult, predicted: QueryResult) -> bool:
    """True when the predicted result holds the gold data.

    Ignores row order and column order, allows rounding differences, and allows extra columns
    (e.g. a name plus its count when only the name was needed).
    """
    if gold.row_count != predicted.row_count or len(predicted.columns) < len(gold.columns):
        return False
    pred_cols = [_column(predicted, i) for i in range(len(predicted.columns))]
    used: set[int] = set()
    for gi in range(len(gold.columns)):
        g = _column(gold, gi)
        for pi, p in enumerate(pred_cols):
            if pi not in used and all(_same_value(a, b) for a, b in zip(g, p)):
                used.add(pi)
                break
        else:
            return False
    return True


# ---------- running ----------


def evaluate_case(case: Case, registry: DatabaseRegistry, generator: SQLGenerator, settings: Settings) -> CaseResult:
    out = CaseResult(case.id, case.database, case.difficulty, case.question, correct=False)
    started = time.perf_counter()
    try:
        _, gold = registry.execute(case.database, case.gold_sql)
        req = GenerateRequest(database_id=case.database, question=case.question, auto_route=False, insights=False)
        answer = answer_question(req, registry, generator, settings)
        out.predicted_sql = answer.sql
        out.repairs = len(answer.attempts)
        if answer.error:
            out.error = answer.error
        elif not answer.answerable or answer.result is None:
            out.error = "The AI said the question can't be answered."
        else:
            out.correct = results_match(gold, answer.result)
            out.first_try = out.correct and out.repairs == 0
    except LLMError as e:
        out.error = e.message
    except Exception as e:  # noqa: BLE001 - one bad case must not stop the whole run
        out.error = f"{type(e).__name__}: {e}"
    out.seconds = round(time.perf_counter() - started, 2)
    return out


def run_evaluation(
    cases: list[Case],
    registry: DatabaseRegistry,
    generator: SQLGenerator,
    settings: Settings,
    delay: float = 0.0,
    on_result=None,
) -> Report:
    report = Report(model=settings.active_model, started=datetime.now().isoformat(timespec="seconds"))
    for i, case in enumerate(cases):
        if i and delay:
            time.sleep(delay)
        result = evaluate_case(case, registry, generator, settings)
        report.results.append(result)
        if on_result:
            on_result(result)
    return report


# ---------- reporting ----------


def to_markdown(report: Report) -> str:
    n = len(report.results)
    correct = sum(r.correct for r in report.results)
    first = sum(r.first_try for r in report.results)
    avg = sum(r.seconds for r in report.results) / n if n else 0
    lines = [
        "# Sawaal evaluation",
        "",
        f"- Model: `{report.model}`",
        f"- Run: {report.started}",
        f"- **Execution accuracy: {report.accuracy:.1%}** ({correct}/{n})",
        f"- Correct on the first try (no automatic repair): {first}/{n}",
        f"- Average time per question: {avg:.1f}s",
        "",
    ]
    for title, key in (("Difficulty", "difficulty"), ("Database", "database")):
        lines += [f"| {title} | Correct | Accuracy |", "| --- | --- | --- |"]
        for name, (ok, total) in sorted(report.breakdown(key).items()):
            lines.append(f"| {name} | {ok}/{total} | {ok / total:.0%} |")
        lines.append("")
    wrong = [r for r in report.results if not r.correct]
    if wrong:
        lines += ["## Wrong answers", ""]
        for r in wrong:
            lines += [f"- **{r.id}** {r.question}", f"  - `{r.predicted_sql or '(no SQL)'}`"]
            if r.error:
                lines.append(f"  - {r.error}")
        lines.append("")
    return "\n".join(lines)


def save_report(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path, md_path = out_dir / f"eval-{stamp}.json", out_dir / f"eval-{stamp}.md"
    payload = {
        "model": report.model,
        "started": report.started,
        "accuracy": report.accuracy,
        "results": [asdict(r) for r in report.results],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the accuracy of the AI on a set of known questions.")
    parser.add_argument("--db", help="only this database id (ecommerce, school, company, government)")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds to wait between questions (free-tier limits)")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.llm_enabled:
        print("No AI key found. Set GROQ_API_KEY or ANTHROPIC_API_KEY in .env first.", file=sys.stderr)
        return 1
    cases = [c for c in load_cases(args.golden)
             if (not args.db or c.database == args.db) and (not args.difficulty or c.difficulty == args.difficulty)]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("No questions match those filters.", file=sys.stderr)
        return 1

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ensure_sample_databases(settings.sample_dir)
    registry = DatabaseRegistry(settings)
    registry.refresh()
    print(f"Evaluating {len(cases)} questions with {settings.active_model}\n")

    def show(r: CaseResult) -> None:
        print(f"{'PASS' if r.correct else 'FAIL'}  {r.id}  {r.question}  ({r.seconds}s)")

    report = run_evaluation(cases, registry, make_generator(settings), settings, args.delay, show)
    json_path, md_path = save_report(report, settings.data_dir / "eval")
    print(f"\nExecution accuracy: {report.accuracy:.1%}\nSaved {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
