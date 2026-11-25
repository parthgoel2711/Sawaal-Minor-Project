from __future__ import annotations

from app.autodash import month_of, plan_rules, q


def test_rule_plan_covers_trend_category_and_measure(registry):
    plans = plan_rules(registry.schema("ecommerce"), "sqlite")
    titles = [t for t, _, _ in plans]
    assert titles[0] == "Records per table"
    assert any("by month" in t for t in titles)
    assert any(" by " in t and "month" not in t for t in titles)


def test_dialect_helpers():
    assert q("mysql", "a`b") == "`a``b`" and q("postgresql", 'a"b') == '"a""b"'
    assert month_of("postgresql", "d").startswith("to_char") and month_of("mysql", "d").startswith("DATE_FORMAT")
    assert month_of("sqlite", "d").startswith("strftime")


def test_every_sample_database_gets_working_charts_without_ai(client_without_llm):
    c = client_without_llm
    for db in c.get("/api/databases").json():
        if db["kind"] != "sample":
            continue
        r = c.post(f"/api/databases/{db['id']}/auto-dashboard", json={"use_ai": False}).json()
        assert r["source"] == "rules"
        assert len(r["widgets"]) >= 3, db["id"]
        assert all(w["result"]["row_count"] > 0 for w in r["widgets"])


def test_ai_charts_are_used_and_validated(client, fake_generator):
    fake_generator.dashboard_ideas = None
    r = client.post("/api/databases/ecommerce/auto-dashboard", json={}).json()
    assert r["source"] == "ai" and [w["title"] for w in r["widgets"]] == ["Customers by city", "Orders by status"]


def test_bad_ai_charts_fall_back_to_rules(client, fake_generator):
    from app.llm import ChartIdea

    fake_generator.dashboard_ideas = [
        ChartIdea("Broken", "SELECT nope FROM nowhere", ""),
        ChartIdea("Unsafe", "DELETE FROM customers", ""),
    ]
    r = client.post("/api/databases/ecommerce/auto-dashboard", json={}).json()
    assert r["source"] == "rules" and len(r["widgets"]) >= 3
