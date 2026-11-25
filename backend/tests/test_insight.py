"""Plain-language summaries and follow-up suggestions."""

import json

import groq
import httpx

from app.config import Settings
from app.llm import GroqSQLGenerator, Insight, LLMError, insight_message, to_insight


def ask(client, **extra):
    body = {"database_id": "ecommerce", "question": "How many customers?", **extra}
    return client.post("/api/generate", json=body).json()


def test_answer_includes_summary_and_followups(client, fake_generator):
    body = ask(client)
    assert body["summary"] == "There are 300 customers."
    assert len(body["followups"]) == 3
    call = fake_generator.insight_calls[0]
    assert call["columns"] == ["n"] and call["rows"] == [[300]] and call["row_count"] == 1


def test_insights_can_be_switched_off(client, fake_generator):
    body = ask(client, insights=False)
    assert body["summary"] == "" and body["followups"] == []
    assert fake_generator.insight_calls == []


def test_failing_insight_never_breaks_the_answer(client, fake_generator):
    fake_generator.insight_result = LLMError("rate limited", 429)
    body = ask(client)
    assert body["answerable"] and body["result"]["rows"] == [[300]]
    assert body["summary"] == ""
    fake_generator.insight_result = RuntimeError("boom")
    assert ask(client)["result"]["rows"] == [[300]]


def test_no_insight_for_empty_results(client, fake_generator):
    from app.llm import Generation
    fake_generator.script = [Generation(True, "SELECT * FROM customers WHERE 1 = 0", "Nothing.")]
    body = ask(client)
    assert body["result"]["row_count"] == 0 and body["summary"] == ""
    assert fake_generator.insight_calls == []


def test_insight_message_truncates_long_results():
    rows = [[i, "x" * 200] for i in range(100)]
    text = insight_message("q?", "SELECT 1", ["id", "note"], rows, 100)
    assert "first 25 of 100 rows" in text
    assert "x" * 100 not in text and text.count("\n") < 40


def test_to_insight_is_forgiving():
    assert to_insight({"summary": " Hi ", "followups": ["a", "", "b", "c", "d"]}) == Insight("Hi", ["a", "b", "c"])
    assert to_insight({"summary": None, "followups": "oops"}) == Insight("", [])


def test_groq_insight_roundtrip():
    answer = {"summary": "Top city is Pune.", "followups": ["q1", "q2", "q3"]}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    settings = Settings(_env_file=None, llm_provider="groq", groq_api_key="k")
    client = groq.Groq(api_key="k", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = GroqSQLGenerator(settings, client=client, patient_retries=0).insight(
        question="Which city?", sql="SELECT 1", columns=["city"], rows=[["Pune"]], row_count=1)
    assert out == Insight("Top city is Pune.", ["q1", "q2", "q3"])
    assert "Which city?" in seen[0]["messages"][1]["content"]
