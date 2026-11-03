from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.services.correlation import correlate
from app.services.intel import get_active_config, save_new_version
from app.services.scoring import ScoringParams, band_of, base_score, risk_score, sla_due

router = APIRouter(prefix="/settings", tags=["configuración"])

FORMULA = (
    "base = w_epss·EPSS + w_percentile·percentil + w_cvss·(CVSS/10) + w_asset·(criticidad/4)\n"
    "En KEV:      score = kev_floor + (100 − kev_floor)·base  (+ bonus_ransomware si hay uso conocido en ransomware), tope 100\n"
    "Fuera de KEV: score = (kev_floor − 1)·base\n"
    "KEV domina por construcción: en KEV el score es ≥ kev_floor y fuera de KEV es < kev_floor."
)


class ScoringOut(BaseModel):
    version: int
    created_at: datetime
    params: ScoringParams
    formula: str = FORMULA


class Sample(BaseModel):
    in_kev: bool = True
    epss: float = Field(0.5, ge=0, le=1)
    percentile: float = Field(0.9, ge=0, le=1)
    cvss: float = Field(7.5, ge=0, le=10)
    criticality: int = Field(3, ge=1, le=4)
    ransomware: bool = False


class PreviewIn(BaseModel):
    params: ScoringParams
    sample: Sample = Sample()


class PreviewOut(BaseModel):
    base: float
    score: float
    band: str
    sla_days_from_detection: int


@router.get("/scoring", response_model=ScoringOut)
def get_scoring(_: User = Depends(require("settings", "view")), db: Session = Depends(get_db)) -> ScoringOut:
    row, params = get_active_config(db)
    db.commit()
    return ScoringOut(version=row.version, created_at=row.created_at, params=params)


@router.put("/scoring", response_model=ScoringOut)
def put_scoring(
    request: Request,
    params: ScoringParams,
    actor: User = Depends(require("settings", "edit")),
    db: Session = Depends(get_db),
) -> ScoringOut:
    old_row, old = get_active_config(db)
    changes = {k: [v, getattr(params, k)] for k, v in old.model_dump().items() if v != getattr(params, k)}
    row = save_new_version(db, params, actor.id)
    correlate(db, mark_matches=False)  # recalcula todo; las "nuevas coincidencias" no se tocan
    audit(db, request, "settings", "scoring_update", user=actor,
          detail={"from_version": old_row.version, "to_version": row.version, "changes": changes})
    db.commit()
    return ScoringOut(version=row.version, created_at=row.created_at, params=params)


@router.post("/scoring/preview", response_model=PreviewOut)
def preview_scoring(body: PreviewIn, _: User = Depends(require("settings", "view"))) -> PreviewOut:
    s, p = body.sample, body.params
    score = risk_score(p, in_kev=s.in_kev, epss=s.epss, percentile=s.percentile, cvss=s.cvss,
                       criticality=s.criticality, ransomware=s.ransomware)  # fmt: skip
    band = band_of(p, score)
    day = date(2000, 1, 1)
    days = (sla_due(p, band=band, detected=day) - day).days
    return PreviewOut(
        base=round(base_score(p, s.epss, s.percentile, s.cvss, s.criticality), 4),
        score=score, band=band, sla_days_from_detection=days,
    )
