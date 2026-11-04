"""Endpoints para n8n (red interna de Docker), protegidos con API key de servicio.
n8n NUNCA escribe en las tablas de la app: todo pasa por aquí, validado y auditado."""

import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai.enrichment import EnrichmentError, Ungrounded, enrich_ticket
from app.core.config import get_settings
from app.db.session import get_db
from app.models.intel import WorkflowRun
from app.models.inventory import Vulnerability
from app.models.ops import Ticket
from app.services import feeds
from app.services.alerting import Match, dispatch_matches, source_failure_alert
from app.services.audit import write_audit
from app.services.correlation import correlate
from app.services.intel import IntelError, ingest_epss, ingest_kev, parse_epss_csv


def require_service_key(x_service_key: str | None = Header(default=None)) -> None:
    expected = get_settings().radar_service_key.get_secret_value()
    # Comparación en tiempo constante; sin clave configurada el módulo queda cerrado.
    if not expected or not x_service_key or not hmac.compare_digest(x_service_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Clave de servicio inválida")


router = APIRouter(
    prefix="/internal", tags=["interno"], dependencies=[Depends(require_service_key)], include_in_schema=False
)


class StartIn(BaseModel):
    trigger: str = Field("cron", pattern="^(cron|manual)$")
    force: bool = False
    n8n_execution_id: str | None = Field(None, max_length=40)


class RunRef(BaseModel):
    run_id: uuid.UUID


class EpssIn(RunRef):
    items: list[dict[str, Any]] = Field(max_length=50_000)
    score_date: str | None = None


class DispatchIn(RunRef):
    matches: list[Match] = Field(max_length=5000)


class FailIn(BaseModel):
    """Los errores de fuentes externas pueden ser páginas HTML enteras: se truncan, nunca se rechazan."""

    node: str
    message: str

    @field_validator("node", mode="before")
    @classmethod
    def _node(cls, v: object) -> str:
        return str(v)[:80]

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, v: object) -> str:
        return str(v)[:1000]


def _run(db: Session, run_id: uuid.UUID) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ejecución no encontrada")
    return run


def _sys_audit(db: Session, action: str, result: str = "success", detail: dict[str, Any] | None = None) -> None:
    write_audit(db, module="workflow", action=action, result=result, actor="system:n8n", detail=detail)


def _add_error(run: WorkflowRun, node: str, message: str) -> None:
    run.errors = [*run.errors, {"node": node, "message": message[:500], "at": datetime.now(UTC).isoformat()}]


@router.post("/runs/start")
def start_run(body: StartIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    done = db.execute(
        select(WorkflowRun).where(WorkflowRun.run_date == today, WorkflowRun.status.in_(("success", "partial")))
    ).scalars().first()
    if done and not body.force:  # idempotencia de la ejecución diaria
        return {"skipped": True, "run_id": str(done.id), "reason": "Ya hubo una ejecución exitosa hoy"}
    run = WorkflowRun(run_date=today, trigger=body.trigger, n8n_execution_id=body.n8n_execution_id)
    db.add(run)
    db.flush()
    _sys_audit(db, "run_start", detail={"run": str(run.id), "trigger": body.trigger})
    db.commit()
    return {"skipped": False, "run_id": str(run.id)}


@router.get("/inventory/cves")
def inventory_cves(db: Session = Depends(get_db)) -> dict[str, Any]:
    cves = sorted(
        set(db.execute(select(Vulnerability.cve_id).where(Vulnerability.status.in_(("open", "in_progress")))).scalars())
    )
    return {"count": len(cves), "cves": cves}


@router.post("/kev/ingest")
def kev_ingest(
    payload: dict[str, Any] = Body(...), run_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> dict[str, Any]:
    run = _run(db, run_id) if run_id else None
    try:
        out = ingest_kev(db, payload)
    except IntelError as e:
        db.rollback()
        if run_id:
            run = _run(db, run_id)
            _add_error(run, "kev_ingest", str(e))
            db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    if run:
        run.kev_catalog_version, run.kev_total = out["catalog_version"], out["total"]
    _sys_audit(db, "kev_ingest", detail=out)
    db.commit()
    return out


@router.post("/epss/ingest")
def epss_ingest(body: EpssIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = _run(db, body.run_id)
    sdate = datetime.fromisoformat(body.score_date).date() if body.score_date else None
    out = ingest_epss(db, body.items, sdate)
    run.epss_scored += out["scored"]
    _sys_audit(db, "epss_ingest", detail=out)
    db.commit()
    return out


@router.post("/epss/fallback")
def epss_fallback(body: RunRef, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Si la API de EPSS no responde, usa el CSV diario completo filtrado al inventario."""
    run = _run(db, body.run_id)
    cves = set(db.execute(select(Vulnerability.cve_id)).scalars())
    try:
        items, sdate, version = parse_epss_csv(feeds.fetch_epss_csv(), cves)
    except (RuntimeError, IntelError) as e:
        _add_error(run, "epss_fallback", str(e))
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "EPSS no disponible (API ni CSV)") from None
    out = ingest_epss(db, items, sdate, version)
    run.epss_scored += out["scored"]
    _add_error(run, "epss_api", "API de EPSS no disponible; se usó el CSV diario")
    _sys_audit(db, "epss_fallback_csv", result="success", detail=out)
    db.commit()
    return {**out, "source": "csv"}


@router.post("/correlate")
def run_correlation(body: RunRef, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = _run(db, body.run_id)
    res = correlate(db)
    run.new_matches = len(res.new_matches)
    _sys_audit(
        db, "correlate",
        detail={"total": res.total, "in_kev": res.in_kev, "new_matches": len(res.new_matches)},
    )  # fmt: skip
    db.commit()
    return {
        "total": res.total, "in_kev": res.in_kev, "epss_missing": res.epss_missing,
        "new_matches": res.new_matches,
    }  # fmt: skip


@router.post("/alerts/dispatch")
def alerts_dispatch(body: DispatchIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Crea alerta + ticket por cada coincidencia NUEVA y avisa por correo/webhook (idempotente)."""
    run = _run(db, body.run_id)
    out = dispatch_matches(db, run, body.matches)
    _sys_audit(db, "alerts_dispatch", detail={k: v for k, v in out.items() if k != "tickets"})
    db.commit()
    return out


@router.post("/tickets/{ticket_id}/enrich")
def enrich(ticket_id: uuid.UUID, run_id: uuid.UUID | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Enriquece un ticket con IA. La IA es opcional: si falla, se responde 200 con el estado y el flujo continúa
    (el fallo se anota en la ejecución, que queda "con avisos"), nunca se detiene la detección."""
    with providers.llm_slot():  # la cola espera aquí, sin retener una conexión de base de datos
        return _enrich(db, ticket_id, run_id)


def _enrich(db: Session, ticket_id: uuid.UUID, run_id: uuid.UUID | None) -> dict[str, Any]:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket no encontrado")
    try:
        result = enrich_ticket(db, ticket, user_id=None, actor="system:n8n")
    except (providers.AIUnavailable, EnrichmentError) as e:
        db.commit()  # conserva el registro de la interacción fallida
        if run_id and (run := db.get(WorkflowRun, run_id)):
            _add_error(run, "enriquecimiento_ia", f"{ticket.code}: {e}")
            db.commit()
        return {"status": "ungrounded" if isinstance(e, Ungrounded) else "unavailable", "ticket": ticket.code, "detail": str(e)[:300]}
    db.commit()
    return {"status": "enriched", "ticket": ticket.code, "fuentes": result.fuentes}


@router.post("/runs/fail-latest")
def fail_latest(body: FailIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Lo usa el workflow de errores de n8n, que no conoce el run_id: marca como fallida la última en curso."""
    run = db.execute(
        select(WorkflowRun).where(WorkflowRun.status == "running").order_by(WorkflowRun.started_at.desc())
    ).scalars().first()
    if run is None:
        return {"status": "no_running_run"}
    return fail_run(run.id, body, db)


@router.post("/runs/{run_id}/finish")
def finish_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = _run(db, run_id)
    run.status = "partial" if run.errors else "success"
    run.finished_at = datetime.now(UTC)
    _sys_audit(db, "run_finish", detail={"run": str(run.id), "status": run.status, "new_matches": run.new_matches})
    db.commit()
    return {"status": run.status}


@router.post("/runs/{run_id}/fail")
def fail_run(run_id: uuid.UUID, body: FailIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = _run(db, run_id)
    _add_error(run, body.node, body.message)
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    _sys_audit(db, "run_fail", result="failure", detail={"run": str(run.id), "node": body.node, "message": body.message})
    try:
        source_failure_alert(db, run, body.node, body.message)
    except Exception:  # la alerta es un extra: nunca debe impedir registrar el fallo
        db.rollback()
        run = _run(db, run_id)
        run.status = "failed"
    db.commit()
    return {"status": "failed"}
