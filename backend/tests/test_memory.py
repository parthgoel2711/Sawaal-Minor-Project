from __future__ import annotations

import pytest

from app.memory import AgentMemory, rank


@pytest.fixture
def mem(tmp_path):
    return AgentMemory(tmp_path / "memory.db")


def test_rank_orders_by_shared_rare_words():
    texts = ["total revenue by month", "list of customers by city", "average rating of products"]
    assert rank("monthly revenue total", texts)[0][0] == 0
    assert rank("zzz", texts) == []


def test_examples_are_deduplicated(mem):
    a = mem.add_example("shop", "How many customers?", "SELECT COUNT(*) FROM customers;")
    b = mem.add_example("shop", "how many  customers?", "select count(*) from customers")
    assert a.id == b.id and len(mem.list("shop")) == 1


def test_recall_picks_similar_examples_and_notes(mem):
    mem.add_example("shop", "Top 5 customers by revenue", "SELECT 1")
    mem.add_example("shop", "Employees per region", "SELECT 2")
    mem.add_note("shop", "Revenue means quantity * unit_price after discount.")
    mem.add_example("other", "Top customers", "SELECT 3")
    r = mem.recall("shop", "which customers bring the most revenue")
    assert [e.sql for e in r.examples] == ["SELECT 1"]
    assert "Revenue means" in r.to_prompt() and "SELECT 1" in r.to_prompt()
    assert r.count == 2
    assert mem.recall("empty-db", "anything").to_prompt() == ""
    assert next(i for i in mem.list("shop") if i.sql == "SELECT 1").uses == 1


def test_notes_are_capped_and_newest_win_when_unrelated(mem):
    for i in range(12):
        mem.add_note("shop", f"rule number {i}")
    assert len(mem.recall("shop", "something else").notes) == 8


def test_delete_and_forget_database(mem):
    item = mem.add_note("shop", "a rule about stuff")
    assert mem.delete(item.id) and not mem.delete(item.id)
    mem.add_note("shop", "another rule")
    mem.forget_database("shop")
    assert mem.list("shop") == []


def test_teaching_changes_what_the_model_sees(client, fake_generator):
    ok = client.post("/api/memory/examples", json={
        "database_id": "ecommerce", "question": "How many customers do we have?",
        "sql": "SELECT COUNT(*) AS n FROM customers"})
    assert ok.status_code == 201
    client.post("/api/memory/notes", json={"database_id": "ecommerce", "text": "A customer means a row in customers."})
    r = client.post("/api/generate", json={"database_id": "ecommerce", "question": "how many customers"}).json()
    assert r["used_memory"] == 2
    ctx = fake_generator.calls[-1]["context"]
    assert "SELECT COUNT(*) AS n FROM customers" in ctx and "A customer means" in ctx


def test_nothing_taught_means_no_context(client, fake_generator):
    r = client.post("/api/generate", json={"database_id": "ecommerce", "question": "how many customers"}).json()
    assert r["used_memory"] == 0 and fake_generator.calls[-1]["context"] == ""


def test_unsafe_sql_cannot_be_taught(client):
    bad = client.post("/api/memory/examples", json={
        "database_id": "ecommerce", "question": "wipe it", "sql": "DELETE FROM customers"})
    assert bad.status_code == 400
    assert client.get("/api/memory?database_id=ecommerce").json() == []


def test_list_and_forget(client):
    item = client.post("/api/memory/notes", json={"database_id": "ecommerce", "text": "Prices are in INR."}).json()
    assert [i["text"] for i in client.get("/api/memory?database_id=ecommerce").json()] == ["Prices are in INR."]
    assert client.delete(f"/api/memory/{item['id']}").status_code == 204
    assert client.delete(f"/api/memory/{item['id']}").status_code == 404


def test_deleting_a_database_forgets_its_training(client):
    import io

    r = client.post("/api/databases/upload", files={"file": ("t.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    db = r.json()["id"]
    client.post("/api/memory/notes", json={"database_id": db, "text": "column a is the id"})
    client.delete(f"/api/databases/{db}")
    assert client.get(f"/api/memory?database_id={db}").json() == []
