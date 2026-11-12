"""Excel con openpyxl: formato, filtros, paneles fijos, anchos y gráfico de tendencia."""

import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.reports.model import Report

HEAD_FILL = PatternFill("solid", fgColor="1D5BB8")
HEAD_FONT = Font(bold=True, color="FFFFFF")
_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")


def safe(v: Any) -> Any:
    """Evita la inyección de fórmulas al abrir el archivo en Excel."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _num(v: Any) -> Any:
    """Convierte '12,5' o '97,3 %' a número para que Excel pueda ordenar y calcular (conserva el texto si no es numérico)."""
    if isinstance(v, str):
        m = re.fullmatch(r"-?\d+(?:[ \d]*)(?:,\d+)?", v.strip())
        if m:
            try:
                return float(v.replace(" ", "").replace(",", "."))
            except ValueError:
                return v
    return v


def _sheet_name(name: str, used: set[str]) -> str:
    base = _BAD_SHEET.sub(" ", name)[:28].strip() or "Datos"
    out, i = base, 2
    while out in used:
        out = f"{base[:25]} {i}"
        i += 1
    used.add(out)
    return out


def render(report: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Resumen"
    used = {"Resumen"}
    ws["A1"], ws["A1"].font = report.title, Font(bold=True, size=16)
    ws["A2"] = report.subtitle
    ws["A3"] = f"Generado el {report.generated_at.strftime('%d/%m/%Y %H:%M')} UTC"
    ws["A3"].font = Font(color="777777", size=9)
    row = 5
    for label, value in report.kpis:
        ws.cell(row, 1, label).font = Font(color="555555")
        c = ws.cell(row, 2, safe(_num(value)))
        c.font, c.alignment = Font(bold=True, size=13), Alignment(horizontal="right")
        row += 1
    if report.ai:
        row += 1
        ws.cell(row, 1, f"✦ Generado por IA · {report.ai['provider']}/{report.ai['model']} · {report.ai['generated_at'][:10]}").font = Font(bold=True, color="1D5BB8")
        s = report.ai["summary"]
        row += 1
        ws.cell(row, 1, "Resumen ejecutivo").font = Font(bold=True)
        ws.cell(row, 2, safe(s["tendencia"])).alignment = Alignment(wrap_text=True, vertical="top")
        for x in s["riesgos_principales"]:
            row += 1
            ws.cell(row, 1, "Riesgo")
            ws.cell(row, 2, safe(x["texto"])).alignment = Alignment(wrap_text=True, vertical="top")
        for x in s["recomendaciones"]:
            row += 1
            ws.cell(row, 1, "Recomendación")
            ws.cell(row, 2, safe(x)).alignment = Alignment(wrap_text=True, vertical="top")
    for n in report.notes:
        row += 2
        ws.cell(row, 1, n).font = Font(color="8A5300", italic=True)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 90

    for table in report.tables:
        sh = wb.create_sheet(_sheet_name(table.title, used))
        sh.append([table.title])
        sh["A1"].font = Font(bold=True, size=12)
        sh.append([])
        sh.append(table.columns)
        for i in range(1, len(table.columns) + 1):
            c = sh.cell(3, i)
            c.fill, c.font = HEAD_FILL, HEAD_FONT
            c.alignment = Alignment(horizontal="right" if (i - 1) in table.right else "left", vertical="center")
        for r in table.rows:
            sh.append([safe(_num(v)) if (i in table.right) else safe(v) for i, v in enumerate(r)])
        if table.rows:
            sh.auto_filter.ref = f"A3:{get_column_letter(len(table.columns))}{3 + len(table.rows)}"
        sh.freeze_panes = "A4"
        for i, col in enumerate(table.columns, start=1):
            longest = max([len(str(col))] + [len(str(r[i - 1])) for r in table.rows[:300]])
            sh.column_dimensions[get_column_letter(i)].width = min(60, max(10, longest + 2))
        if table.how_to_read:
            c = sh.cell(5 + len(table.rows) + (1 if table.note else 0) + 1, 1, "Cómo leerla: " + table.how_to_read)
            c.font = Font(italic=True, color="333333")
        if table.note:
            sh.cell(5 + len(table.rows), 1, table.note).font = Font(italic=True, color="666666")

    if report.chart and report.chart.labels:
        ch = wb.create_sheet(_sheet_name("Gráfico", used))
        ch.append(["Fecha", *[name for name, _ in report.chart.series]])
        for i, label in enumerate(report.chart.labels):
            ch.append([label, *[vals[i] for _, vals in report.chart.series]])
        line = LineChart()
        line.title, line.height, line.width = report.chart.title, 9, 22
        line.add_data(Reference(ch, min_col=2, max_col=1 + len(report.chart.series), min_row=1, max_row=1 + len(report.chart.labels)), titles_from_data=True)
        line.set_categories(Reference(ch, min_col=1, min_row=2, max_row=1 + len(report.chart.labels)))
        ch.add_chart(line, "E2")
        if report.chart.how_to_read:
            ch["E22"] = "Cómo leerlo: " + report.chart.how_to_read
            ch["E22"].font = Font(italic=True, color="333333")
        ch.column_dimensions["A"].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
