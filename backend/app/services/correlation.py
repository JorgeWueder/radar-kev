"""Cruce de inventario × KEV × EPSS con pandas (determinista; nunca depende de un LLM)."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.models.intel import ExposureSnapshot, KevEntry
from app.models.inventory import Asset, Vulnerability
from app.services.intel import get_active_config
from app.services.scoring import ScoringParams, band_of, risk_score, sla_due, sla_state

ACTIVE = ("open", "in_progress")


@dataclass
class CorrelationResult:
    total: int = 0
    in_kev: int = 0
    epss_missing: int = 0
    new_matches: list[dict[str, Any]] = field(default_factory=list)


def _latest_epss(db: Session) -> pd.DataFrame:
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (cve_id) cve_id, epss, percentile, score_date "
            "FROM epss_scores ORDER BY cve_id, score_date DESC"
        )
    ).mappings().all()
    df = pd.DataFrame(rows, columns=["cve_id", "epss", "percentile", "score_date"])
    for col in ("epss", "percentile"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_frame(db: Session) -> pd.DataFrame:
    vulns = pd.DataFrame(
        db.execute(
            select(
                Vulnerability.id.label("vuln_id"), Vulnerability.asset_id, Vulnerability.cve_id,
                Vulnerability.cvss_score, Vulnerability.status, Vulnerability.first_seen,
                Vulnerability.kev_matched_at, Asset.hostname, Asset.criticality,
            ).join(Asset, Asset.id == Vulnerability.asset_id)
        ).mappings().all(),
        columns=["vuln_id", "asset_id", "cve_id", "cvss_score", "status", "first_seen",
                 "kev_matched_at", "hostname", "criticality"],
    )  # fmt: skip
    kev = pd.DataFrame(
        db.execute(
            select(KevEntry.cve_id, KevEntry.date_added, KevEntry.due_date, KevEntry.ransomware_use,
                   KevEntry.vulnerability_name, KevEntry.required_action)
        ).mappings().all(),
        columns=["cve_id", "date_added", "due_date", "ransomware_use", "vulnerability_name", "required_action"],
    )  # fmt: skip
    df = vulns.merge(kev, on="cve_id", how="left").merge(_latest_epss(db), on="cve_id", how="left")
    df["cvss_score"] = pd.to_numeric(df["cvss_score"], errors="coerce")
    df["in_kev"] = df["date_added"].notna()
    return df


def _score_row(p: ScoringParams, r: Any, today: date) -> pd.Series:  # type: ignore[type-arg]
    in_kev = bool(r.in_kev)
    score = risk_score(
        p, in_kev=in_kev,
        epss=None if pd.isna(r.epss) else float(r.epss),
        percentile=None if pd.isna(r.percentile) else float(r.percentile),
        cvss=None if pd.isna(r.cvss_score) else float(r.cvss_score),
        criticality=int(r.criticality), ransomware=in_kev and r.ransomware_use == "Known",
    )  # fmt: skip
    band = band_of(p, score)
    detected = pd.Timestamp(r.first_seen).date()
    due = sla_due(
        p, band=band, detected=detected,
        kev_date_added=r.date_added if in_kev else None, kev_due_date=r.due_date if in_kev else None,
    )  # fmt: skip
    state = sla_state(p, due, today, active=r.status in ACTIVE)
    return pd.Series({"risk_score": score, "risk_band": band, "sla_due_date": due, "sla_state": state})


def correlate(db: Session, *, mark_matches: bool = True, today: date | None = None) -> CorrelationResult:
    """Recalcula score y SLA de todo el inventario. Con mark_matches, fija kev_matched_at SOLO la primera vez
    (base de la idempotencia: una segunda ejecución el mismo día no devuelve nuevas coincidencias)."""
    today = today or datetime.now(UTC).date()
    _, params = get_active_config(db)
    df = build_frame(db)
    result = CorrelationResult(total=len(df))
    if df.empty:
        return result
    scored = df.apply(lambda r: _score_row(params, r, today), axis=1)
    df = pd.concat([df, scored], axis=1)
    result.in_kev = int((df["in_kev"] & df["status"].isin(ACTIVE)).sum())
    result.epss_missing = int(df["epss"].isna().sum())

    now = datetime.now(UTC)
    fresh = df["in_kev"] & df["kev_matched_at"].isna() & df["status"].isin(ACTIVE)
    updates = [
        {"id": r.vuln_id, "risk_score": r.risk_score, "risk_band": r.risk_band, "sla_due_date": r.sla_due_date,
         **({"kev_matched_at": now} if mark_matches and f else {})}
        for r, f in zip(df.itertuples(index=False), fresh, strict=True)
    ]  # fmt: skip
    db.execute(update(Vulnerability), updates)
    if mark_matches:
        for r in df[fresh].sort_values("risk_score", ascending=False).itertuples(index=False):
            result.new_matches.append(
                {
                    "vulnerability_id": str(r.vuln_id), "asset_id": str(r.asset_id), "hostname": r.hostname,
                    "cve_id": r.cve_id, "criticality": int(r.criticality), "risk_score": float(r.risk_score),
                    "risk_band": r.risk_band, "sla_due_date": r.sla_due_date.isoformat(),
                    "kev_due_date": r.due_date.isoformat(), "ransomware": r.ransomware_use == "Known",
                    "epss": None if pd.isna(r.epss) else float(r.epss),
                    "vulnerability_name": r.vulnerability_name,
                }
            )  # fmt: skip
    _snapshot(db, df, today)
    return result


def _snapshot(db: Session, df: pd.DataFrame, today: date) -> None:
    active = df[df["status"].isin(ACTIVE)]
    kev_active = active[active["in_kev"]]
    by_band = active["risk_band"].value_counts().to_dict()
    snap = db.get(ExposureSnapshot, today) or ExposureSnapshot(snapshot_date=today)
    snap.kev_open = len(kev_active)
    snap.sla_overdue = int((active["sla_state"] == "vencido").sum())
    snap.critical_assets_exposed = int(kev_active[kev_active["criticality"] == 4]["asset_id"].nunique())
    snap.mean_risk = round(float(active["risk_score"].mean()), 2) if len(active) else None
    snap.by_band = {str(k): int(v) for k, v in by_band.items()}
    db.add(snap)
    db.flush()
