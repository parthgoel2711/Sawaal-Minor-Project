from app.ratelimit import RateLimiter


def test_blocks_after_the_limit_and_recovers():
    now = [0.0]
    limiter = RateLimiter(2, window_seconds=60, clock=lambda: now[0])
    assert limiter.check("a") == 0 and limiter.check("a") == 0
    assert 0 < limiter.check("a") <= 60
    assert limiter.check("b") == 0  # other clients are unaffected
    now[0] = 61
    assert limiter.check("a") == 0


def test_zero_disables_the_limit():
    limiter = RateLimiter(0)
    assert all(limiter.check("a") == 0 for _ in range(100))


def test_api_returns_429_with_retry_after(settings, fake_generator):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.rate_limit_per_minute = 2
    with TestClient(create_app(settings, generator=fake_generator)) as c:
        body = {"database_id": "ecommerce", "question": "How many customers?"}
        assert c.post("/api/generate", json=body).status_code == 200
        assert c.post("/api/generate", json=body).status_code == 200
        r = c.post("/api/generate", json=body)
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
        assert "Too many questions" in r.json()["detail"]
        assert c.post("/api/execute", json={"database_id": "ecommerce", "sql": "SELECT 1"}).status_code == 200
