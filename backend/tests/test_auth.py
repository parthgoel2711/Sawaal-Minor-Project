from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password, required_role, verify_password
from app.config import Settings
from app.llm import Generation
from app.main import create_app


def test_password_hashing():
    h = hash_password("s3cret-pass")
    assert "s3cret" not in h and verify_password("s3cret-pass", h) and not verify_password("nope", h)
    assert not verify_password("x", "garbage")


def test_role_rules():
    assert required_role("GET", "/api/health") is None
    assert required_role("POST", "/api/generate") == "viewer"
    assert required_role("GET", "/api/databases") == "viewer"
    assert required_role("POST", "/api/memory/notes") == "analyst"
    assert required_role("POST", "/api/databases/upload") == "analyst"
    assert required_role("POST", "/api/databases/connect") == "admin"
    assert required_role("DELETE", "/api/databases/x") == "admin"
    assert required_role("GET", "/api/audit") == "admin"
    assert required_role("POST", "/api/documents/ask") == "viewer"


@pytest.fixture
def secured(settings: Settings, fake_generator) -> Iterator[TestClient]:
    s = settings.model_copy(update={
        "auth_enabled": True, "demo_users": True, "restricted_tables": "orders, Reviews", "rate_limit_per_minute": 0})
    with TestClient(create_app(s, generator=fake_generator)) as c:
        yield c


def login(app_client: TestClient, who: str) -> TestClient:
    other = TestClient(app_client.app)
    r = other.post("/api/auth/login", json={"username": who, "password": f"{who}-demo"})
    assert r.status_code == 200, r.text
    return other


def test_nothing_works_without_signing_in(secured):
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/api/databases").status_code == 401
    assert secured.post("/api/generate", json={"database_id": "ecommerce", "question": "x"}).status_code == 401
    me = secured.get("/api/auth/me").json()
    assert me["auth_enabled"] and me["user"] is None


def test_wrong_password_and_unknown_user_look_the_same(secured):
    a = secured.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    b = secured.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_cookie_is_http_only_and_logout_ends_the_session(secured):
    c = TestClient(secured.app)
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "viewer-demo"})
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/auth/me").json()["user"] == {"username": "viewer", "role": "viewer"}
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/databases").status_code == 401


def test_viewer_can_ask_but_not_change_things(secured):
    v = login(secured, "viewer")
    assert v.get("/api/databases").status_code == 200
    assert v.post("/api/generate", json={"database_id": "ecommerce", "question": "customers"}).status_code == 200
    assert v.post("/api/memory/notes", json={"database_id": "ecommerce", "text": "some rule"}).status_code == 403
    assert v.post("/api/databases/connect", json={"name": "x", "url": "postgresql://u:p@h/d"}).status_code == 403
    assert v.get("/api/audit").status_code == 403
    assert v.get("/api/users").status_code == 403


def test_analyst_can_teach_but_not_connect_or_administer(secured):
    a = login(secured, "analyst")
    assert a.post("/api/memory/notes", json={"database_id": "ecommerce", "text": "some rule"}).status_code == 201
    assert a.post("/api/databases/connect", json={"name": "x", "url": "postgresql://u:p@h/d"}).status_code == 403
    assert a.get("/api/audit").status_code == 403


def test_restricted_tables_are_hidden_from_viewers_only(secured):
    names = lambda c: {t["name"] for t in c.get("/api/databases/ecommerce/schema").json()["tables"]}  # noqa: E731
    assert not ({"orders", "reviews"} & names(login(secured, "viewer")))
    assert {"orders", "reviews", "customers"} <= names(login(secured, "analyst"))
    assert {"orders", "reviews"} <= names(login(secured, "admin"))


def test_restricted_tables_cannot_be_queried_by_viewers(secured):
    v = login(secured, "viewer")
    r = v.post("/api/execute", json={"database_id": "ecommerce", "sql": "SELECT * FROM orders"}).json()
    assert "not allowed to read the table orders" in r["error"]
    sneaky = v.post("/api/execute", json={
        "database_id": "ecommerce",
        "sql": "WITH x AS (SELECT * FROM Orders) SELECT COUNT(*) FROM x JOIN customers c ON 1=1"}).json()
    assert sneaky["error"]
    assert login(secured, "analyst").post("/api/execute", json={
        "database_id": "ecommerce", "sql": "SELECT COUNT(*) FROM orders"}).json()["result"]["rows"][0][0] > 0
    assert v.post("/api/execute", json={
        "database_id": "ecommerce", "sql": "SELECT COUNT(*) FROM customers"}).json()["result"]


def test_ai_answers_respect_restrictions_and_hide_the_table_from_the_prompt(secured, fake_generator):
    fake_generator.script = [Generation(True, "SELECT COUNT(*) FROM orders", "x")]
    r = login(secured, "viewer").post("/api/generate", json={
        "database_id": "ecommerce", "question": "how many orders", "auto_route": False}).json()
    assert r["error"] and "orders" in r["error"] and r["result"] is None
    assert "CREATE TABLE orders" not in fake_generator.calls[0]["schema"]
    assert "CREATE TABLE customers" in fake_generator.calls[0]["schema"]


def test_audit_log_records_who_did_what(secured):
    login(secured, "viewer").post("/api/generate", json={"database_id": "ecommerce", "question": "how many customers"})
    login(secured, "viewer").post("/api/memory/notes", json={"database_id": "ecommerce", "text": "a rule"})
    secured.post("/api/auth/login", json={"username": "admin", "password": "bad-password"})
    rows = login(secured, "admin").get("/api/audit").json()
    seen = {(r["username"], r["action"], r["status"]) for r in rows}
    assert ("viewer", "login", "ok") in seen and ("viewer", "ask", "ok") in seen
    assert ("viewer", "denied", "denied") in seen and ("anonymous", "login", "denied") in seen
    ask = next(r for r in rows if r["action"] == "ask")
    assert "how many customers" in ask["detail"] and "SELECT" in ask["detail"]
    only = login(secured, "admin").get("/api/audit?action=ask").json()
    assert only and all(r["action"] == "ask" for r in only)


def test_user_management(secured):
    admin = login(secured, "admin")
    assert admin.post("/api/users", json={"username": "short", "password": "x", "role": "viewer"}).status_code == 400
    ok = admin.post("/api/users", json={"username": "meera", "password": "long-enough-pw", "role": "analyst"})
    assert ok.status_code == 201
    assert admin.post("/api/users", json={"username": "MEERA", "password": "long-enough-pw", "role": "viewer"}).status_code == 400
    assert {u["username"] for u in admin.get("/api/users").json()} >= {"admin", "meera"}
    assert "password" not in json.dumps(admin.get("/api/users").json())
    new = TestClient(secured.app)
    assert new.post("/api/auth/login", json={"username": "meera", "password": "long-enough-pw"}).status_code == 200
    assert admin.delete(f"/api/users/{ok.json()['id']}").status_code == 204
    me = next(u for u in admin.get("/api/users").json() if u["username"] == "admin")
    assert admin.delete(f"/api/users/{me['id']}").status_code == 400  # last admin


def test_login_attempts_are_rate_limited(secured):
    codes = [secured.post("/api/auth/login", json={"username": "admin", "password": "bad-password"}).status_code
             for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def test_auth_off_means_local_admin_and_everything_works(client):
    me = client.get("/api/auth/me").json()
    assert me["auth_enabled"] is False and me["user"]["role"] == "admin"
    assert client.get("/api/audit").status_code == 200
    client.post("/api/generate", json={"database_id": "ecommerce", "question": "customers"})
    assert any(r["action"] == "ask" and r["username"] == "local" for r in client.get("/api/audit").json())


def test_first_start_creates_an_admin(settings, fake_generator, caplog):
    s = settings.model_copy(update={"auth_enabled": True, "admin_password": "chosen-password"})
    with TestClient(create_app(s, generator=fake_generator)) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": "chosen-password"}).status_code == 200


def test_stream_sends_steps_then_the_answer(client):
    with client.stream("POST", "/api/generate/stream", json={"database_id": "ecommerce", "question": "customers"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in body.strip().split("\n\n")]
    names = [n for n, _ in events]
    assert names[0] == "status" and "sql" in names and names[-1] == "done"
    assert events[-1][1]["result"]["rows"][0][0] == 300


def test_stream_reports_errors_as_events(client_without_llm):
    with client_without_llm.stream(
            "POST", "/api/generate/stream", json={"database_id": "ecommerce", "question": "x"}) as r:
        body = "".join(r.iter_text())
    assert body.startswith("event: error") and "API key" in body


def test_signed_sessions_work_across_instances(tmp_path):
    from app.auth import UserStore

    a = UserStore(tmp_path / "a.db", 12, "secret")
    b = UserStore(tmp_path / "b.db", 12, "secret")  # a different server instance with its own database
    for store in (a, b):
        store.create("ann", "pw-pw-pw-1", "analyst")
    _, token = a.login("ann", "pw-pw-pw-1")
    assert b.user_for_token(token).username == "ann"
    assert b.user_for_token(token + "x") is None
    assert UserStore(tmp_path / "c.db", 12, "other").user_for_token(token) is None
