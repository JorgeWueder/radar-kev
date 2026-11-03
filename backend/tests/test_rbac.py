import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.rbac import DEFAULT_MATRIX, permission_codes
from tests.conftest import login

USERS = {
    "Administrador": "admin@radar.local",
    "Analista de vulnerabilidades": "analista@radar.local",
    "Auditor": "auditor@radar.local",
    "Gerencia": "gerencia@radar.local",
}

# (método, ruta, permiso requerido)
ENDPOINTS = [
    ("GET", "/api/v1/users", "users:view"),
    ("GET", "/api/v1/roles", "roles:view"),
    ("GET", "/api/v1/audit", "audit:view"),
    ("GET", "/api/v1/audit/verify", "audit:view"),
    ("GET", "/api/v1/audit/export", "audit:export"),
]


@pytest.mark.parametrize("role", list(USERS))
def test_matrix_enforced_by_backend(client: TestClient, role: str) -> None:
    allowed = permission_codes(DEFAULT_MATRIX[role])
    h = login(client, USERS[role])
    for method, path, perm in ENDPOINTS:
        r = client.request(method, path, headers=h)
        assert r.status_code == (200 if perm in allowed else 403), (role, path, r.status_code)


def test_no_token_is_401(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401
    assert client.get("/api/v1/audit").status_code == 401


def test_denied_access_is_audited(client: TestClient, maker: sessionmaker[Session]) -> None:
    from sqlalchemy import select

    from app.models.audit import AuditLog

    h = login(client, "gerencia@radar.local")
    assert client.get("/api/v1/users", headers=h).status_code == 403
    with maker() as s:
        row = s.execute(
            select(AuditLog).where(AuditLog.action == "access_denied").order_by(AuditLog.id.desc())
        ).scalars().first()
        assert row is not None and row.result == "denied" and row.detail["permission"] == "users:view"


def test_role_permission_change_is_audited_and_effective(client: TestClient) -> None:
    h = login(client, "admin@radar.local")
    r = client.post("/api/v1/roles", headers=h, json={"name": "Lector KEV", "permissions": ["kev:view"]})
    assert r.status_code == 201
    role_id = r.json()["id"]
    r = client.put(f"/api/v1/roles/{role_id}/permissions", headers=h,
                   json={"permissions": ["kev:view", "audit:view"]})
    assert r.json()["permissions"] == ["audit:view", "kev:view"]
    assert client.put(f"/api/v1/roles/{role_id}/permissions", headers=h,
                      json={"permissions": ["inventado:view"]}).status_code == 422
    admin_role = next(x for x in client.get("/api/v1/roles", headers=h).json() if x["name"] == "Administrador")
    assert client.put(f"/api/v1/roles/{admin_role['id']}/permissions", headers=h,
                      json={"permissions": []}).status_code == 400
    sys_role = next(x for x in client.get("/api/v1/roles", headers=h).json() if x["is_system"])
    assert client.delete(f"/api/v1/roles/{sys_role['id']}", headers=h).status_code == 400
    assert client.delete(f"/api/v1/roles/{role_id}", headers=h).status_code == 204


def test_user_crud_policy_and_self_protection(client: TestClient) -> None:
    h = login(client, "admin@radar.local")
    roles = client.get("/api/v1/roles", headers=h).json()
    rid = roles[0]["id"]
    bad = client.post("/api/v1/users", headers=h,
                      json={"email": "nuevo@radar.local", "full_name": "Nuevo", "password": "corta", "role_id": rid})
    assert bad.status_code == 422
    ok = client.post("/api/v1/users", headers=h,
                     json={"email": "nuevo@radar.local", "full_name": "Nuevo Usuario",
                           "password": "Clave-Segura-2026!", "role_id": rid})
    assert ok.status_code == 201
    assert client.post("/api/v1/users", headers=h,
                       json={"email": "nuevo@radar.local", "full_name": "Otro", "password": "Clave-Segura-2026!",
                             "role_id": rid}).status_code == 409
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert client.delete(f"/api/v1/users/{me['id']}", headers=h).status_code == 400
    assert client.delete(f"/api/v1/users/{ok.json()['id']}", headers=h).status_code == 204
