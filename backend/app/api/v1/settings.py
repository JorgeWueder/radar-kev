from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.services import integrations, notifications
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


class IntegrationsIn(BaseModel):
    """Los secretos (contraseña SMTP, URL del webhook) vacíos o enmascarados conservan el valor actual."""

    smtp_host: str = Field("", max_length=255)
    smtp_port: int = Field(1025, ge=1, le=65535)
    smtp_user: str = Field("", max_length=255)
    smtp_password: str = Field("", max_length=255)
    smtp_from: str = Field("", max_length=255)
    alert_email_to: str = Field("", max_length=1000)
    webhook_url: str = Field("", max_length=1000, pattern=r"^(https?://\S+|\*{8}|)$")
    webhook_kind: str = Field("generic", pattern="^(generic|slack|teams|telegram)$")
    telegram_chat_id: str = Field("", max_length=60)


@router.get("/integrations")
def get_integrations(
    _: User = Depends(require("settings", "view")), db: Session = Depends(get_db)
) -> dict[str, str]:
    return integrations.masked(db)


@router.put("/integrations")
def put_integrations(
    request: Request,
    body: IntegrationsIn,
    actor: User = Depends(require("settings", "edit")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    values = {k: str(v) for k, v in body.model_dump().items()}
    changed = integrations.save(db, values)
    audit(db, request, "settings", "integrations_update", user=actor, detail={"keys": sorted(changed)})
    db.commit()
    return integrations.masked(db)


@router.post("/integrations/test-email")
def test_email(
    request: Request, actor: User = Depends(require("settings", "edit")), db: Session = Depends(get_db)
) -> dict[str, str]:
    try:
        notifications.send_email(integrations.load(db), "[Radar KEV] Prueba de correo", "Canal de correo configurado correctamente.")
    except notifications.NotifyError as e:
        audit(db, request, "settings", "test_email", user=actor, result="failure", detail={"error": str(e)})
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    audit(db, request, "settings", "test_email", user=actor)
    db.commit()
    return {"status": "enviado"}


@router.post("/integrations/test-webhook")
def test_webhook(
    request: Request, actor: User = Depends(require("settings", "edit")), db: Session = Depends(get_db)
) -> dict[str, str]:
    try:
        notifications.send_webhook(integrations.load(db), "[Radar KEV] Prueba de webhook: canal configurado correctamente.")
    except notifications.NotifyError as e:
        audit(db, request, "settings", "test_webhook", user=actor, result="failure", detail={"error": str(e)})
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    audit(db, request, "settings", "test_webhook", user=actor)
    db.commit()
    return {"status": "enviado"}
