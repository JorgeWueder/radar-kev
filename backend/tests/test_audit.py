import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog
from tests.conftest import client_for, isolated_schema, login


def test_audit_log_rejects_update_delete_truncate(client: TestClient, maker: sessionmaker[Session]) -> None:
    login(client, "admin@radar.local")
    for stmt in ("UPDATE audit_log SET module='x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with maker() as s, pytest.raises(DBAPIError, match="solo de anadir"):
            s.execute(text(stmt))
            s.commit()


def test_chain_verifies_then_detects_tampering() -> None:
    with isolated_schema() as m:
        c = client_for(m)
        h = login(c, "admin@radar.local")
        c.get("/api/v1/users", headers=h)
        ok = c.get("/api/v1/audit/verify", headers=h).json()
        assert ok["ok"] is True and ok["checked"] >= 1
        # Manipulación hecha "por fuera" (un DBA): se desactiva el trigger y se altera una fila.
        with m() as s:
            s.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
            s.execute(text("UPDATE audit_log SET action='borrado' WHERE id = 1"))
            s.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))
            s.commit()
        bad = c.get("/api/v1/audit/verify", headers=h).json()
        assert bad["ok"] is False and bad["first_broken_id"] == 1


def test_module_navigation_enter_leave_with_duration(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "analista@radar.local")
    assert client.post("/api/v1/audit/navigation", headers=h,
                       json={"module": "assets", "event": "enter"}).status_code == 204
    assert client.post("/api/v1/audit/navigation", headers=h,
                       json={"module": "assets", "event": "leave", "duration_ms": 4200}).status_code == 204
    assert client.post("/api/v1/audit/navigation", headers=h,
                       json={"module": "BAD MODULE!", "event": "enter"}).status_code == 422
    with maker() as s:
        rows = s.execute(select(AuditLog).where(AuditLog.module == "assets")).scalars().all()
        assert [r.action for r in rows][-2:] == ["module_enter", "module_leave"]
        assert rows[-1].duration_ms == 4200


def test_filters_and_export_are_audited(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "auditor@radar.local")
    r = client.get("/api/v1/audit", headers=h, params={"module": "auth", "action": "login"})
    assert r.status_code == 200 and all(i["module"] == "auth" for i in r.json()["items"])
    csv = client.get("/api/v1/audit/export", headers=h, params={"fmt": "csv"})
    assert csv.status_code == 200 and csv.text.startswith("id,fecha_utc")
    xlsx = client.get("/api/v1/audit/export", headers=h, params={"fmt": "xlsx"})
    assert xlsx.content[:2] == b"PK"
    with maker() as s:
        exports = s.execute(select(AuditLog).where(AuditLog.action == "export")).scalars().all()
        assert len(exports) >= 2


def test_audit_has_no_edit_or_delete_endpoints(client: TestClient) -> None:
    h = login(client, "admin@radar.local")
    for method in ("PUT", "PATCH", "DELETE"):
        assert client.request(method, "/api/v1/audit/1", headers=h).status_code in (404, 405)
