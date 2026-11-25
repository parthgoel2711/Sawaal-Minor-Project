"""Explain-this-SQL."""

import json

import groq
import httpx

from app.config import Settings
from app.llm import Explanation, GroqSQLGenerator, to_explanation


def test_explain_endpoint(client, fake_generator):
    r = client.post("/api/explain", json={"database_id": "ecommerce", "sql": "SELECT COUNT(*) FROM customers"})
    assert r.status_code == 200
    assert r.json() == {"summary": "Counts customers.", "steps": ["Read the customers table.", "Count the rows."]}
    call = fake_generator.explain_calls[0]
    assert call["dialect"] == "sqlite" and "CREATE TABLE customers" in call["schema"]


def test_explain_unknown_database(client):
    assert client.post("/api/explain", json={"database_id": "nope", "sql": "SELECT 1"}).status_code == 404


def test_explain_needs_an_api_key(client_without_llm):
    r = client_without_llm.post("/api/explain", json={"database_id": "ecommerce", "sql": "SELECT 1"})
    assert r.status_code == 503


def test_to_explanation_is_forgiving():
    assert to_explanation({"summary": " Hi ", "steps": ["a", "", "b"]}) == Explanation("Hi", ["a", "b"])
    assert to_explanation({"steps": "oops"}) == Explanation("", [])


def test_groq_explain_roundtrip():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        content = json.dumps({"summary": "Counts rows.", "steps": ["Read t", "Count"]})
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    settings = Settings(_env_file=None, llm_provider="groq", groq_api_key="k")
    client = groq.Groq(api_key="k", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = GroqSQLGenerator(settings, client=client, patient_retries=0).explain(
        dialect="sqlite", schema="CREATE TABLE t (a INT);", sql="SELECT COUNT(*) FROM t")
    assert out == Explanation("Counts rows.", ["Read t", "Count"])
    assert "CREATE TABLE t" in seen[0]["messages"][0]["content"]
