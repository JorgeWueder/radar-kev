import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import require
from app.db.session import get_db
from app.models.auth import User
from app.models.intel import EpssScore, KevEntry
from app.models.inventory import Asset, Vulnerability

router = APIRouter(prefix="/kev", tags=["catálogo KEV"])

SORTS = {
    "date_added": KevEntry.date_added,
    "due_date": KevEntry.due_date,
    "cve_id": KevEntry.cve_id,
    "vendor_project": KevEntry.vendor_project,
}


class KevOut(BaseModel):
    cve_id: str
    vendor_project: str
    product: str
    vulnerability_name: str
    date_added: date
    due_date: date
    ransomware_use: str
    short_description: str
    required_action: str
    notes: str
    cwes: list[str]
    assets_affected: int
    epss: float | None
    percentile: float | None


class KevList(BaseModel):
    items: list[KevOut]
    total: int
    catalog_version: str | None
    in_environment: int


class AffectedAsset(BaseModel):
    vulnerability_id: uuid.UUID
    asset_id: uuid.UUID
    hostname: str
    criticality: int
    environment: str
    status: str
    risk_score: float | None
    sla_due_date: date | None


class EpssPoint(BaseModel):
    score_date: date
    epss: float
    percentile: float


class KevDetail(KevOut):
    affected: list[AffectedAsset]
    epss_history: list[EpssPoint]


ACTIVE = ("open", "in_progress")


def _env_counts(db: Session, cves: list[str]) -> dict[str, int]:
    if not cves:
        return {}
    rows = db.execute(
        select(Vulnerability.cve_id, func.count(func.distinct(Vulnerability.asset_id)))
        .where(Vulnerability.cve_id.in_(cves), Vulnerability.status.in_(ACTIVE))
        .group_by(Vulnerability.cve_id)
    ).all()
    return {c: n for c, n in rows}


def _latest_epss(db: Session, cves: list[str]) -> dict[str, tuple[float, float]]:
    if not cves:
        return {}
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (cve_id) cve_id, epss, percentile FROM epss_scores "
            "WHERE cve_id = ANY(:c) ORDER BY cve_id, score_date DESC"
        ),
        {"c": cves},
    ).all()
    return {r[0]: (float(r[1]), float(r[2])) for r in rows}


def _to_out(k: KevEntry, env: dict[str, int], epss: dict[str, tuple[float, float]]) -> KevOut:
    e = epss.get(k.cve_id)
    return KevOut(
        cve_id=k.cve_id, vendor_project=k.vendor_project, product=k.product,
        vulnerability_name=k.vulnerability_name, date_added=k.date_added, due_date=k.due_date,
        ransomware_use=k.ransomware_use, short_description=k.short_description,
        required_action=k.required_action, notes=k.notes, cwes=list(k.cwes or []),
        assets_affected=env.get(k.cve_id, 0), epss=e[0] if e else None, percentile=e[1] if e else None,
    )  # fmt: skip


def _filtered(
    q: str | None, vendor: str | None, ransomware: bool, in_env: bool, date_from: date | None, date_to: date | None
) -> Select[tuple[KevEntry]]:
    stmt = select(KevEntry)
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(
            or_(KevEntry.cve_id.ilike(like), KevEntry.vendor_project.ilike(like),
                KevEntry.product.ilike(like), KevEntry.vulnerability_name.ilike(like))
        )  # fmt: skip
    if vendor:
        stmt = stmt.where(KevEntry.vendor_project == vendor)
    if ransomware:
        stmt = stmt.where(KevEntry.ransomware_use == "Known")
    if in_env:
        stmt = stmt.where(
            KevEntry.cve_id.in_(select(Vulnerability.cve_id).where(Vulnerability.status.in_(ACTIVE)))
        )
    if date_from:
        stmt = stmt.where(KevEntry.date_added >= date_from)
    if date_to:
        stmt = stmt.where(KevEntry.date_added <= date_to)
    return stmt


@router.get("", response_model=KevList)
def list_kev(
    q: str | None = None,
    vendor: str | None = Query(None, max_length=200),
    ransomware: bool = False,
    in_environment: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["date_added", "due_date", "cve_id", "vendor_project"] = "date_added",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("kev", "view")),
    db: Session = Depends(get_db),
) -> KevList:
    stmt = _filtered(q, vendor, ransomware, in_environment, date_from, date_to)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    col = SORTS[sort]
    rows = db.execute(
        stmt.order_by(col.desc() if direction == "desc" else col.asc(), KevEntry.cve_id).limit(limit).offset(offset)
    ).scalars().all()
    cves = [r.cve_id for r in rows]
    env, epss = _env_counts(db, cves), _latest_epss(db, cves)
    version = db.execute(select(func.max(KevEntry.catalog_version))).scalar()
    n_env = db.execute(
        select(func.count(func.distinct(KevEntry.cve_id)))
        .join(Vulnerability, Vulnerability.cve_id == KevEntry.cve_id)
        .where(Vulnerability.status.in_(ACTIVE))
    ).scalar_one()
    return KevList(items=[_to_out(r, env, epss) for r in rows], total=total, catalog_version=version, in_environment=n_env)


@router.get("/vendors", response_model=list[str])
def vendors(_: User = Depends(require("kev", "view")), db: Session = Depends(get_db)) -> list[str]:
    return list(db.execute(select(KevEntry.vendor_project).distinct().order_by(KevEntry.vendor_project)).scalars())


@router.get("/{cve_id}", response_model=KevDetail)
def kev_detail(
    cve_id: str, _: User = Depends(require("kev", "view")), db: Session = Depends(get_db)
) -> KevDetail:
    k = db.get(KevEntry, cve_id.upper())
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CVE no está en el catálogo KEV")
    base = _to_out(k, _env_counts(db, [k.cve_id]), _latest_epss(db, [k.cve_id]))
    affected = db.execute(
        select(Vulnerability, Asset).join(Asset, Asset.id == Vulnerability.asset_id)
        .where(Vulnerability.cve_id == k.cve_id).order_by(Asset.criticality.desc(), Asset.hostname)
    ).all()
    hist = db.execute(
        select(EpssScore).where(EpssScore.cve_id == k.cve_id).order_by(EpssScore.score_date.desc()).limit(30)
    ).scalars().all()
    return KevDetail(
        **base.model_dump(),
        affected=[
            AffectedAsset(
                vulnerability_id=v.id, asset_id=a.id, hostname=a.hostname, criticality=a.criticality,
                environment=a.environment, status=v.status,
                risk_score=float(v.risk_score) if isinstance(v.risk_score, Decimal) else None,
                sla_due_date=v.sla_due_date,
            )
            for v, a in affected
        ],
        epss_history=[EpssPoint(score_date=h.score_date, epss=float(h.epss), percentile=float(h.percentile)) for h in hist],
    )
