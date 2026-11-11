def test_live(client):
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_reports_components(client):
    r = client.get("/api/v1/health")
    body = r.json()
    assert {"db", "redis", "worker", "beat", "status"} <= body.keys()
    assert body["db"]["status"] == "ok"


def test_unknown_route_uses_error_format(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_security_headers_and_no_stack_traces(client, app):
    r = client.get("/api/v1/health/live")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"

    @app.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("secret internals")

    from fastapi.testclient import TestClient

    res = TestClient(app, raise_server_exceptions=False).get("/api/v1/_boom")
    assert res.status_code == 500 and res.json() == {"detail": "Internal server error", "code": "internal_error"}
    assert "secret internals" not in res.text
