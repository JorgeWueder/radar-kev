from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_security_headers_present() -> None:
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_cors_rejects_foreign_origin() -> None:
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
