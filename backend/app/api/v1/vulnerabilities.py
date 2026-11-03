import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.models.inventory import VULN_STATUSES, Asset, Vulnerability

router = APIRouter(prefix="/vulnerabilities", tags=["vulnerabilidades"])

Status = Literal["open", "in_progress", "mitigated", "accepted", "false_positive"]


class AssetRef(BaseModel):
    id: uuid.UUID
    hostname: str
    ip: str | None
    criticality: int
    environment: str


class VulnOut(BaseModel):
    id: uuid.UUID
    cve_id: str
    cvss_score: float | None
    cvss_vector: str | None
    status: str
    first_seen: datetime
    last_seen: datetime
    asset: AssetRef
    # Los completa el cruce KEV/EPSS (fase 3); hasta entonces quedan nulos.
    kev_matched_at: datetime | None
    risk_score: float | None
    risk_band: str | None
    sla_due_date: date | None


class VulnList(BaseModel):
    items: list[VulnOut]
    total: int


class VulnPatch(BaseModel):
    status: Status


def to_out(v: Vulnerability) -> VulnOut:
    a = v.asset
    return VulnOut(
        id=v.id, cve_id=v.cve_id, cvss_score=float(v.cvss_score) if v.cvss_score is not None else None,
        cvss_vector=v.cvss_vector, status=v.status, first_seen=v.first_seen, last_seen=v.last_seen,
        asset=AssetRef(id=a.id, hostname=a.hostname, ip=str(a.ip) if a.ip else None,
                       criticality=a.criticality, environment=a.environment),
        kev_matched_at=v.kev_matched_at,
        risk_score=float(v.risk_score) if v.risk_score is not None else None,
        risk_band=v.risk_band, sla_due_date=v.sla_due_date,
    )


@router.get("", response_model=VulnList)
def list_vulnerabilities(
    q: str | None = None,
    status_: str | None = Query(None, alias="status"),
    asset_id: uuid.UUID | None = None,
    environment: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("vulnerabilities", "view")),
    db: Session = Depends(get_db),
) -> VulnList:
    stmt = select(Vulnerability).join(Asset, Asset.id == Vulnerability.asset_id)
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(or_(Vulnerability.cve_id.ilike(like), Asset.hostname.ilike(like)))
    if status_ in VULN_STATUSES:
        stmt = stmt.where(Vulnerability.status == status_)
    if asset_id:
        stmt = stmt.where(Vulnerability.asset_id == asset_id)
    if environment:
        stmt = stmt.where(Asset.environment == environment)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = (Vulnerability.risk_score.desc().nulls_last(), Vulnerability.cvss_score.desc().nulls_last(), Vulnerability.cve_id)
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).scalars().unique().all()
    return VulnList(items=[to_out(v) for v in rows], total=total)


@router.get("/{vuln_id}", response_model=VulnOut)
def get_vulnerability(
    vuln_id: uuid.UUID, _: User = Depends(require("vulnerabilities", "view")), db: Session = Depends(get_db)
) -> VulnOut:
    v = db.get(Vulnerability, vuln_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hallazgo no encontrado")
    return to_out(v)


@router.patch("/{vuln_id}", response_model=VulnOut)
def set_status(
    request: Request,
    vuln_id: uuid.UUID,
    body: VulnPatch,
    actor: User = Depends(require("vulnerabilities", "edit")),
    db: Session = Depends(get_db),
) -> VulnOut:
    v = db.get(Vulnerability, vuln_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hallazgo no encontrado")
    old = v.status
    v.status = body.status
    v.resolved_at = datetime.now().astimezone() if body.status in ("mitigated", "false_positive") else None
    audit(db, request, "vulnerabilities", "edit", user=actor,
          detail={"vulnerability": str(v.id), "cve": v.cve_id, "status": [old, body.status]})
    db.commit()
    return to_out(v)
