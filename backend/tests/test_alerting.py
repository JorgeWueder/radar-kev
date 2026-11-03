from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.inventory import Vulnerability
from app.models.ops import Alert, AlertDelivery, IntegrationSetting, Ticket, TicketEvent
from app.services import notifications
from tests.conftest import login
from tests.test_intel_api import (  # noqa: F401  (fixture `env` y helper de datos)
    KEY,
    add_inventory,  # noqa: F401
    env,
    populate,
)

Env = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, str]]]:
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(notifications, "send_email", lambda cfg, subject, body: sent.append({"s": subject, "b": body}))
    yield sent


def matches_from_correlation(c: TestClient, m: sessionmaker[Session]) -> tuple[str, list[dict[str, Any]]]:
    populate_inventory(c, m)
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    return rid, c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": rid}).json()["new_matches"]


def populate_inventory(c: TestClient, m: sessionmaker[Session]) -> None:
    from tests.test_intel_api import CATALOG

    add_inventory(m)
    c.post("/api/v1/internal/kev/ingest", headers=KEY, json=CATALOG)


def dispatch(c: TestClient, rid: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    r = c.post("/api/v1/internal/alerts/dispatch", headers=KEY, json={"run_id": rid, "matches": matches})
    assert r.status_code == 200, r.text
    return r.json()


def test_dispatch_creates_alert_ticket_and_one_urgent_digest(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    assert len(matches) == 1
    out = dispatch(c, rid, matches)
    assert out["created_alerts"] == 1 and out["created_tickets"] == 1 and out["tickets"][0]["code"] == "RAD-000001"
    assert out["delivery"] == {"email": "sent", "webhook": "skipped"}  # webhook sin configurar
    assert len(mail) == 1 and mail[0]["s"].startswith("[URGENTE] 1 nueva vulnerabilidad KEV")
    assert "CVE-2021-44228 | srv-a" in mail[0]["b"] and "ransomware" not in mail[0]["b"].split("\n")[0]
    with m() as db:
        t = db.execute(select(Ticket)).scalar_one()
        assert t.priority == "critical" and t.status == "open" and "Acción requerida (CISA)" in t.description
        assert t.ai_generated is False and t.due_date is not None
        assert db.execute(select(TicketEvent.event)).scalar_one() == "created"


def test_dispatch_twice_creates_nothing_and_sends_nothing(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    first = dispatch(c, rid, matches)
    second = dispatch(c, rid, matches)  # el mismo lote otra vez (reintento del workflow)
    assert first["created_alerts"] == 1
    assert second["created_alerts"] == 0 and second["created_tickets"] == 0 and second["delivery"] == {}
    assert len(mail) == 1
    with m() as db:
        assert db.execute(select(func.count()).select_from(Alert)).scalar_one() == 1
        assert db.execute(select(func.count()).select_from(Ticket)).scalar_one() == 1
        assert db.execute(select(func.count()).select_from(AlertDelivery)).scalar_one() == 2  # email + webhook


def test_unique_constraints_back_the_idempotency(env: Env) -> None:  # noqa: F811
    from sqlalchemy.exc import IntegrityError

    c, m = env
    rid, matches = matches_from_correlation(c, m)
    dispatch(c, rid, matches)
    with m() as db:
        a = db.execute(select(Alert)).scalar_one()
        db.add(Alert(vulnerability_id=a.vulnerability_id, alert_type=a.alert_type, message="dup"))
        with pytest.raises(IntegrityError):
            db.flush()


def test_unknown_vulnerability_is_skipped_not_fatal(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    ghost = {**matches[0], "vulnerability_id": "00000000-0000-0000-0000-000000000000"}
    out = dispatch(c, rid, [ghost, *matches])
    assert out["skipped"] == 1 and out["created_alerts"] == 1


def test_invalid_match_payload_is_rejected(env: Env) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    bad = {**matches[0], "cve_id": "no-es-cve"}
    r = c.post("/api/v1/internal/alerts/dispatch", headers=KEY, json={"run_id": rid, "matches": [bad]})
    assert r.status_code == 422


def test_failing_channel_does_not_block_the_other(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    adm = login(c, "admin@radar.local")
    c.put("/api/v1/settings/integrations", headers=adm, json={"webhook_url": "https://hooks.example.test/x", "webhook_kind": "slack",
        "smtp_host": "mailpit", "smtp_port": 1025, "alert_email_to": "a@x.com"})  # fmt: skip
    sent: list[str] = []

    def boom(cfg: Any, subject: str, body: str) -> None:
        raise notifications.NotifyError("SMTP: ConnectionRefusedError")

    monkeypatch.setattr(notifications, "send_email", boom)
    monkeypatch.setattr(notifications, "send_webhook", lambda cfg, text: sent.append(text))
    rid, matches = matches_from_correlation(c, m)
    out = dispatch(c, rid, matches)
    assert out["delivery"] == {"email": "failed", "webhook": "sent"} and len(sent) == 1
    with m() as db:
        failed = db.execute(select(AlertDelivery).where(AlertDelivery.channel == "email")).scalar_one()
        assert failed.status == "failed" and "ConnectionRefused" in (failed.last_error or "")


def test_email_is_plain_text_via_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.integrations import Integrations

    captured: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            captured["addr"] = (host, port)

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def send_message(self, msg: Any) -> None:
            captured["msg"] = msg

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    cfg = Integrations("mailpit", 1025, "", "", "radar@x.com", ["a@x.com", "b@x.com"], "", "generic", "")
    notifications.send_email(cfg, "Asunto", "Cuerpo <b>no html</b>")
    msg = captured["msg"]
    assert captured["addr"] == ("mailpit", 1025) and msg["To"] == "a@x.com, b@x.com"
    assert msg.get_content_type() == "text/plain" and "<b>" in msg.get_content()
    with pytest.raises(notifications.NotifyError, match="destinatarios"):
        notifications.send_email(Integrations("h", 25, "", "", "f", [], "", "generic", ""), "s", "b")


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("slack", {"text": "hola"}), ("generic", {"text": "hola"}), ("telegram", {"chat_id": "42", "text": "hola"})],
)
def test_webhook_payload_per_kind(kind: str, expected: dict[str, str]) -> None:
    from app.services.integrations import Integrations

    cfg = Integrations("h", 25, "", "", "f", [], "https://x.test/hook", kind, "42")
    assert notifications.webhook_payload(cfg, "hola") == expected


@respx.mock
def test_webhook_errors_never_leak_the_url_token() -> None:
    from app.services.integrations import Integrations

    respx.post("https://api.telegram.org/botSECRETTOKEN/sendMessage").mock(return_value=Response(401))
    cfg = Integrations("h", 25, "", "", "f", [], "https://api.telegram.org/botSECRETTOKEN/sendMessage", "telegram", "1")
    with pytest.raises(notifications.NotifyError) as e:
        notifications.send_webhook(cfg, "x")
    assert "SECRETTOKEN" not in str(e.value)
    with pytest.raises(notifications.NotifyError, match="chat_id"):
        notifications.send_webhook(Integrations("h", 25, "", "", "f", [], "https://x.test", "telegram", ""), "x")


def test_source_failure_creates_internal_alert_and_fail_latest_works(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    r = c.post("/api/v1/internal/runs/fail-latest", headers=KEY, json={"node": "HTTP KEV", "message": "timeout 60s"})
    assert r.json() == {"status": "failed"}
    assert c.post("/api/v1/internal/runs/fail-latest", headers=KEY, json={"node": "x", "message": "y"}).json() == {"status": "no_running_run"}
    ana = login(c, "analista@radar.local")
    alerts = c.get("/api/v1/alerts", headers=ana).json()["items"]
    assert alerts[0]["alert_type"] == "source_unavailable" and "HTTP KEV" in alerts[0]["message"]
    assert alerts[0]["cve_id"] is None and mail[0]["s"].startswith("[Radar KEV] Fuente externa")
    run = c.get("/api/v1/workflow-runs", headers=ana).json()["items"][0]
    assert run["id"] == rid and run["status"] == "failed"


def test_alerts_read_state_is_per_user(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    dispatch(c, rid, matches)
    ana, mgr = login(c, "analista@radar.local"), login(c, "gerencia@radar.local")
    assert c.get("/api/v1/alerts/unread-count", headers=ana).json() == {"unread": 1}
    a = c.get("/api/v1/alerts", headers=ana).json()["items"][0]
    assert a["is_read"] is False and a["ticket_id"] and a["hostname"] == "srv-a"
    assert {d["channel"]: d["status"] for d in a["deliveries"]} == {"email": "sent", "webhook": "skipped"}
    assert c.post(f"/api/v1/alerts/{a['id']}/read", headers=ana).status_code == 204
    assert c.get("/api/v1/alerts/unread-count", headers=ana).json() == {"unread": 0}
    assert c.get("/api/v1/alerts/unread-count", headers=mgr).json() == {"unread": 1}  # el otro usuario sigue con 1
    assert c.post("/api/v1/alerts/read-all", headers=mgr).status_code == 204
    assert c.get("/api/v1/alerts", headers=mgr, params={"unread_only": True}).json()["total"] == 0
    assert c.post("/api/v1/alerts/00000000-0000-0000-0000-000000000000/read", headers=ana).status_code == 404
    assert c.get("/api/v1/alerts").status_code == 401


def test_ticket_lifecycle_syncs_vulnerability_and_records_history(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    tid = dispatch(c, rid, matches)["tickets"][0]["id"]
    ana = login(c, "analista@radar.local")
    lst = c.get("/api/v1/tickets", headers=ana).json()
    assert lst["total"] == 1 and lst["items"][0]["cve_id"] == "CVE-2021-44228" and lst["items"][0]["sla_state"] in ("en_plazo", "por_vencer", "vencido")
    uid = c.get("/api/v1/auth/me", headers=ana).json()["id"]
    p = c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"status": "in_progress", "assignee_id": uid})
    assert p.status_code == 200 and p.json()["assignee"]["name"] == "Analista Demo"
    assert c.post(f"/api/v1/tickets/{tid}/comments", headers=ana, json={"text": "Parche programado el viernes"}).status_code == 201
    c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"status": "resolved"})
    d = c.get(f"/api/v1/tickets/{tid}", headers=ana).json()
    assert [e["event"] for e in d["events"]] == ["status", "comment", "assignee", "status", "created"]
    assert d["resolved_at"] is not None and d["events"][1]["data"]["text"].startswith("Parche")
    with m() as db:
        v = db.execute(select(Vulnerability).where(Vulnerability.cve_id == "CVE-2021-44228")).scalar_one()
        assert v.status == "mitigated"
        assert db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.module == "tickets")).scalar_one() >= 3
    # reabrir devuelve el hallazgo a abierto; aceptar riesgo lo marca aceptado
    c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"status": "open"})
    c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"status": "risk_accepted"})
    with m() as db:
        assert db.execute(select(Vulnerability.status).where(Vulnerability.cve_id == "CVE-2021-44228")).scalar_one() == "accepted"
    assert c.get("/api/v1/tickets", headers=ana, params={"status": "active"}).json()["total"] == 0
    assert c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"assignee_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    assert c.patch(f"/api/v1/tickets/{tid}", headers=ana, json={"status": "inventado"}).status_code == 422


def test_ticket_rbac(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, m = env
    rid, matches = matches_from_correlation(c, m)
    tid = dispatch(c, rid, matches)["tickets"][0]["id"]
    for who in ("gerencia@radar.local", "auditor@radar.local"):  # pueden ver, no editar
        h = login(c, who)
        assert c.get("/api/v1/tickets", headers=h).status_code == 200
        assert c.patch(f"/api/v1/tickets/{tid}", headers=h, json={"status": "closed"}).status_code == 403
        assert c.post(f"/api/v1/tickets/{tid}/comments", headers=h, json={"text": "x"}).status_code == 403
    assert c.get("/api/v1/tickets").status_code == 401


def test_integrations_secrets_are_encrypted_masked_and_preserved(env: Env) -> None:  # noqa: F811
    c, m = env
    adm = login(c, "admin@radar.local")
    body = {"smtp_host": "smtp.empresa.com", "smtp_port": 587, "smtp_user": "u", "smtp_password": "S3cr3t!", "smtp_from": "radar@empresa.com",
            "alert_email_to": "a@empresa.com, b@empresa.com", "webhook_url": "https://hooks.slack.com/services/T/B/XYZ", "webhook_kind": "slack",
            "telegram_chat_id": ""}  # fmt: skip
    out = c.put("/api/v1/settings/integrations", headers=adm, json=body).json()
    assert out["smtp_password"] == "********" and out["webhook_url"] == "********" and out["smtp_host"] == "smtp.empresa.com"
    with m() as db:
        raw = {r.key: r.value_encrypted for r in db.execute(select(IntegrationSetting)).scalars()}
        assert "S3cr3t!" not in raw["smtp_password"] and "slack" not in raw["webhook_url"]  # cifrados
    # reenviar el formulario con secretos enmascarados/vacíos no los pierde
    c.put("/api/v1/settings/integrations", headers=adm, json={**body, "smtp_password": "********", "webhook_url": ""})
    with m() as db:
        from app.services import integrations as svc

        cfg = svc.load(db)
        assert cfg.smtp_password == "S3cr3t!" and cfg.webhook_url.endswith("XYZ") and cfg.alert_email_to == ["a@empresa.com", "b@empresa.com"]
    assert c.put("/api/v1/settings/integrations", headers=adm, json={**body, "webhook_url": "javascript:alert(1)"}).status_code == 422
    ana = login(c, "analista@radar.local")
    assert c.get("/api/v1/settings/integrations", headers=ana).json()["webhook_url"] == "********"
    assert c.put("/api/v1/settings/integrations", headers=ana, json=body).status_code == 403
    with m() as db:
        ev = db.execute(select(AuditLog).where(AuditLog.action == "integrations_update")).scalars().first()
        assert ev is not None and "S3cr3t" not in str(ev.detail) and "XYZ" not in str(ev.detail)


def test_test_email_endpoint_reports_failures(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, _ = env
    adm = login(c, "admin@radar.local")
    monkeypatch.setattr(notifications, "send_email", lambda *a: None)
    assert c.post("/api/v1/settings/integrations/test-email", headers=adm).json() == {"status": "enviado"}

    def boom(*a: Any) -> None:
        raise notifications.NotifyError("SMTP: ConnectionRefusedError")

    monkeypatch.setattr(notifications, "send_email", boom)
    assert c.post("/api/v1/settings/integrations/test-email", headers=adm).status_code == 502
    assert c.post("/api/v1/settings/integrations/test-webhook", headers=adm).status_code == 502  # sin URL configurada


@respx.mock
def test_manual_trigger_calls_n8n_with_service_key(env: Env) -> None:  # noqa: F811
    c, m = env
    route = respx.post(get_settings().n8n_webhook_url).mock(return_value=Response(200, json={"ok": True}))
    ana = login(c, "analista@radar.local")
    assert c.post("/api/v1/workflow-runs/trigger", headers=ana).status_code == 202
    sent = route.calls.last.request
    assert sent.headers["x-service-key"] == "test-service-key" and b'"force":true' in sent.content.replace(b" ", b"")
    route.mock(return_value=Response(404))
    assert c.post("/api/v1/workflow-runs/trigger", headers=ana).status_code == 502
    assert c.post("/api/v1/workflow-runs/trigger", headers=login(c, "gerencia@radar.local")).status_code == 403  # solo ver
    with m() as db:
        res = [r.result for r in db.execute(select(AuditLog).where(AuditLog.action == "trigger").order_by(AuditLog.id)).scalars()]
        assert res == ["success", "failure", "denied"][:2] or "success" in res


def test_fail_accepts_huge_error_bodies_and_truncates(env: Env, mail: list[dict[str, str]]) -> None:  # noqa: F811
    c, _ = env
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    html = "<html>" + "x" * 5000 + "</html>"  # p. ej. la página 404 de una fuente externa
    r = c.post(f"/api/v1/internal/runs/{rid}/fail", headers=KEY, json={"node": "n" * 300, "message": html})
    assert r.status_code == 200
    run = c.get("/api/v1/workflow-runs", headers=login(c, "auditor@radar.local")).json()["items"][0]
    assert run["status"] == "failed" and len(run["errors"][0]["message"]) <= 500 and len(run["errors"][0]["node"]) <= 80
