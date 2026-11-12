"""Score de riesgo y SLA. Fórmula explícita y configurable (ver la pantalla Configuración).

    base = w_epss·EPSS + w_percentile·percentil + w_cvss·(CVSS/10) + w_asset·(criticidad/4)      (Σw = 1)
    en KEV:      score = kev_floor + (100 − kev_floor)·base (+ bonus si ransomware), tope 100
    fuera de KEV: score = (kev_floor − 1)·base

Así KEV domina por construcción: cualquier CVE en KEV puntúa ≥ kev_floor y cualquiera fuera de KEV < kev_floor.
"""

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, model_validator

BAND_NAMES = ("critical", "high", "medium", "low")


class ScoringParams(BaseModel):
    w_epss: float = Field(0.35, ge=0, le=1)
    w_percentile: float = Field(0.15, ge=0, le=1)
    w_cvss: float = Field(0.25, ge=0, le=1)
    w_asset: float = Field(0.25, ge=0, le=1)
    kev_floor: float = Field(70, ge=1, le=99)
    ransomware_bonus: float = Field(5, ge=0, le=30)
    band_critical: float = Field(85, ge=1, le=100)
    band_high: float = Field(70, ge=1, le=100)
    band_medium: float = Field(40, ge=1, le=100)
    sla_critical: int = Field(15, ge=1, le=730)
    sla_high: int = Field(30, ge=1, le=730)
    sla_medium: int = Field(90, ge=1, le=730)
    sla_low: int = Field(180, ge=1, le=730)
    due_soon_days: int = Field(7, ge=0, le=60)

    @model_validator(mode="after")
    def _check(self) -> "ScoringParams":
        total = self.w_epss + self.w_percentile + self.w_cvss + self.w_asset
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Los pesos deben sumar 1 (suman {total:.3f})")
        if not (self.band_critical > self.band_high > self.band_medium):
            raise ValueError("Los umbrales de banda deben cumplir crítico > alto > medio")
        return self

    # --- (de)serialización hacia las columnas JSONB de scoring_configs ---
    def to_columns(self) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
        weights = {
            "w_epss": self.w_epss, "w_percentile": self.w_percentile, "w_cvss": self.w_cvss,
            "w_asset": self.w_asset, "kev_floor": self.kev_floor, "ransomware_bonus": self.ransomware_bonus,
        }  # fmt: skip
        bands = {"critical": self.band_critical, "high": self.band_high, "medium": self.band_medium}
        sla = {
            "critical": self.sla_critical, "high": self.sla_high, "medium": self.sla_medium,
            "low": self.sla_low, "due_soon_days": self.due_soon_days,
        }  # fmt: skip
        return weights, bands, sla

    @classmethod
    def from_columns(cls, weights: dict[str, Any], bands: dict[str, Any], sla: dict[str, Any]) -> "ScoringParams":
        return cls(
            **weights,
            band_critical=bands["critical"], band_high=bands["high"], band_medium=bands["medium"],
            sla_critical=sla["critical"], sla_high=sla["high"], sla_medium=sla["medium"],
            sla_low=sla["low"], due_soon_days=sla["due_soon_days"],
        )  # fmt: skip


def base_score(p: ScoringParams, epss: float, percentile: float, cvss: float, criticality: int) -> float:
    return (
        p.w_epss * epss
        + p.w_percentile * percentile
        + p.w_cvss * (cvss / 10)
        + p.w_asset * (criticality / 4)
    )


def risk_score(
    p: ScoringParams,
    *,
    in_kev: bool,
    epss: float | None,
    percentile: float | None,
    cvss: float | None,
    criticality: int,
    ransomware: bool = False,
) -> float:
    """Los datos ausentes (EPSS o CVSS desconocidos) aportan 0; nunca se inventan."""
    base = base_score(p, epss or 0.0, percentile or 0.0, cvss or 0.0, criticality)
    if in_kev:
        score = p.kev_floor + (100 - p.kev_floor) * base + (p.ransomware_bonus if ransomware else 0)
        return round(min(100.0, score), 2)
    return round((p.kev_floor - 1) * base, 2)


def explain_score(
    p: ScoringParams,
    *,
    in_kev: bool,
    epss: float | None,
    percentile: float | None,
    cvss: float | None,
    criticality: int,
    ransomware: bool = False,
) -> dict[str, Any]:
    """Desglose del score: cuántos puntos aporta cada factor. Usa la misma fórmula que `risk_score` (hay test de
    coincidencia), así que la explicación nunca puede divergir del número mostrado."""
    inputs = [
        ("epss", "Probabilidad de explotación (EPSS)", p.w_epss, epss or 0.0, epss, f"{(epss or 0) * 100:.1f} %"),
        ("percentile", "Percentil EPSS", p.w_percentile, percentile or 0.0, percentile, f"{(percentile or 0) * 100:.1f} %"),
        ("cvss", "Gravedad técnica (CVSS)", p.w_cvss, (cvss or 0.0) / 10, cvss, f"{cvss:.1f} / 10" if cvss is not None else "sin dato"),
        ("asset", "Criticidad del activo", p.w_asset, criticality / 4, criticality, f"{criticality} / 4"),
    ]  # fmt: skip
    base = base_score(p, epss or 0.0, percentile or 0.0, cvss or 0.0, criticality)
    scale = (100 - p.kev_floor) if in_kev else (p.kev_floor - 1)
    factors: list[dict[str, Any]] = []
    for key, label, weight, norm, raw, shown in inputs:
        pts = round(weight * norm * scale, 2)
        factors.append({"key": key, "label": label, "weight": weight, "value": shown, "known": raw is not None,
                        "points": pts})  # fmt: skip
    kev_points = p.kev_floor if in_kev else 0.0
    bonus = p.ransomware_bonus if (in_kev and ransomware) else 0.0
    total = risk_score(p, in_kev=in_kev, epss=epss, percentile=percentile, cvss=cvss, criticality=criticality,
                       ransomware=ransomware)  # fmt: skip
    top = max(factors, key=lambda f: f["points"])
    if in_kev:
        text = (f"Está en el catálogo KEV de CISA (explotación confirmada), lo que fija un piso de {p.kev_floor:g} puntos. "
                f"Los otros factores suman {sum(f['points'] for f in factors):.1f}; el que más pesa es «{top['label']}».")  # fmt: skip
        if bonus:
            text += f" Se añaden {bonus:g} puntos por uso conocido en ransomware."
        if total >= 100 and kev_points + sum(f["points"] for f in factors) + bonus > 100:
            text += " El resultado se limita a 100."
    else:
        text = (f"No está en KEV, por eso su score no puede superar {p.kev_floor - 1:g}. "
                f"El factor que más pesa es «{top['label']}» ({top['points']:.1f} puntos).")  # fmt: skip
    missing = [f["label"] for f in factors if not f["known"]]
    if missing:
        text += f" Sin dato (cuenta 0, no se inventa): {', '.join(missing)}."
    return {"score": total, "band": band_of(p, total), "in_kev": in_kev, "kev_points": kev_points,
            "ransomware_bonus": bonus, "factors": factors, "base": round(base, 4), "summary": text}  # fmt: skip


def band_of(p: ScoringParams, score: float) -> str:
    if score >= p.band_critical:
        return "critical"
    if score >= p.band_high:
        return "high"
    if score >= p.band_medium:
        return "medium"
    return "low"


def sla_due(
    p: ScoringParams,
    *,
    band: str,
    detected: date,
    kev_date_added: date | None = None,
    kev_due_date: date | None = None,
) -> date:
    """Fecha límite de remediación.

    KEV: si se detectó antes del dueDate de CISA, vence ese dueDate; si se detectó después, se da la misma
    ventana que dio CISA (dueDate − dateAdded) contada desde la detección, para que no nazca vencido.
    Fuera de KEV: días por banda desde la detección.
    """
    if kev_due_date is not None and kev_date_added is not None:
        if detected <= kev_due_date:
            return kev_due_date
        window = max(1, (kev_due_date - kev_date_added).days)
        return detected + timedelta(days=window)
    days = {"critical": p.sla_critical, "high": p.sla_high, "medium": p.sla_medium, "low": p.sla_low}[band]
    return detected + timedelta(days=days)


def sla_state(p: ScoringParams, due: date | None, today: date, active: bool = True) -> str:
    if due is None or not active:
        return "no_aplica"
    if due < today:
        return "vencido"
    if (due - today).days <= p.due_soon_days:
        return "por_vencer"
    return "en_plazo"
