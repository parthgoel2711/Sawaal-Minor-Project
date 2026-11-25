"""Data profile, usage stats and personal-data masking."""

from app.database import mask_personal_data


def test_masking_hides_personal_columns_only():
    cols = ["name", "email", "phone_number", "city"]
    rows = [["Asha", "asha@example.com", "9876543210", "Pune"], ["Ravi", None, "12", "Delhi"]]
    hidden = mask_personal_data(cols, rows)
    assert hidden == ["email", "phone_number"]
    assert rows[0] == ["Asha", "a•••@example.com", "•••10", "Pune"]
    assert rows[1][1] is None and rows[1][2] == "••••"


def test_masking_ignores_lookalike_names():
    cols = ["company", "expand", "panel", "campaign"]
    assert mask_personal_data(cols, [["a", "b", "c", 1]]) == []


def test_results_hide_emails_by_default(client):
    body = client.post("/api/execute", json={"database_id": "ecommerce",
                                             "sql": "SELECT first_name, email FROM customers LIMIT 3"}).json()
    assert body["result"]["masked_columns"] == ["email"]
    assert all("•••@" in row[1] for row in body["result"]["rows"])


def test_masking_can_be_turned_off(settings, fake_generator):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.mask_pii = False
    with TestClient(create_app(settings, generator=fake_generator)) as c:
        body = c.post("/api/execute", json={"database_id": "ecommerce",
                                            "sql": "SELECT email FROM customers LIMIT 2"}).json()
    assert body["result"]["masked_columns"] == [] and "•" not in body["result"]["rows"][0][0]


def test_profile_reports_counts_and_flags(client):
    p = client.get("/api/databases/school/profile").json()
    tables = {t["name"]: t for t in p["tables"]}
    assert tables["students"]["row_count"] == 240
    cols = {c["name"]: c for c in tables["students"]["columns"]}
    assert cols["student_id"]["distinct"] == 240 and "unique" in cols["student_id"]["flags"]
    assert cols["gender"]["distinct"] == 2
    assert cols["gender"]["null_pct"] == 0
    assert 0 < p["completeness"] <= 100
    stream = {c["name"]: c for c in {t["name"]: t for t in p["tables"]}["classes"]["columns"]}["stream"]
    assert stream["nulls"] > 0  # junior classes have no stream


def test_profile_unknown_database_is_404(client):
    assert client.get("/api/databases/nope/profile").status_code == 404


def test_stats_count_questions_repairs_and_failures(client, fake_generator):
    from app.llm import Generation

    assert client.get("/api/stats").json()["total"] == 0
    client.post("/api/generate", json={"database_id": "ecommerce", "question": "How many customers?"})
    fake_generator.script = [Generation(True, "SELECT * FROM nope", "Bad."),
                             Generation(True, "SELECT COUNT(*) AS n FROM orders", "Fixed.")]
    fake_generator.calls.clear()
    client.post("/api/generate", json={"database_id": "ecommerce", "question": "How many orders?"})
    client.post("/api/execute", json={"database_id": "ecommerce", "sql": "SELECT * FROM missing"})
    s = client.get("/api/stats", params={"database_id": "ecommerce"}).json()
    assert (s["total"], s["ai"], s["manual"], s["failed"], s["repaired"]) == (3, 2, 1, 1, 1)
    assert s["success_rate"] == round(2 / 3, 3)
    assert len(s["daily"]) == 14 and s["daily"][-1]["count"] == 3
    assert client.get("/api/stats", params={"database_id": "school"}).json()["total"] == 0


def test_old_history_database_is_upgraded(tmp_path):
    import sqlite3

    from app.history import HistoryStore

    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, database_id TEXT NOT NULL, "
                 "question TEXT, sql TEXT NOT NULL, explanation TEXT, row_count INTEGER, error TEXT, "
                 "source TEXT NOT NULL, starred INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    conn.commit()
    conn.close()
    store = HistoryStore(path)
    store.add(database_id="x", sql="SELECT 1", source="ai", repairs=2, elapsed_ms=1500)
    assert store.stats().repaired == 1 and store.stats().avg_seconds == 1.5
