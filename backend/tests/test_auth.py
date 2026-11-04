from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.ratelimit import limiter
from app.core.security import create_token, validate_password
from app.models.audit import AuditLog
from app.models.auth import User
from tests.conftest import PASSWORD, login

ADMIN = "admin@radar.local"


def audit_actions(maker: sessionmaker[Session], **where: str) -> list[str]:
    with maker() as s:
        stmt = select(AuditLog.action, AuditLog.result)
        for k, v in where.items():
            stmt = stmt.where(getattr(AuditLog, k) == v)
        return [f"{a}:{r}" for a, r in s.execute(stmt.order_by(AuditLog.id)).all()]


def test_password_policy() -> None:
    assert validate_password("Radar-Demo-2026!", "x@y.com") == []
    assert validate_password("corta1A!", "x@y.com")  # < 12
    assert validate_password("todominusculasaqui", "x@y.com")  # una sola clase
    assert validate_password("Carlos-Ruiz-2026!", "carlos@y.com")  # contiene el usuario


def test_login_ok_and_me(client: TestClient) -> None:
    r = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "Administrador"
    assert "users:create" in body["user"]["permissions"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == ADMIN


def test_login_bad_password_generic_and_audited(
    client: TestClient, maker: sessionmaker[Session]
) -> None:
    r = client.post("/api/v1/auth/login", json={"email": ADMIN, "password": "mala"})
    assert r.status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"email": "nadie@radar.local", "password": "mala"}
    ).json() == r.json()  # misma respuesta: no se enumeran usuarios
    assert "login:failure" in audit_actions(maker)


def test_lockout_after_five_failures(client: TestClient, maker: sessionmaker[Session]) -> None:
    email = "auditor@radar.local"
    for _ in range(5):
        assert client.post(
            "/api/v1/auth/login", json={"email": email, "password": "mala"}
        ).status_code == 401
    # Incluso con la contraseña correcta, la cuenta sigue bloqueada.
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 423
    with maker() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one()
        assert u.locked_until is not None
        u.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # vence el bloqueo
        s.commit()
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_login_rate_limit_returns_429(client: TestClient) -> None:
    limiter.enabled = True
    limiter.reset()
    codes = [
        client.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "mala"}).status_code
        for _ in range(7)
    ]
    assert codes[:5] == [401] * 5
    assert 429 in codes[5:]


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    client.post("/api/v1/auth/login", json={"email": "gerencia@radar.local", "password": PASSWORD})
    old = client.cookies.get("refresh_token")
    assert old
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    # Reutilizar el refresh anterior revoca toda la familia.
    domain = next(c.domain for c in client.cookies.jar if c.name == "refresh_token")
    client.cookies.set("refresh_token", old, domain=domain, path="/api/v1/auth")  # sustituye la cookie rotada por la vieja
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_and_audits(client: TestClient, maker: sessionmaker[Session]) -> None:
    client.post("/api/v1/auth/login", json={"email": "analista@radar.local", "password": PASSWORD})
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert "logout:success" in audit_actions(maker, module="auth")


def test_expired_access_token_is_audited(client: TestClient, maker: sessionmaker[Session]) -> None:
    with maker() as s:
        uid = s.execute(select(User.id).where(User.email == ADMIN)).scalar_one()
    expired = create_token(uid, "access", timedelta(seconds=-5))
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    assert "session_expired:success" in audit_actions(maker)


def test_change_password_policy_enforced(client: TestClient) -> None:
    h = login(client, "auditor@radar.local") if False else login(client, "gerencia@radar.local")
    r = client.put("/api/v1/auth/me/password", headers=h,
                   json={"current_password": PASSWORD, "new_password": "corta"})
    assert r.status_code == 422
