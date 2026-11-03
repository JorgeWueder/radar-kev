import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.models.intel import KevEntry
from app.models.inventory import VULN_STATUSES, Asset, Vulnerability
from app.services.intel import get_active_config
from app.services.scoring import ScoringParams, sla_state

router = APIRouter(prefix="/vulnerabilities", tags=["vulnerabilidades"])

Status = Literal["open", "in_progress", "mitigated", "accepted", "false_positive"]
ACTIVE = ("open", "in_progress")


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
    in_kev: bool
    kev_due_date: date | None
    ransomware: bool
    epss: float | None
    percentile: float | None
    kev_matched_at: datetime | None
    risk_score: float | None
    risk_band: str | None
    sla_due_date: date | None
    sla_state: str


class VulnList(BaseModel):
    items: list[VulnOut]
    total: int


class VulnPatch(BaseModel):
    status: Status


def _enrich(db: Session, rows: list[Vulnerability]) -> list[VulnOut]:
    cves = sorted({v.cve_id for v in rows})
    kev = {k.cve_id: k for k in db.execute(select(KevEntry).where(KevEntry.cve_id.in_(cves))).scalars()} if cves else {}
    epss = {
        r[0]: (float(r[1]), float(r[2]))
        for r in db.execute(
            text("SELECT DISTINCT ON (cve_id) cve_id, epss, percentile FROM epss_scores "
                 "WHERE cve_id = ANY(:c) ORDER BY cve_id, score_date DESC"),
            {"c": cves},
        ).all()
    } if cves else {}  # fmt: skip
    _, params = get_active_config(db)
    today = datetime.now(UTC).date()
    out: list[VulnOut] = []
    for v in rows:
        a, k, e = v.asset, kev.get(v.cve_id), epss.get(v.cve_id)
        out.append(
            VulnOut(
                id=v.id, cve_id=v.cve_id, cvss_score=float(v.cvss_score) if v.cvss_score is not None else None,
                cvss_vector=v.cvss_vector, status=v.status, first_seen=v.first_seen, last_seen=v.last_seen,
                asset=AssetRef(id=a.id, hostname=a.hostname, ip=str(a.ip) if a.ip else None,
                               criticality=a.criticality, environment=a.environment),
                in_kev=k is not None, kev_due_date=k.due_date if k else None,
                ransomware=bool(k and k.ransomware_use == "Known"),
                epss=e[0] if e else None, percentile=e[1] if e else None,
                kev_matched_at=v.kev_matched_at,
                risk_score=float(v.risk_score) if isinstance(v.risk_score, Decimal) else None,
                risk_band=v.risk_band, sla_due_date=v.sla_due_date,
                sla_state=_state(params, v, today),
            )
        )  # fmt: skip
    return out


def _state(params: ScoringParams, v: Vulnerability, today: date) -> str:
    return sla_state(params, v.sla_due_date, today, active=v.status in ACTIVE)


@router.get("", response_model=VulnList)
def list_vulnerabilities(
    q: str | None = None,
    status_: str | None = Query(None, alias="status"),
    asset_id: uuid.UUID | None = None,
    environment: str | None = None,
    kev: bool = False,
    overdue: bool = False,
    band: Literal["critical", "high", "medium", "low"] | None = None,
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
    if kev:
        stmt = stmt.where(Vulnerability.cve_id.in_(select(KevEntry.cve_id)))
    if overdue:
        stmt = stmt.where(Vulnerability.status.in_(ACTIVE), Vulnerability.sla_due_date < datetime.now(UTC).date())
    if band:
        stmt = stmt.where(Vulnerability.risk_band == band)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = (Vulnerability.risk_score.desc().nulls_last(), Vulnerability.cvss_score.desc().nulls_last(), Vulnerability.cve_id)
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).scalars().unique().all()
    return VulnList(items=_enrich(db, list(rows)), total=total)


@router.get("/{vuln_id}", response_model=VulnOut)
def get_vulnerability(
    vuln_id: uuid.UUID, _: User = Depends(require("vulnerabilities", "view")), db: Session = Depends(get_db)
) -> VulnOut:
    v = db.get(Vulnerability, vuln_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hallazgo no encontrado")
    return _enrich(db, [v])[0]


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
    v.resolved_at = datetime.now(UTC) if body.status in ("mitigated", "false_positive") else None
    audit(db, request, "vulnerabilities", "edit", user=actor,
          detail={"vulnerability": str(v.id), "cve": v.cve_id, "status": [old, body.status]})
    db.commit()
    return _enrich(db, [v])[0]
