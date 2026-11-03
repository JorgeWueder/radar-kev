import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
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
