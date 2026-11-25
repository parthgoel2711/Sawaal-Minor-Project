"""The accuracy benchmark: the gold SQL must be valid, and the comparison must be fair."""

import pytest

from app.evaluate import load_cases, results_match, run_evaluation, to_markdown
from app.llm import Generation
from app.schemas import QueryResult


def qr(columns, rows):
    return QueryResult(columns=columns, column_types=["text"] * len(columns), rows=rows, row_count=len(rows),
                       truncated=False, elapsed_ms=1)


CASES = load_cases()


def test_golden_set_is_well_formed():
    assert len(CASES) >= 25
    assert len({c.id for c in CASES}) == len(CASES)
    assert {c.difficulty for c in CASES} == {"easy", "medium", "hard"}
    assert {c.database for c in CASES} == {"ecommerce", "school", "company", "government"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_gold_sql_runs_and_returns_data(case, registry):
    _, result = registry.execute(case.database, case.gold_sql)
    assert result.row_count > 0


def test_match_ignores_row_and_column_order():
    gold = qr(["name", "n"], [["a", 1], ["b", 2]])
    assert results_match(gold, qr(["count", "who"], [[2, "b"], [1, "a"]]))


def test_match_allows_rounding_extra_columns_and_case():
    assert results_match(qr(["avg"], [[1234.5678]]), qr(["avg"], [[1234.57]]))
    assert results_match(qr(["name"], [["Pune"]]), qr(["name", "total"], [["pune ", 5]]))


def test_match_rejects_wrong_data():
    gold = qr(["n"], [[10]])
    assert not results_match(gold, qr(["n"], [[11]]))
    assert not results_match(gold, qr(["n"], [[10], [10]]))
    assert not results_match(qr(["a", "b"], [[1, 2]]), qr(["a"], [[1]]))
    assert not results_match(qr(["a", "b"], [[1, 2]]), qr(["a", "b"], [[1, 3]]))


def test_run_evaluation_scores_right_and_wrong_answers(registry, settings, fake_generator):
    gold_by_question = {c.question: c.gold_sql for c in CASES}
    calls = []

    def script(question, failures, schema):
        calls.append(question)
        if len(calls) % 2:  # every other question gets a wrong query
            return Generation(True, "SELECT 12345 AS wrong", "Wrong.")
        return Generation(True, gold_by_question[question], "Right.")

    fake_generator.script = script
    cases = CASES[:6]
    report = run_evaluation(cases, registry, fake_generator, settings)
    assert [r.correct for r in report.results] == [False, True] * 3
    assert report.accuracy == 0.5
    assert all(r.first_try for r in report.results if r.correct)
    md = to_markdown(report)
    assert "Execution accuracy: 50.0%" in md and "Wrong answers" in md
    assert fake_generator.insight_calls == [] and fake_generator.route_calls == []


def test_unanswerable_and_failing_queries_count_as_wrong(registry, settings, fake_generator):
    fake_generator.script = [Generation(False, "", "No."), Generation(True, "SELECT * FROM nope", "Bad.")]
    report = run_evaluation(CASES[:2], registry, fake_generator, settings)
    assert [r.correct for r in report.results] == [False, False]
    assert all(r.error for r in report.results)
