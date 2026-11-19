import io

from docx import Document
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import select

from app.models.inventory import Asset, Vulnerability
from app.services.reports.figures import chart_png
from app.services.reports.model import Chart, Report
from app.services.reports.render_pdf import bar_chart_svg, xy_chart_svg
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env, get, pdf_text, seeded

ROC = Chart("Curva ROC", [], [], kind="xy", ref="diagonal", x_label="Otros", y_label="KEV",
            xy=[("<b>EPSS</b>", [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]), ("CVSS", [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])])  # fmt: skip
BARS = Chart("Tramos", ["0 a 10", "10 a 20"], [("Hallazgos", [3.0, 1.0])], kind="bar")


def test_figures_list_skips_empty_charts_and_keeps_the_trend_chart_first() -> None:
    from datetime import UTC, datetime

    line = Chart("Tendencia", ["01/11"], [("KEV", [1.0])])
    r = Report("x", "X", "", datetime.now(UTC), chart=line, charts=[ROC, Chart("Vacía", [], [], kind="xy"), BARS])
    assert [c.title for c in r.figures] == ["Tendencia", "Curva ROC", "Tramos"]


def test_svg_charts_escape_external_text_and_draw_the_reference() -> None:
    svg = xy_chart_svg(ROC)
    assert "<b>EPSS</b>" not in svg and "&lt;b&gt;EPSS&lt;/b&gt;" in svg
    assert "Azar" in svg and svg.count("<polyline") == 2 and 'stroke-dasharray="5 2"' in svg  # 2ª serie con guiones
    pr = xy_chart_svg(Chart("PR", [], [], kind="xy", ref="h:0.7000", xy=[("EPSS", [(0.5, 1.0), (1.0, 0.7)])]))
    assert "Línea base (70 %)" in pr
    bars = bar_chart_svg(BARS)
    assert bars.count("<rect") == 4 and ">3<" in bars and "0 a 10" in bars


def test_png_figures_are_600_dpi_for_every_kind() -> None:
    for chart in (ROC, BARS, Chart("Tendencia", ["a", "b"], [("KEV", [1.0, 2.0])])):
        img = Image.open(io.BytesIO(chart_png(chart)))
        assert round(img.info["dpi"][0]) == 600, chart.kind


def test_criteria_evaluation_without_both_classes_explains_why_there_are_no_curves(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    text = pdf_text(get(c, "analista@radar.local", "criteria_evaluation", "pdf").content)
    assert "no hay nada que separar" in text and "Curva ROC" not in text


def test_inventory_profile_report_has_statistics_quality_and_figures(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    text = pdf_text(get(c, "analista@radar.local", "inventory_profile", "pdf").content)
    for part in ("Perfil del inventario", "Calidad de los datos", "Resumen estadístico", "Mediana", "Por criticidad del activo",
                 "Lectura de los resultados", "EPSS: distribución por tramos", "Cómo leerla"):  # fmt: skip
        assert part in text, part
    doc = Document(io.BytesIO(get(c, "analista@radar.local", "inventory_profile", "docx").content))
    assert len(doc.inline_shapes) == 3  # una distribución por variable (score, EPSS, CVSS)
    wb = load_workbook(io.BytesIO(get(c, "analista@radar.local", "inventory_profile", "xlsx").content))
    charts = [ws for ws in wb.worksheets if ws._charts]
    assert len(charts) == 3 and all(ws["A1"].value == "Tramo" for ws in charts)


def test_criteria_evaluation_report_has_roc_pr_and_confusion_matrices(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    with m() as db:  # un CVE abierto fuera de KEV: sin las dos clases no hay nada que separar
        asset = db.execute(select(Asset).limit(1)).scalar_one()
        db.add(Vulnerability(asset_id=asset.id, cve_id="CVE-2020-0001", cvss_score=9.8, status="open"))
        db.commit()
    text = pdf_text(get(c, "analista@radar.local", "criteria_evaluation", "pdf").content)
    for part in ("Evaluación de criterios frente a KEV", "Lectura de los resultados", "no se evalúa", "Curva ROC",
                 "Precisión frente a cobertura", "Reglas fijas", "KEV sin marcar"):  # fmt: skip
        assert part in text, part
    wb = load_workbook(io.BytesIO(get(c, "analista@radar.local", "criteria_evaluation", "xlsx").content))
    assert {"Curva ROC", "Precisión frente a cobertura"} <= set(wb.sheetnames)
    assert type(wb["Curva ROC"]._charts[0]).__name__ == "ScatterChart"
    rules = next(ws for ws in wb.worksheets if ws.title.startswith("Reglas fijas"))
    assert rules["A3"].value == "Regla" and rules.max_row >= 4
