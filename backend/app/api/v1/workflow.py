import uuid
from datetime import date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import User
from app.models.intel import WorkflowRun

router = APIRouter(prefix="/workflow-runs", tags=["ejecuciones"])


class RunOut(BaseModel):
    id: uuid.UUID
    run_date: date
    trigger: str
    status: str
    kev_catalog_version: str | None
    kev_total: int
    epss_scored: int
    new_matches: int
    alerts_created: int
    errors: list[dict[str, object]]
    started_at: datetime
    finished_at: datetime | None


class RunList(BaseModel):
    items: list[RunOut]
    total: int


@router.get("", response_model=RunList)
def list_runs(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("workflow", "view")),
    db: Session = Depends(get_db),
) -> RunList:
    total = db.execute(select(func.count()).select_from(WorkflowRun)).scalar_one()
    rows = db.execute(select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(limit).offset(offset)).scalars().all()
    return RunList(items=[RunOut.model_validate(r, from_attributes=True) for r in rows], total=total)


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger(
    request: Request, actor: User = Depends(require("workflow", "create")), db: Session = Depends(get_db)
) -> dict[str, str]:
    """Dispara el workflow de n8n ahora (webhook autenticado con la clave de servicio)."""
    cfg = get_settings()
    try:
        r = httpx.post(
            cfg.n8n_webhook_url,
            json={"trigger": "manual", "force": True, "by": actor.email},
            headers={"X-Service-Key": cfg.radar_service_key.get_secret_value()},
            timeout=20,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        audit(db, request, "workflow", "trigger", user=actor, result="failure", detail={"error": e.__class__.__name__})
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No se pudo contactar con n8n; verifique que el workflow esté activo") from None
    audit(db, request, "workflow", "trigger", user=actor)
    db.commit()
    return {"status": "iniciado"}
