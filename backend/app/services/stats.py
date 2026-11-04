"""Agregados de exposición. Fuente única de cifras para el dashboard, los reportes y el resumen ejecutivo
(la IA solo redacta sobre estos números; nunca los calcula)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, case, cast, func, select, text
from sqlalchemy.orm import Session

from app.models.intel import ExposureSnapshot, KevEntry, WorkflowRun
from app.models.inventory import Asset, Vulnerability
from app.services.intel import get_active_config

ACTIVE = ("open", "in_progress")
PERIOD_DAYS = 90


def _kev_active() -> list[Any]:
    return [Vulnerability.status.in_(ACTIVE), Vulnerability.cve_id.in_(select(KevEntry.cve_id))]


def aggregates(db: Session, today: date | None = None, top_n: int = 5) -> dict[str, Any]:
    now = datetime.now(UTC)
    today = today or now.date()
    _, params = get_active_config(db)
    soon = today + timedelta(days=params.due_soon_days)
    kev_active = _kev_active()

    def count(*where: Any) -> int:
        return int(db.execute(select(func.count()).select_from(Vulnerability).where(*where)).scalar_one())

    out: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "open_kev": count(*kev_active),
        "new_kev_24h": count(Vulnerability.kev_matched_at >= now - timedelta(days=1)),
        "new_kev_7d": count(Vulnerability.kev_matched_at >= now - timedelta(days=7)),
        "sla_overdue": count(Vulnerability.status.in_(ACTIVE), Vulnerability.sla_due_date < today),
        "sla_due_soon": count(Vulnerability.status.in_(ACTIVE), Vulnerability.sla_due_date >= today,
                              Vulnerability.sla_due_date <= soon),  # fmt: skip
        "sla_overdue_kev": count(*kev_active, Vulnerability.sla_due_date < today),
        "active_total": count(Vulnerability.status.in_(ACTIVE)),
    }
    out["by_band"] = {
        (b or "sin_score"): n
        for b, n in db.execute(
            select(Vulnerability.risk_band, func.count()).where(Vulnerability.status.in_(ACTIVE)).group_by(Vulnerability.risk_band)
        ).all()
    }
    out["kev_by_asset_criticality"] = {
        int(c): n
        for c, n in db.execute(
            select(Asset.criticality, func.count()).join(Vulnerability, Vulnerability.asset_id == Asset.id)
            .where(*kev_active).group_by(Asset.criticality)
        ).all()
    }  # fmt: skip
    epss_rows = db.execute(
        text(
            "SELECT CASE WHEN e.epss IS NULL THEN 'sin_dato' WHEN e.epss < 0.1 THEN 'menor_10' WHEN e.epss < 0.5 THEN '10_a_50' "
            "WHEN e.epss < 0.9 THEN '50_a_90' ELSE 'mayor_90' END AS bucket, count(*) "
            "FROM vulnerabilities v LEFT JOIN (SELECT DISTINCT ON (cve_id) cve_id, epss FROM epss_scores "
            "ORDER BY cve_id, score_date DESC) e ON e.cve_id = v.cve_id "
            "WHERE v.status IN ('open','in_progress') AND v.cve_id IN (SELECT cve_id FROM kev_entries) GROUP BY 1"
        )
    ).all()
    out["kev_epss_distribution"] = {b: int(n) for b, n in epss_rows}

    top_assets = db.execute(
        select(Asset.hostname, Asset.criticality, Asset.environment, func.count().label("kev"), func.max(Vulnerability.risk_score))
        .join(Vulnerability, Vulnerability.asset_id == Asset.id).where(*kev_active)
        .group_by(Asset.id).order_by(func.count().desc(), func.max(Vulnerability.risk_score).desc().nulls_last()).limit(top_n)
    ).all()  # fmt: skip
    out["top_assets"] = [
        {"hostname": h, "criticality": int(c), "environment": e, "kev_count": int(n), "max_risk": float(r) if r is not None else None}
        for h, c, e, n, r in top_assets
    ]
    top_risks = db.execute(
        select(Vulnerability.cve_id, Asset.hostname, Vulnerability.risk_score, Vulnerability.risk_band, Vulnerability.sla_due_date)
        .join(Asset, Asset.id == Vulnerability.asset_id).where(Vulnerability.status.in_(ACTIVE))
        .order_by(Vulnerability.risk_score.desc().nulls_last(), Vulnerability.sla_due_date.asc().nulls_last()).limit(top_n)
    ).all()  # fmt: skip
    out["top_risks"] = [
        {"cve_id": c, "hostname": h, "risk_score": float(s) if s is not None else None, "band": b,
         "sla_due_date": d.isoformat() if d else None}
        for c, h, s, b, d in top_risks
    ]  # fmt: skip

    since = now - timedelta(days=PERIOD_DAYS)
    resolved = db.execute(
        select(
            func.count(),
            func.avg(func.extract("epoch", Vulnerability.resolved_at - Vulnerability.first_seen) / 86400.0),
            func.sum(case((cast(Vulnerability.resolved_at, Date) <= Vulnerability.sla_due_date, 1), else_=0)),
        ).where(Vulnerability.status == "mitigated", Vulnerability.resolved_at >= since)
    ).one()
    n_res, mttr, on_time = resolved
    out["resolved_90d"] = int(n_res or 0)
    out["mttr_days"] = round(float(mttr), 1) if mttr is not None else None
    out["sla_compliance_pct"] = round(100.0 * int(on_time or 0) / n_res, 1) if n_res else None

    snaps = db.execute(select(ExposureSnapshot).order_by(ExposureSnapshot.snapshot_date.desc()).limit(30)).scalars().all()
    out["trend"] = [
        {"date": s.snapshot_date.isoformat(), "kev_open": s.kev_open, "sla_overdue": s.sla_overdue,
         "mean_risk": float(s.mean_risk) if s.mean_risk is not None else None}
        for s in reversed(snaps)
    ]  # fmt: skip
    run = db.execute(select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(1)).scalars().first()
    out["last_run"] = (
        {"status": run.status, "started_at": run.started_at.isoformat(), "new_matches": run.new_matches,
         "errors": len(run.errors)}
        if run else None
    )  # fmt: skip
    return out


def trend(db: Session, start: date, end: date) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ExposureSnapshot).where(ExposureSnapshot.snapshot_date >= start, ExposureSnapshot.snapshot_date <= end)
        .order_by(ExposureSnapshot.snapshot_date)
    ).scalars().all()  # fmt: skip
    return [
        {"date": r.snapshot_date.isoformat(), "kev_open": r.kev_open, "sla_overdue": r.sla_overdue,
         "critical_assets_exposed": r.critical_assets_exposed, "mean_risk": float(r.mean_risk) if r.mean_risk is not None else None}
        for r in rows
    ]  # fmt: skip


def period_metrics(db: Session, start: date, end: date) -> dict[str, Any]:
    """Métricas de un periodo [start, end] (ambos incluidos), para los reportes de gestión y el comparativo."""
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
    hi = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    new_kev = db.execute(
        select(func.count()).select_from(Vulnerability).where(Vulnerability.kev_matched_at >= lo, Vulnerability.kev_matched_at < hi)
    ).scalar_one()
    resolved = db.execute(
        select(
            func.count(),
            func.avg(func.extract("epoch", Vulnerability.resolved_at - Vulnerability.first_seen) / 86400.0),
            func.sum(case((cast(Vulnerability.resolved_at, Date) <= Vulnerability.sla_due_date, 1), else_=0)),
        ).where(Vulnerability.status == "mitigated", Vulnerability.resolved_at >= lo, Vulnerability.resolved_at < hi)
    ).one()
    n_res, mttr, on_time = resolved
    last = db.execute(
        select(ExposureSnapshot).where(ExposureSnapshot.snapshot_date <= end).order_by(ExposureSnapshot.snapshot_date.desc()).limit(1)
    ).scalars().first()  # fmt: skip
    return {
        "start": start.isoformat(), "end": end.isoformat(), "new_kev": int(new_kev), "resolved": int(n_res or 0),
        "mttr_days": round(float(mttr), 1) if mttr is not None else None,
        "sla_compliance_pct": round(100.0 * int(on_time or 0) / n_res, 1) if n_res else None,
        "kev_open_end": last.kev_open if last else None, "sla_overdue_end": last.sla_overdue if last else None,
        "mean_risk_end": float(last.mean_risk) if last and last.mean_risk is not None else None,
    }  # fmt: skip


def ensure_history(db: Session, today: date, days: int = 60, min_points: int = 14) -> int:
    """Reconstruye el historial de exposición de los últimos días A PARTIR DE LOS DATOS (first_seen, resolved_at y la
    fecha de alta en KEV) cuando aún hay pocos puntos. No inventa nada: es lo que el inventario habría mostrado cada día.
    Nunca toca la foto de hoy ni sobrescribe fotos existentes."""
    existing = db.execute(select(func.count()).select_from(ExposureSnapshot)).scalar_one()
    if existing >= min_points:
        return 0
    first = db.execute(select(func.min(Vulnerability.first_seen))).scalar()
    if first is None:
        return 0  # sin inventario no hay historia que reconstruir
    start = max(today - timedelta(days=days), first.date())  # nunca antes de que existiera el primer hallazgo
    if start >= today:
        return 0
    rows = db.execute(
        text(
            "SELECT d::date AS day, "
            " count(*) FILTER (WHERE k.cve_id IS NOT NULL) AS kev_open, "
            " count(*) FILTER (WHERE v.sla_due_date < d::date) AS overdue, "
            " count(DISTINCT a.id) FILTER (WHERE k.cve_id IS NOT NULL AND a.criticality = 4) AS crit_assets "
            "FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d "
            "LEFT JOIN vulnerabilities v ON v.first_seen::date <= d::date AND (v.resolved_at IS NULL OR v.resolved_at::date > d::date) "
            "LEFT JOIN assets a ON a.id = v.asset_id "
            "LEFT JOIN kev_entries k ON k.cve_id = v.cve_id AND k.date_added <= d::date "
            "GROUP BY d ORDER BY d"
        ),
        {"start": start, "end": today - timedelta(days=1)},
    ).all()
    added = 0
    for day, kev_open, overdue, crit in rows:
        if db.get(ExposureSnapshot, day) is None:
            db.add(ExposureSnapshot(snapshot_date=day, kev_open=int(kev_open), sla_overdue=int(overdue),
                                    critical_assets_exposed=int(crit), mean_risk=None, by_band={}))  # fmt: skip
            added += 1
    db.flush()
    return added
