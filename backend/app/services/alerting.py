"""Alertas urgentes y tickets por cada nueva coincidencia KEV en el entorno.

Idempotencia: UNIQUE(alerts.vulnerability_id, alert_type) y UNIQUE(tickets.vulnerability_id) más
INSERT … ON CONFLICT DO NOTHING; solo lo realmente nuevo se notifica. Ejecutar dos veces el mismo día
no duplica alertas, tickets ni correos."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.intel import KevEntry, WorkflowRun
from app.models.inventory import Asset, Vulnerability
from app.models.ops import Alert, AlertDelivery, Ticket, TicketEvent, ticket_code_seq
from app.services import integrations, notifications
from app.services.notifications import NotifyError

MAX_LINES = 30
CRITICALITY = {1: "Baja", 2: "Media", 3: "Alta", 4: "Crítica"}


class Match(BaseModel):
    vulnerability_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    hostname: str = Field(max_length=255)
    cve_id: str = Field(pattern=r"^CVE-\d{4}-\d{4,}$")
    criticality: int = Field(ge=1, le=4)
    risk_score: float = Field(ge=0, le=100)
    risk_band: str = Field(pattern="^(critical|high|medium|low)$")
    sla_due_date: date
    kev_due_date: date | None = None
    ransomware: bool = False
    epss: float | None = None
    vulnerability_name: str = Field("", max_length=500)


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def ticket_description(m: Match, kev: KevEntry | None, asset: Asset | None) -> str:
    """Descripción determinista (sin IA); el enriquecimiento con IA se agrega aparte y se marca como tal."""
    lines = [
        f"{m.cve_id} está en el catálogo KEV de CISA: explotación activa confirmada.",
        f"Activo afectado: {m.hostname} (criticidad {CRITICALITY[m.criticality]}"
        + (f", entorno {asset.environment}" if asset else "")
        + ").",
        f"Riesgo {m.risk_score:.1f} ({m.risk_band})"
        + (f", EPSS {m.epss * 100:.1f} %" if m.epss is not None else ", sin dato de EPSS")
        + (", uso conocido en campañas de ransomware" if m.ransomware else "")
        + ".",
        f"Fecha límite de remediación (SLA): {_fmt(m.sla_due_date)}.",
    ]
    if kev:
        lines += [f"Descripción (CISA): {kev.short_description}", f"Acción requerida (CISA): {kev.required_action}"]
    return "\n".join(lines)


def digest_text(matches: list[Match]) -> tuple[str, str]:
    n = len(matches)
    subject = f"[URGENTE] {n} nueva{'s' if n != 1 else ''} vulnerabilidad{'es' if n != 1 else ''} KEV en su entorno"
    lines = [
        f"El cruce diario detectó {n} CVE del catálogo KEV de CISA (explotación activa) presentes en su inventario.",
        "",
    ]
    for m in sorted(matches, key=lambda x: -x.risk_score)[:MAX_LINES]:
        lines.append(
            f"- {m.cve_id} | {m.hostname} (criticidad {CRITICALITY[m.criticality]}) | riesgo {m.risk_score:.1f}"
            f" | SLA {_fmt(m.sla_due_date)}" + (" | ransomware" if m.ransomware else "")
        )
    if n > MAX_LINES:
        lines.append(f"… y {n - MAX_LINES} más.")
    lines += ["", f"Revise los tickets: {get_settings().app_url}/tickets"]
    return subject, "\n".join(lines)


def _deliver(db: Session, alert_ids: list[uuid.UUID], subject: str, body: str) -> dict[str, str]:
    """Envía el resumen por cada canal y registra el resultado por alerta. Un canal caído no detiene al otro."""
    cfg = integrations.load(db)
    results: dict[str, str] = {}
    channels: dict[str, tuple[bool, Callable[[], None]]] = {
        "email": (bool(cfg.alert_email_to), lambda: notifications.send_email(cfg, subject, body)),
        "webhook": (bool(cfg.webhook_url), lambda: notifications.send_webhook(cfg, f"{subject}\n\n{body}")),
    }
    for channel, (configured, send) in channels.items():
        status, error = "skipped", "Canal no configurado"
        if configured:
            try:
                send()
                status, error = "sent", ""
            except NotifyError as e:
                status, error = "failed", str(e)
        results[channel] = status
        for aid in alert_ids:
            db.add(AlertDelivery(alert_id=aid, channel=channel, status=status, attempts=int(configured),
                                 last_error=error or None))  # fmt: skip
    db.flush()
    return results


def dispatch_matches(db: Session, run: WorkflowRun | None, matches: list[Match]) -> dict[str, Any]:
    new_alert_ids: list[uuid.UUID] = []
    new_matches: list[Match] = []
    tickets: list[dict[str, str]] = []
    skipped = 0
    for m in matches:
        vuln = db.get(Vulnerability, m.vulnerability_id)
        if vuln is None:
            skipped += 1
            continue
        stmt = (
            insert(Alert)
            .values(
                id=uuid.uuid4(), vulnerability_id=vuln.id, alert_type="kev_new_in_env", severity=m.risk_band,
                message=f"{m.cve_id} en {m.hostname}: nueva vulnerabilidad KEV (riesgo {m.risk_score:.1f}, "
                        f"SLA {_fmt(m.sla_due_date)})",
                workflow_run_id=run.id if run else None, created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["vulnerability_id", "alert_type"])
            .returning(Alert.id)
        )  # fmt: skip
        alert_id = db.execute(stmt).scalar()
        if alert_id is None:
            continue  # ya se alertó antes por este hallazgo
        new_alert_ids.append(alert_id)
        new_matches.append(m)
        if db.execute(select(Ticket.id).where(Ticket.vulnerability_id == vuln.id)).first() is None:
            code = f"RAD-{db.execute(ticket_code_seq.next_value()).scalar_one():06d}"
            asset = db.get(Asset, vuln.asset_id)
            kev = db.get(KevEntry, m.cve_id)
            t = Ticket(
                code=code, vulnerability_id=vuln.id, status="open", priority=m.risk_band, due_date=m.sla_due_date,
                title=f"{m.cve_id} en {m.hostname}" + (f": {kev.vulnerability_name}" if kev else ""),
                description=ticket_description(m, kev, asset),
            )  # fmt: skip
            t.title = t.title[:300]
            db.add(t)
            db.flush()
            db.add(TicketEvent(ticket_id=t.id, event="created", data={"source": "workflow", "alert": str(alert_id)}))
            tickets.append({"id": str(t.id), "code": code, "cve_id": m.cve_id, "hostname": m.hostname})
    delivery: dict[str, str] = {}
    if new_matches:
        subject, body = digest_text(new_matches)
        delivery = _deliver(db, new_alert_ids, subject, body)
    if run:
        run.alerts_created += len(new_alert_ids)
    return {"received": len(matches), "created_alerts": len(new_alert_ids), "created_tickets": len(tickets),
            "skipped": skipped, "tickets": tickets, "delivery": delivery}  # fmt: skip


def source_failure_alert(db: Session, run: WorkflowRun, node: str, message: str) -> None:
    """Alerta interna cuando una fuente externa no responde (el núcleo sigue operando con los datos previos)."""
    text = f"Fuente externa no disponible en el flujo diario (nodo {node}): {message[:300]}"
    alert = Alert(alert_type="source_unavailable", severity="high", message=text, workflow_run_id=run.id)
    db.add(alert)
    db.flush()
    _deliver(db, [alert.id], "[Radar KEV] Fuente externa no disponible", text)


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    from app.models.ops import AlertRead

    total = db.execute(select(func.count()).select_from(Alert)).scalar_one()
    read = db.execute(select(func.count()).select_from(AlertRead).where(AlertRead.user_id == user_id)).scalar_one()
    return max(0, total - read)
