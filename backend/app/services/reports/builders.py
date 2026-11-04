"""Constructores de los 8 reportes. Toda cifra sale de la base de datos o de services/stats.py (nunca de la IA)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.intel import EpssScore, KevEntry
from app.models.inventory import Asset, Vulnerability
from app.models.ops import Ticket
from app.services import stats
from app.services.intel import get_active_config
from app.services.reports.model import (
    BAND,
    CRIT,
    PRIORITY,
    SLA,
    TICKET,
    Chart,
    Report,
    ReportError,
    Table,
    fmt_date,
    fmt_num,
)  # fmt: skip
from app.services.scoring import ScoringParams, sla_state

ACTIVE = ("open", "in_progress")
MAX_ROWS = 2000
MANAGEMENT = ("exposure_trend", "mttr", "sla_compliance", "period_comparison")

CATALOG: list[dict[str, Any]] = [
    {"key": "kev_by_asset", "kind": "operational", "title": "CVEs KEV por activo", "description": "Hallazgos abiertos con explotación activa confirmada, agrupados por activo y ordenados por riesgo.", "period": False},
    {"key": "open_tickets", "kind": "operational", "title": "Tickets abiertos", "description": "Tickets de remediación activos con responsable, prioridad y SLA.", "period": False},
    {"key": "sla_overdue", "kind": "operational", "title": "SLA vencidos", "description": "Hallazgos abiertos cuyo plazo de remediación ya venció, con los días de atraso.", "period": False},
    {"key": "cve_detail", "kind": "operational", "title": "Detalle por CVE", "description": "Ficha completa de un CVE: KEV, EPSS, equipos afectados y tickets.", "period": False, "needs_cve": True},
    {"key": "exposure_trend", "kind": "management", "title": "Tendencia de exposición", "description": "Evolución diaria de CVEs KEV abiertos y SLA vencidos en el periodo.", "period": True},
    {"key": "mttr", "kind": "management", "title": "Tiempo medio de remediación (MTTR)", "description": "Días promedio entre la detección y la mitigación, por banda de riesgo.", "period": True},
    {"key": "sla_compliance", "kind": "management", "title": "Cumplimiento de SLA", "description": "Porcentaje de hallazgos mitigados dentro de su plazo, por banda de riesgo.", "period": True},
    {"key": "period_comparison", "kind": "management", "title": "Comparativo por periodo", "description": "El periodo elegido frente al periodo anterior de la misma duración.", "period": True},
]


def _now() -> datetime:
    return datetime.now(UTC)


def _ctx(db: Session) -> tuple[ScoringParams, date]:
    _, params = get_active_config(db)
    return params, _now().date()


def _period(start: date, end: date) -> str:
    return f"Periodo: {fmt_date(start)} al {fmt_date(end)}"


# --------------------------------------------------------------------------- operacionales
def kev_by_asset(db: Session) -> Report:
    params, today = _ctx(db)
    q = db.execute(
        select(Vulnerability, Asset, KevEntry).join(Asset, Asset.id == Vulnerability.asset_id)
        .join(KevEntry, KevEntry.cve_id == Vulnerability.cve_id).where(Vulnerability.status.in_(ACTIVE))
        .order_by(Asset.criticality.desc(), Asset.hostname, Vulnerability.risk_score.desc().nulls_last()).limit(MAX_ROWS)
    ).unique().all()  # fmt: skip
    rows, overdue = [], 0
    for v, a, k in q:
        state = sla_state(params, v.sla_due_date, today, True)
        overdue += state == "vencido"
        rows.append([a.hostname, CRIT[a.criticality], a.environment, v.cve_id, fmt_num(float(v.risk_score) if v.risk_score is not None else None),
                     BAND.get(v.risk_band or "", "—"), fmt_date(v.sla_due_date), SLA[state], "Sí" if k.ransomware_use == "Known" else "No"])  # fmt: skip
    return Report(
        "kev_by_asset", "CVEs en KEV por activo", "Hallazgos abiertos con explotación activa confirmada por CISA", _now(),
        kpis=[("Hallazgos KEV abiertos", str(len(rows))), ("Activos afectados", str(len({r[0] for r in rows}))), ("Con SLA vencido", str(overdue))],
        tables=[Table("Detalle por activo", ["Activo", "Criticidad", "Entorno", "CVE", "Riesgo", "Banda", "SLA", "Estado SLA", "Ransomware"], rows, right={4})],
    )  # fmt: skip


def open_tickets(db: Session) -> Report:
    params, today = _ctx(db)
    ts = db.execute(select(Ticket).where(Ticket.status.in_(ACTIVE)).order_by(Ticket.due_date.asc().nulls_last(), Ticket.code).limit(MAX_ROWS)).scalars().unique().all()
    rows, overdue = [], 0
    for t in ts:
        state = sla_state(params, t.due_date, today, True)
        overdue += state == "vencido"
        rows.append([t.code, t.vulnerability.cve_id, t.vulnerability.asset.hostname, PRIORITY[t.priority], TICKET[t.status],
                     t.assignee.full_name if t.assignee else "Sin asignar", fmt_date(t.due_date), SLA[state]])  # fmt: skip
    return Report(
        "open_tickets", "Tickets de remediación abiertos", "Tickets activos con responsable y SLA", _now(),
        kpis=[("Tickets activos", str(len(rows))), ("Sin responsable", str(sum(r[5] == "Sin asignar" for r in rows))), ("Con SLA vencido", str(overdue))],
        tables=[Table("Detalle de tickets", ["Código", "CVE", "Activo", "Prioridad", "Estado", "Responsable", "SLA", "Estado SLA"], rows)],
    )  # fmt: skip


def sla_overdue(db: Session) -> Report:
    _, today = _ctx(db)
    q = db.execute(
        select(Vulnerability, Asset).join(Asset, Asset.id == Vulnerability.asset_id)
        .where(Vulnerability.status.in_(ACTIVE), Vulnerability.sla_due_date < today)
        .order_by(Vulnerability.sla_due_date.asc()).limit(MAX_ROWS)
    ).unique().all()  # fmt: skip
    kev = {k for (k,) in db.execute(select(KevEntry.cve_id)).all()}
    rows = [[v.cve_id, a.hostname, CRIT[a.criticality], "Sí" if v.cve_id in kev else "No", fmt_num(float(v.risk_score) if v.risk_score is not None else None),
             fmt_date(v.sla_due_date), (today - v.sla_due_date).days] for v, a in q]  # fmt: skip
    return Report(
        "sla_overdue", "Hallazgos con SLA vencido", f"Situación al {fmt_date(today)}", _now(),
        kpis=[("SLA vencidos", str(len(rows))), ("De ellos en KEV", str(sum(r[3] == "Sí" for r in rows))),
              ("Atraso máximo (días)", str(max((r[6] for r in rows), default=0)))],  # fmt: skip
        tables=[Table("Hallazgos vencidos", ["CVE", "Activo", "Criticidad", "En KEV", "Riesgo", "SLA venció", "Días de atraso"], rows, right={4, 6})],
    )


def cve_detail(db: Session, cve_id: str | None) -> Report:
    if not cve_id:
        raise ReportError("Indique el CVE (por ejemplo CVE-2021-44228)")
    cve = cve_id.strip().upper()
    params, today = _ctx(db)
    kev = db.get(KevEntry, cve)
    vulns = db.execute(select(Vulnerability, Asset).join(Asset, Asset.id == Vulnerability.asset_id).where(Vulnerability.cve_id == cve)
                       .order_by(Asset.criticality.desc(), Asset.hostname)).unique().all()  # fmt: skip
    if kev is None and not vulns:
        raise ReportError(f"{cve} no está en el catálogo KEV ni en el inventario")
    epss = db.execute(select(EpssScore).where(EpssScore.cve_id == cve).order_by(EpssScore.score_date.desc()).limit(30)).scalars().all()
    tickets = {t.vulnerability_id: t.code for t in db.execute(select(Ticket).where(Ticket.vulnerability_id.in_([v.id for v, _ in vulns]))).scalars().unique()} if vulns else {}
    tables: list[Table] = []
    if kev:
        tables.append(Table("Ficha KEV (CISA)", ["Campo", "Valor"], [
            ["Nombre", kev.vulnerability_name], ["Proveedor / producto", f"{kev.vendor_project} / {kev.product}"],
            ["Agregado a KEV", fmt_date(kev.date_added)], ["Fecha límite de CISA", fmt_date(kev.due_date)],
            ["Uso en ransomware", "Conocido" if kev.ransomware_use == "Known" else "Sin confirmar"],
            ["Descripción", kev.short_description], ["Acción requerida", kev.required_action]]))  # fmt: skip
    tables.append(Table("Activos afectados", ["Activo", "Criticidad", "Entorno", "Estado", "Riesgo", "Banda", "SLA", "Estado SLA", "Ticket"], [
        [a.hostname, CRIT[a.criticality], a.environment, v.status, fmt_num(float(v.risk_score) if v.risk_score is not None else None),
         BAND.get(v.risk_band or "", "—"), fmt_date(v.sla_due_date), SLA[sla_state(params, v.sla_due_date, today, v.status in ACTIVE)], tickets.get(v.id, "—")]
        for v, a in vulns], right={4}))  # fmt: skip
    if epss:
        tables.append(Table("Historial de EPSS (últimos 30 días)", ["Fecha", "EPSS", "Percentil"],
                            [[fmt_date(e.score_date), fmt_num(float(e.epss) * 100, 2, " %"), fmt_num(float(e.percentile) * 100, 1, " %")] for e in epss], right={1, 2}))  # fmt: skip
    latest = epss[0] if epss else None
    return Report(
        "cve_detail", f"Detalle de {cve}", "Ficha del CVE con su exposición en el entorno", _now(),
        kpis=[("En KEV", "Sí" if kev else "No"), ("Activos afectados", str(len(vulns))),
              ("EPSS actual", fmt_num(float(latest.epss) * 100, 1, " %") if latest else "—")],  # fmt: skip
        tables=tables,
    )


# --------------------------------------------------------------------------- de gestión
def _validate(start: date, end: date) -> None:
    if start > end:
        raise ReportError("La fecha inicial no puede ser posterior a la final")
    if (end - start).days > 366:
        raise ReportError("El periodo no puede superar 366 días")


def exposure_trend(db: Session, start: date, end: date) -> Report:
    _validate(start, end)
    pts = stats.trend(db, start, end)
    rows = [[fmt_date(date.fromisoformat(p["date"])), p["kev_open"], p["sla_overdue"], p["critical_assets_exposed"], fmt_num(p["mean_risk"])] for p in pts]
    kpis = [("Días con datos", str(len(pts)))]
    notes: list[str] = []
    if pts:
        first, last = pts[0], pts[-1]
        kpis += [("KEV abiertos al inicio", str(first["kev_open"])), ("KEV abiertos al cierre", str(last["kev_open"])),
                 ("Variación", f"{last['kev_open'] - first['kev_open']:+d}"), ("Pico de SLA vencidos", str(max(p["sla_overdue"] for p in pts)))]  # fmt: skip
        notes.append("El historial previo a la primera ejecución del flujo se reconstruye a partir de las fechas de detección, resolución y alta en KEV.")
    else:
        notes.append("No hay datos de exposición en el periodo.")
    chart = Chart("CVEs KEV abiertos y SLA vencidos", [r[0] for r in rows], [("KEV abiertos", [float(p["kev_open"]) for p in pts]), ("SLA vencidos", [float(p["sla_overdue"]) for p in pts])]) if pts else None  # fmt: skip
    return Report("exposure_trend", "Tendencia de exposición", _period(start, end), _now(), kpis=kpis, chart=chart, notes=notes,
                  tables=[Table("Evolución diaria", ["Fecha", "KEV abiertos", "SLA vencidos", "Activos críticos expuestos", "Riesgo medio"], rows, right={1, 2, 3, 4})])  # fmt: skip


def _resolved_rows(db: Session, start: date, end: date) -> list[tuple[Vulnerability, Asset]]:
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
    hi = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    found = db.execute(
        select(Vulnerability, Asset).join(Asset, Asset.id == Vulnerability.asset_id)
        .where(Vulnerability.status == "mitigated", Vulnerability.resolved_at >= lo, Vulnerability.resolved_at < hi)
        .order_by(Vulnerability.resolved_at.desc()).limit(MAX_ROWS)
    ).unique().all()  # fmt: skip
    return [(v, a) for v, a in found]


def _by_band(rows: list[tuple[Vulnerability, Asset]]) -> dict[str, list[tuple[Vulnerability, Asset]]]:
    out: dict[str, list[tuple[Vulnerability, Asset]]] = {b: [] for b in ("critical", "high", "medium", "low")}
    for v, a in rows:
        out.setdefault(v.risk_band or "low", []).append((v, a))
    return out


def _days(v: Vulnerability) -> float:
    return (v.resolved_at - v.first_seen).total_seconds() / 86400 if v.resolved_at else 0.0


def mttr(db: Session, start: date, end: date) -> Report:
    _validate(start, end)
    rows = _resolved_rows(db, start, end)
    m = stats.period_metrics(db, start, end)
    band_rows = []
    for b, items in _by_band(rows).items():
        band_rows.append([BAND[b], len(items), fmt_num(sum(_days(v) for v, _ in items) / len(items)) if items else "—"])
    detail = [[v.cve_id, a.hostname, BAND.get(v.risk_band or "", "—"), fmt_date(v.first_seen), fmt_date(v.resolved_at), fmt_num(_days(v))] for v, a in rows[:200]]
    return Report("mttr", "Tiempo medio de remediación (MTTR)", _period(start, end), _now(),
                  kpis=[("MTTR del periodo (días)", fmt_num(m["mttr_days"])), ("Hallazgos mitigados", str(m["resolved"]))],  # fmt: skip
                  notes=[] if rows else ["No hubo hallazgos mitigados en el periodo."],
                  tables=[Table("MTTR por banda de riesgo", ["Banda", "Mitigados", "MTTR (días)"], band_rows, right={1, 2}),
                          Table("Hallazgos mitigados", ["CVE", "Activo", "Banda", "Detectado", "Mitigado", "Días"], detail, right={5},
                                note="Se muestran como máximo 200 filas." if len(rows) > 200 else "")])  # fmt: skip


def sla_compliance(db: Session, start: date, end: date) -> Report:
    _validate(start, end)
    rows = _resolved_rows(db, start, end)
    m = stats.period_metrics(db, start, end)

    def on_time(v: Vulnerability) -> bool:
        return bool(v.resolved_at and v.sla_due_date and v.resolved_at.date() <= v.sla_due_date)

    band_rows = []
    for b, items in _by_band(rows).items():
        ok = sum(on_time(v) for v, _ in items)
        band_rows.append([BAND[b], len(items), ok, len(items) - ok, fmt_num(100 * ok / len(items), 1, " %") if items else "—"])
    late = [[v.cve_id, a.hostname, BAND.get(v.risk_band or "", "—"), fmt_date(v.sla_due_date), fmt_date(v.resolved_at),
             (v.resolved_at.date() - v.sla_due_date).days if v.sla_due_date and v.resolved_at else 0] for v, a in rows if not on_time(v)][:200]  # fmt: skip
    params, today = _ctx(db)
    still = db.execute(select(func.count()).select_from(Vulnerability).where(Vulnerability.status.in_(ACTIVE), Vulnerability.sla_due_date < today)).scalar_one()
    return Report("sla_compliance", "Cumplimiento de SLA", _period(start, end), _now(),
                  kpis=[("Cumplimiento del periodo", fmt_num(m["sla_compliance_pct"], 1, " %")), ("Mitigados en el periodo", str(m["resolved"])), ("SLA vencidos hoy", str(still))],  # fmt: skip
                  notes=[] if rows else ["No hubo hallazgos mitigados en el periodo."],
                  tables=[Table("Cumplimiento por banda", ["Banda", "Mitigados", "En plazo", "Fuera de plazo", "Cumplimiento"], band_rows, right={1, 2, 3, 4}),
                          Table("Mitigados fuera de plazo", ["CVE", "Activo", "Banda", "SLA", "Mitigado", "Días de atraso"], late, right={5})])  # fmt: skip


def period_comparison(db: Session, start: date, end: date) -> Report:
    _validate(start, end)
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur, prev = stats.period_metrics(db, start, end), stats.period_metrics(db, prev_start, prev_end)

    def row(label: str, key: str, digits: int = 0, suffix: str = "") -> list[Any]:
        a, b = cur[key], prev[key]
        delta = "—" if a is None or b is None else (f"{a - b:+.{digits}f}".replace(".", ","))
        return [label, fmt_num(b, digits, suffix), fmt_num(a, digits, suffix), delta]

    rows = [row("Nuevas entradas KEV en el entorno", "new_kev"), row("Hallazgos mitigados", "resolved"),
            row("MTTR (días)", "mttr_days", 1), row("Cumplimiento de SLA", "sla_compliance_pct", 1, " %"),
            row("KEV abiertos al cierre", "kev_open_end"), row("SLA vencidos al cierre", "sla_overdue_end")]  # fmt: skip
    return Report("period_comparison", "Comparativo por periodo", f"{_period(start, end)} frente a {fmt_date(prev_start)} al {fmt_date(prev_end)}", _now(),
                  kpis=[("Nuevas KEV", str(cur["new_kev"])), ("Mitigados", str(cur["resolved"])), ("Días del periodo", str(days))],  # fmt: skip
                  tables=[Table("Indicadores", ["Indicador", f"Anterior ({fmt_date(prev_start)} a {fmt_date(prev_end)})", f"Actual ({fmt_date(start)} a {fmt_date(end)})", "Variación"], rows, right={1, 2, 3})])  # fmt: skip


def build(db: Session, key: str, start: date, end: date, cve_id: str | None) -> Report:
    if key == "kev_by_asset":
        return kev_by_asset(db)
    if key == "open_tickets":
        return open_tickets(db)
    if key == "sla_overdue":
        return sla_overdue(db)
    if key == "cve_detail":
        return cve_detail(db, cve_id)
    if key == "exposure_trend":
        return exposure_trend(db, start, end)
    if key == "mttr":
        return mttr(db, start, end)
    if key == "sla_compliance":
        return sla_compliance(db, start, end)
    if key == "period_comparison":
        return period_comparison(db, start, end)
    raise ReportError("Tipo de reporte desconocido")

