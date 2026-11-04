import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.core.ratelimit import client_key
from app.main import create_app, validate_runtime_settings
from tests.conftest import PASSWORD, client_for, isolated_schema, login


def req(headers: dict[str, str], host: str = "172.19.0.5") -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()], "client": (host, 1234)})


def test_rate_limit_key_uses_the_real_client_behind_the_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings()
    monkeypatch.setattr(cfg, "trust_proxy_headers", True)
    assert client_key(req({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})) == "203.0.113.9"  # no todos comparten la IP del proxy
    monkeypatch.setattr(cfg, "trust_proxy_headers", False)
    assert client_key(req({"X-Forwarded-For": "203.0.113.9"})) == "172.19.0.5"  # sin proxy de confianza se ignora la cabecera


def test_validation_errors_do_not_echo_submitted_values() -> None:
    with isolated_schema() as m:
        c = client_for(m)
        secret = "ContraseñaSuperSecreta" * 20  # excede el máximo permitido
        r = c.post("/api/v1/auth/login", json={"email": "admin@radar.local", "password": secret})
        assert r.status_code == 422
        assert secret not in r.text and "input" not in r.json()["detail"][0]  # nunca se devuelve lo enviado


def test_swagger_exposes_bearer_scheme_and_hides_internal_endpoints() -> None:
    spec = TestClient(create_app()).get("/openapi.json").json()
    assert "HTTPBearer" in spec["components"]["securitySchemes"] and spec["info"]["version"] == "1.0.0"
    assert not [p for p in spec["paths"] if "/internal" in p]
    assert {t["name"] for t in spec["tags"]} >= {"autenticación", "reportes", "IA", "bitácora"}
    assert "Bearer" in spec["info"]["description"]


def test_docs_are_disabled_in_production_unless_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings()
    monkeypatch.setattr(cfg, "environment", "test")
    assert TestClient(create_app()).get("/docs").status_code == 200
    monkeypatch.setattr(cfg, "environment", "production")
    monkeypatch.setattr("app.main.validate_runtime_settings", lambda c: None)
    app = create_app()
    c = TestClient(app)
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    assert "max-age" in c.get("/health").headers["strict-transport-security"]  # HSTS solo en producción
    monkeypatch.setattr(cfg, "enable_docs_explicit", True)
    assert TestClient(create_app()).get("/docs").status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [("jwt_secret", "CHANGE_ME"), ("jwt_secret", "corta"), ("radar_service_key", ""), ("fernet_key", "no-es-una-clave-fernet-valida-0000000")],
)
def test_startup_refuses_missing_example_or_invalid_secrets(field: str, value: str) -> None:
    from pydantic import SecretStr

    good = {"jwt_secret": SecretStr("j" * 40), "radar_service_key": SecretStr("s" * 30),
            "fernet_key": SecretStr("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")}  # fmt: skip
    validate_runtime_settings(Settings(**good))  # una configuración correcta arranca
    with pytest.raises(RuntimeError, match="Configuración insegura"):
        validate_runtime_settings(Settings(**{**good, field: SecretStr(value)}))


def test_ready_and_health_endpoints() -> None:
    with isolated_schema() as m:
        c = client_for(m)
        assert c.get("/health").json() == {"status": "ok"} and c.get("/ready").json() == {"status": "ready"}
        h = login(c, "admin@radar.local")
        assert c.get("/api/v1/auth/me", headers=h).status_code == 200 and PASSWORD  # el esquema Bearer no rompe la autenticación


def test_hardening_headers_on_api_responses() -> None:
    r = TestClient(create_app()).get("/health")
    assert r.headers["permissions-policy"].startswith("camera=()") and r.headers["cross-origin-resource-policy"] == "same-origin"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"


def test_apps_are_isolated_between_tests() -> None:
    assert isinstance(create_app(), FastAPI)
