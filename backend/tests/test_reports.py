import io
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai import providers
from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.intel import ExposureSnapshot, KevEntry
from app.models.inventory import Asset, Vulnerability
from app.services import stats
from app.services.reports.render_xlsx import _num, safe
from tests.ai_fakes import fake
from tests.conftest import login
from tests.test_ai import SUMMARY
from tests.test_alerting import dispatch, matches_from_correlation
from tests.test_intel_api import env  # noqa: F401

Env = tuple[TestClient, sessionmaker[Session]]
TYPES = ["kev_by_asset", "open_tickets", "sla_overdue", "cve_detail", "exposure_trend", "mttr", "sla_compliance", "period_comparison"]
CVE = "CVE-2021-44228"


@pytest.fixture(autouse=True)
def _provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "llm_provider", "ollama")
    yield
    providers.set_factory(None)


def seeded(c: TestClient, m: sessionmaker[Session]) -> None:
    """Inventario con un KEV abierto (con ticket) y dos hallazgos mitigados: uno en plazo y otro fuera de plazo."""
    rid, matches = matches_from_correlation(c, m)
    dispatch(c, rid, matches)
    now = datetime.now(UTC)
    with m() as db:
        late = db.execute(select(Vulnerability).where(Vulnerability.cve_id == "CVE-2022-0778")).scalar_one()
        late.status, late.first_seen, late.resolved_at = "mitigated", now - timedelta(days=10), now - timedelta(days=1)
        late.sla_due_date, late.risk_band = (now - timedelta(days=3)).date(), "low"
        asset_b = db.execute(select(Asset).limit(1)).scalar_one()
        db.add(Vulnerability(asset_id=asset_b.id, cve_id="CVE-2023-0286", cvss_score=7.4, status="mitigated", first_seen=now - timedelta(days=6),
                             resolved_at=now - timedelta(days=2), sla_due_date=(now + timedelta(days=5)).date(), risk_band="medium"))  # fmt: skip
        db.commit()
    from tests.test_intel_api import KEY

    rid2 = c.post("/api/v1/internal/runs/start", headers=KEY, json={"force": True}).json()["run_id"]
    c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": rid2})  # recalcula y reconstruye el historial


def get(c: TestClient, who: str, rtype: str, fmt: str, **params: Any) -> Any:
    if rtype == "cve_detail":
        params.setdefault("cve_id", CVE)
    return c.post(f"/api/v1/reports/{rtype}", headers=login(c, who), params={"fmt": fmt, **params})


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def docx_text(data: bytes) -> str:
    d = Document(io.BytesIO(data))
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


# --------------------------------------------------------------------------- dashboard
def test_dashboard_endpoints_and_rbac(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    for who in ("admin@radar.local", "analista@radar.local", "auditor@radar.local", "gerencia@radar.local"):
        k = c.get("/api/v1/dashboard/kpis", headers=login(c, who))
        assert k.status_code == 200, who
    k = c.get("/api/v1/dashboard/kpis", headers=login(c, "gerencia@radar.local")).json()
    assert k["open_kev"] == 1 and k["new_kev_24h"] == 1 and k["resolved_90d"] == 2
    assert k["mttr_days"] == pytest.approx(6.5, abs=0.2) and k["sla_compliance_pct"] == 50.0  # (9 d + 4 d) / 2; 1 de 2 en plazo
    assert k["top_assets"][0]["hostname"] == "srv-a" and k["last_run"] is not None and "trend" not in k
    tr = c.get("/api/v1/dashboard/trend", headers=login(c, "gerencia@radar.local"), params={"days": 30}).json()
    assert len(tr) >= 2 and tr[-1]["date"] == datetime.now(UTC).date().isoformat() and tr[-1]["kev_open"] == 1
    assert c.get("/api/v1/dashboard/trend", headers=login(c, "gerencia@radar.local"), params={"days": 1}).status_code == 422
    assert len(c.get("/api/v1/dashboard/top-assets", headers=login(c, "gerencia@radar.local"), params={"limit": 3}).json()) == 1
    assert c.get("/api/v1/dashboard/kpis").status_code == 401


def test_history_is_reconstructed_from_data_not_invented(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    today = datetime.now(UTC).date()
    with m() as db:
        snaps = {s.snapshot_date: s for s in db.execute(select(ExposureSnapshot)).scalars()}
        assert today in snaps and snaps[today].mean_risk is not None  # la foto real de hoy no se toca
        past = snaps[today - timedelta(days=1)]
        assert past.kev_open == 0 and past.mean_risk is None and past.by_band == {}  # lo reconstruido no trae datos imposibles de saber
        assert min(snaps) >= today - timedelta(days=10)  # no se inventa historia anterior al primer hallazgo
        # 44228 se vio hace 5 días (fixture de correlación: first_seen 2026-10-30) o antes; nunca antes de existir
        first = db.execute(select(Vulnerability.first_seen).where(Vulnerability.cve_id == CVE)).scalar_one().date()
        before = [s for d, s in snaps.items() if d < first]
        assert all(s.kev_open == 0 for s in before)
        assert stats.ensure_history(db, today) == 0  # idempotente: ya hay suficientes puntos


# --------------------------------------------------------------------------- reportes: todos los tipos y formatos
@pytest.mark.parametrize("rtype", TYPES)
def test_every_report_generates_valid_pdf_docx_xlsx_and_is_audited(env: Env, rtype: str) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    for fmt in ("pdf", "docx", "xlsx"):
        r = get(c, "analista@radar.local", rtype, fmt)
        assert r.status_code == 200, (rtype, fmt, r.text[:200])
        assert f'filename="radar_{rtype}_' in r.headers["content-disposition"] and r.headers["content-disposition"].endswith(f'.{fmt}"')
        if fmt == "pdf":
            assert r.content[:5] == b"%PDF-" and len(PdfReader(io.BytesIO(r.content)).pages) >= 1
            assert "Radar de explotación activa" in pdf_text(r.content)
        elif fmt == "docx":
            assert "Generado el" in docx_text(r.content)
        else:
            wb = load_workbook(io.BytesIO(r.content))
            assert wb.sheetnames[0] == "Resumen" and wb["Resumen"]["A1"].value
            tabular = [ws for ws in wb.worksheets[1:] if ws.title != "Gráfico" and ws.max_row >= 4 and ws["A3"].value]
            for ws in tabular:
                assert ws.freeze_panes == "A4" and ws["A3"].font.bold  # encabezado con formato y panel fijo
                assert ws.auto_filter.ref or ws.max_row == 3  # filtros sobre los datos
    with m() as db:
        ev = db.execute(select(AuditLog).where(AuditLog.module == "reports", AuditLog.action == "export")).scalars().all()
        assert len(ev) == 3 and {e.detail["fmt"] for e in ev} == {"pdf", "docx", "xlsx"} and all(e.detail["type"] == rtype for e in ev)


def test_report_content_matches_the_data(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    x = load_workbook(io.BytesIO(get(c, "analista@radar.local", "kev_by_asset", "xlsx").content))
    ws = x["Detalle por activo"]
    assert [ws.cell(3, i).value for i in (1, 4, 6)] == ["Activo", "CVE", "Banda"]
    assert ws.cell(4, 1).value == "srv-a" and ws.cell(4, 4).value == CVE and ws.cell(4, 6).value == "Crítico"
    assert isinstance(ws.cell(4, 5).value, int | float)  # el riesgo es numérico (ordenable en Excel)
    mt = load_workbook(io.BytesIO(get(c, "analista@radar.local", "mttr", "xlsx").content))
    kpis = {mt["Resumen"].cell(r, 1).value: mt["Resumen"].cell(r, 2).value for r in range(5, 7)}
    assert kpis["Hallazgos mitigados"] == 2 and 6.3 <= kpis["MTTR del periodo (días)"] <= 6.7
    sla = load_workbook(io.BytesIO(get(c, "analista@radar.local", "sla_compliance", "xlsx").content))
    assert sla["Resumen"]["B5"].value == "50,0 %" or sla["Resumen"]["B5"].value == 50.0
    over = load_workbook(io.BytesIO(get(c, "analista@radar.local", "sla_overdue", "xlsx").content))
    assert over["Resumen"]["B5"].value in (0, "0")  # no hay hallazgos activos vencidos en este escenario
    trend = load_workbook(io.BytesIO(get(c, "analista@radar.local", "exposure_trend", "xlsx").content))
    assert "Gráfico" in trend.sheetnames and trend["Gráfico"]._charts  # gráfico nativo de Excel
    pc = pdf_text(get(c, "analista@radar.local", "period_comparison", "pdf").content)
    assert "Nuevas entradas KEV en el entorno" in pc and "Variación" in pc


def test_trend_pdf_embeds_a_chart(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    r = get(c, "analista@radar.local", "exposure_trend", "pdf")
    assert "CVEs KEV abiertos y SLA vencidos" in pdf_text(r.content)


# --------------------------------------------------------------------------- seguridad y validación
def test_roles_that_can_export_and_those_that_cannot(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    for who in ("admin@radar.local", "analista@radar.local", "auditor@radar.local", "gerencia@radar.local"):
        assert get(c, who, "open_tickets", "pdf").status_code == 200, who
        assert c.get("/api/v1/reports/catalog", headers=login(c, who)).status_code == 200
    assert c.post("/api/v1/reports/mttr").status_code == 401
    assert len(c.get("/api/v1/reports/catalog", headers=login(c, "gerencia@radar.local")).json()) == 8


@pytest.mark.parametrize(
    ("rtype", "params", "msg"),
    [
        ("cve_detail", {}, "Indique el CVE"),
        ("cve_detail", {"cve_id": "CVE-2099-0001"}, "no está en el catálogo"),
        ("mttr", {"date_from": "2026-11-10", "date_to": "2026-11-01"}, "posterior"),
        ("mttr", {"date_from": "2024-01-01", "date_to": "2026-11-01"}, "366"),
    ],
)
def test_validation_errors_are_422_with_clear_messages(env: Env, rtype: str, params: dict[str, str], msg: str) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    r = c.post(f"/api/v1/reports/{rtype}", headers=login(c, "analista@radar.local"), params=params)
    assert r.status_code == 422 and msg in str(r.json()), r.text


def test_invalid_type_format_and_cve_pattern_are_rejected(env: Env) -> None:  # noqa: F811
    c, _ = env
    h = login(c, "analista@radar.local")
    assert c.post("/api/v1/reports/inventado", headers=h).status_code == 422
    assert c.post("/api/v1/reports/mttr", headers=h, params={"fmt": "exe"}).status_code == 422
    assert c.post("/api/v1/reports/cve_detail", headers=h, params={"cve_id": "x'; DROP TABLE users;--"}).status_code == 422


def test_external_text_is_neither_interpreted_as_html_nor_as_excel_formula(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    with m() as db:
        k = db.get(KevEntry, CVE)
        assert k is not None
        k.vulnerability_name = '=HYPERLINK("http://evil.test","clic")'
        k.short_description = "<script>alert(1)</script> <b>negrita</b>"
        db.commit()
    xl = load_workbook(io.BytesIO(get(c, "analista@radar.local", "cve_detail", "xlsx").content))
    ficha = xl["Ficha KEV (CISA)"]
    values = [ficha.cell(r, 2).value for r in range(4, 12)]
    assert any(isinstance(v, str) and v.startswith("'=HYPERLINK") for v in values)  # la fórmula quedó como texto
    assert all(not (isinstance(cell.value, str) and cell.value.startswith("=")) for row in ficha.iter_rows() for cell in row)
    text = pdf_text(get(c, "analista@radar.local", "cve_detail", "pdf").content)
    assert "<script>alert(1)</script>" in text and "<b>negrita</b>" in text  # visible como texto, no ejecutado ni formateado
    assert safe("=1+1") == "'=1+1" and safe("+x") == "'+x" and safe("normal") == "normal" and safe(5) == 5
    assert _num("12,5") == 12.5 and _num("1 234,5") == 1234.5 and _num("97,3 %") == "97,3 %" and _num("CVE-2021-1") == "CVE-2021-1"


# --------------------------------------------------------------------------- resumen ejecutivo con IA
def test_management_report_includes_ai_summary_marked_in_every_format(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    providers.set_factory(lambda: fake(structured=[SUMMARY]))
    pdf = get(c, "gerencia@radar.local", "period_comparison", "pdf", ai_summary="true")
    t = pdf_text(pdf.content)
    assert "GENERADO POR IA" in t and "Resumen ejecutivo" in t and "CVE-2021-44228" in t
    assert "Generado por IA" in docx_text(get(c, "gerencia@radar.local", "period_comparison", "docx", ai_summary="true").content)
    xl = load_workbook(io.BytesIO(get(c, "gerencia@radar.local", "period_comparison", "xlsx", ai_summary="true").content))
    assert any("Generado por IA" in str(cell.value) for row in xl["Resumen"].iter_rows() for cell in row if cell.value)
    with m() as db:
        assert db.execute(select(AuditLog).where(AuditLog.module == "ai", AuditLog.action == "exec_summary")).scalars().all()
        ev = db.execute(select(AuditLog).where(AuditLog.module == "reports")).scalars().first()
        assert ev is not None and ev.detail["ai_summary"] is True


def test_report_is_generated_even_when_ai_is_unavailable(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    monkeypatch.setattr(get_settings(), "llm_provider", "none")
    r = get(c, "gerencia@radar.local", "mttr", "pdf", ai_summary="true")
    assert r.status_code == 200
    t = pdf_text(r.content)
    assert "no disponible" in t and "GENERADO POR IA" not in t  # el reporte sale completo, con el aviso


def test_ai_summary_is_skipped_for_operational_reports_and_for_roles_without_ai(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    providers.set_factory(lambda: fake(structured=[SUMMARY]))
    assert "GENERADO POR IA" not in pdf_text(get(c, "analista@radar.local", "open_tickets", "pdf", ai_summary="true").content)
    r = get(c, "auditor@radar.local", "mttr", "pdf", ai_summary="true")  # el Auditor no tiene permiso de IA
    assert r.status_code == 200 and "GENERADO POR IA" not in pdf_text(r.content) and "su rol no puede usar la IA" in pdf_text(r.content)


def test_report_period_defaults_and_comparison_uses_previous_window(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    today = datetime.now(UTC).date()
    with m() as db:
        from app.services.reports import build_report

        r = build_report(db, "period_comparison", today - timedelta(days=9), today, None)
        assert r.subtitle.count(" al ") == 2 and "frente a" in r.subtitle  # actual vs. anterior de igual duración
        rows = {row[0]: row for row in r.tables[0].rows}
        assert rows["Hallazgos mitigados"][2] == "2" and rows["Hallazgos mitigados"][1] == "0"  # actual 2, anterior 0
        assert rows["Hallazgos mitigados"][3] == "+2"
        default = build_report(db, "mttr", None, None, None)
        assert str(today.year) in default.subtitle  # sin fechas: últimos 30 días
        assert date.today().year == today.year


def test_risk_suffix_does_not_repeat_cves_already_in_the_text() -> None:
    from app.services.reports.model import risk_suffix

    assert risk_suffix("El equipo srv-a con CVE-2021-44228.", ["CVE-2021-44228"]) == ""
    assert risk_suffix("El equipo srv-a.", ["CVE-2021-44228", "CVE-2022-0778"]) == " (CVE-2021-44228, CVE-2022-0778)"
    assert risk_suffix("Texto sin CVE con cve-2021-44228 en minúsculas", ["CVE-2021-44228"]) == ""
