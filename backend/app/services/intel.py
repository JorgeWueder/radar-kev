"""Ingesta de KEV y EPSS, y acceso a la configuración de score activa."""

import gzip
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.intel import EpssScore, KevEntry, ScoringConfig
from app.services.scoring import ScoringParams

CVE_PATTERN = r"^CVE-\d{4}-\d{4,}$"


class IntelError(ValueError):
    """Los datos externos no cumplen el esquema esperado (se registra como fallo de la ejecución)."""


# --------------------------------------------------------------------------- configuración de score
def get_active_config(db: Session) -> tuple[ScoringConfig, ScoringParams]:
    row = db.execute(select(ScoringConfig).where(ScoringConfig.is_active)).scalar_one_or_none()
    if row is None:
        params = ScoringParams()
        w, b, s = params.to_columns()
        row = ScoringConfig(version=1, weights=w, bands=b, sla_days=s, is_active=True)
        db.add(row)
        db.flush()
    return row, ScoringParams.from_columns(row.weights, row.bands, row.sla_days)


def save_new_version(db: Session, params: ScoringParams, user_id: Any) -> ScoringConfig:
    current, _ = get_active_config(db)
    current.is_active = False
    db.flush()  # libera el índice único parcial antes de activar la nueva versión
    max_version = db.execute(select(func.max(ScoringConfig.version))).scalar_one()
    w, b, s = params.to_columns()
    row = ScoringConfig(
        version=(max_version or 0) + 1, weights=w, bands=b, sla_days=s, is_active=True, created_by=user_id
    )
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------------------- KEV
class KevItem(BaseModel):
    """Campos verificados el 2026-11-03; los desconocidos se ignoran (CISA añade campos, p. ej. forensicTriage)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    cve_id: str = Field(alias="cveID", pattern=CVE_PATTERN)
    vendor_project: str = Field("", alias="vendorProject")
    product: str = ""
    vulnerability_name: str = Field("", alias="vulnerabilityName")
    date_added: date = Field(alias="dateAdded")
    short_description: str = Field("", alias="shortDescription")
    required_action: str = Field("", alias="requiredAction")
    due_date: date = Field(alias="dueDate")
    ransomware_use: str = Field("Unknown", alias="knownRansomwareCampaignUse")
    forensic_triage: str | None = Field(None, alias="forensicTriage")
    notes: str = ""
    cwes: list[str] = []

    @field_validator("cwes", mode="before")
    @classmethod
    def _cwes(cls, v: Any) -> Any:
        return v or []


class KevCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    catalog_version: str = Field(alias="catalogVersion")
    count: int | None = None
    vulnerabilities: list[KevItem]


def ingest_kev(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        catalog = KevCatalog.model_validate(payload)
    except ValidationError as e:
        first = e.errors()[0]
        raise IntelError(f"Esquema KEV inesperado en {'.'.join(map(str, first['loc']))}: {first['msg']}") from None
    if not catalog.vulnerabilities:
        raise IntelError("El catálogo KEV llegó vacío")
    now = datetime.now(UTC)
    existing = set(db.execute(select(KevEntry.cve_id)).scalars())
    rows = []
    for it in catalog.vulnerabilities:
        rows.append(
            {
                "cve_id": it.cve_id, "vendor_project": it.vendor_project, "product": it.product,
                "vulnerability_name": it.vulnerability_name, "date_added": it.date_added,
                "short_description": it.short_description, "required_action": it.required_action,
                "due_date": it.due_date, "ransomware_use": it.ransomware_use,
                "forensic_triage": it.forensic_triage, "notes": it.notes, "cwes": it.cwes,
                "catalog_version": catalog.catalog_version, "first_seen_at": now, "last_seen_at": now,
            }
        )  # fmt: skip
    rows = list({r["cve_id"]: r for r in rows}.values())  # CVE repetido en el feed: gana el último
    for i in range(0, len(rows), 500):
        stmt = insert(KevEntry).values(rows[i : i + 500])
        update_cols = {
            c: getattr(stmt.excluded, c)
            for c in rows[0]
            if c not in ("cve_id", "first_seen_at")  # first_seen_at se conserva: marca cuándo apareció
        }
        db.execute(stmt.on_conflict_do_update(index_elements=["cve_id"], set_=update_cols))
    new = len({r["cve_id"] for r in rows} - existing)
    return {"catalog_version": catalog.catalog_version, "total": len(rows), "new_entries": new}


# --------------------------------------------------------------------------- EPSS
class EpssItem(BaseModel):
    """La API devuelve los números como string ("0.999990000"); Pydantic los convierte."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    cve: str = Field(pattern=CVE_PATTERN)
    epss: Decimal = Field(ge=0, le=1)
    percentile: Decimal = Field(ge=0, le=1)
    score_date: date | None = Field(None, alias="date")


def ingest_epss(
    db: Session, items: list[dict[str, Any]], score_date: date | None = None, model_version: str | None = None
) -> dict[str, int]:
    parsed: list[EpssItem] = []
    invalid = 0
    for raw in items:
        try:
            parsed.append(EpssItem.model_validate(raw))
        except ValidationError:
            invalid += 1
    default_date = score_date or datetime.now(UTC).date()
    rows = [
        {"cve_id": p.cve.upper(), "score_date": p.score_date or default_date, "epss": p.epss,
         "percentile": p.percentile, "model_version": model_version}
        for p in parsed
    ]  # fmt: skip
    # Un mismo (CVE, fecha) repetido en el lote haría fallar el UPSERT: gana el último valor.
    rows = list({(r["cve_id"], r["score_date"]): r for r in rows}.values())
    for i in range(0, len(rows), 1000):
        stmt = insert(EpssScore).values(rows[i : i + 1000])
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["cve_id", "score_date"],
                set_={"epss": stmt.excluded.epss, "percentile": stmt.excluded.percentile,
                      "model_version": stmt.excluded.model_version},
            )
        )  # fmt: skip
    return {"scored": len(rows), "invalid": invalid}


def parse_epss_csv(gz_bytes: bytes, only: set[str] | None = None) -> tuple[list[dict[str, Any]], date, str | None]:
    """CSV diario completo (gz). Primera línea: '#model_version:...,score_date:...'; luego cve,epss,percentile."""
    text = gzip.decompress(gz_bytes)
    first = text.split(b"\n", 1)[0].decode("utf-8", "replace")
    if not first.startswith("#"):
        raise IntelError("El CSV de EPSS no trae la línea de metadatos esperada")
    meta = dict(p.split(":", 1) for p in first.lstrip("#").strip().split(",") if ":" in p)
    try:
        sdate = datetime.fromisoformat(meta["score_date"].replace("Z", "+00:00")).date()
    except (KeyError, ValueError):
        raise IntelError("No se pudo leer score_date del CSV de EPSS") from None
    df = pd.read_csv(io.BytesIO(text), comment="#", dtype={"cve": str})
    if not {"cve", "epss", "percentile"} <= set(df.columns):
        raise IntelError("El CSV de EPSS no tiene las columnas cve, epss, percentile")
    if only is not None:
        df = df[df["cve"].isin(only)]
    items = [
        {"cve": r.cve, "epss": str(r.epss), "percentile": str(r.percentile)}
        for r in df.itertuples(index=False)
    ]
    return items, sdate, meta.get("model_version")
