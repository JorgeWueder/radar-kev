"""Word con python-docx."""

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from app.services.reports.model import Report, risk_suffix


def render(report: Report) -> bytes:
    doc = Document()
    sec = doc.sections[0]
    if report.wide:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(1.8))
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)

    doc.add_heading(report.title, level=0)
    p = doc.add_paragraph(report.subtitle)
    p.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    meta = doc.add_paragraph(f"Generado el {report.generated_at.strftime('%d/%m/%Y %H:%M')} UTC · Radar de explotación activa (KEV/EPSS)")
    meta.runs[0].font.size = Pt(8)
    meta.runs[0].font.color.rgb = RGBColor(0x77, 0x77, 0x77)

    if report.kpis:
        t = doc.add_table(rows=2, cols=len(report.kpis))
        for i, (label, value) in enumerate(report.kpis):
            v = t.cell(0, i).paragraphs[0].add_run(value)
            v.bold, v.font.size = True, Pt(18)
            lab = t.cell(1, i).paragraphs[0].add_run(label)
            lab.font.size, lab.font.color.rgb = Pt(8), RGBColor(0x55, 0x55, 0x55)
        doc.add_paragraph()

    if report.ai:
        s = report.ai["summary"]
        h = doc.add_heading("Resumen ejecutivo", level=1)
        badge = doc.add_paragraph()
        r = badge.add_run(f"✦ Generado por IA · {report.ai['provider']}/{report.ai['model']} · {report.ai['generated_at'][:10]}")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(8), RGBColor(0x1D, 0x5B, 0xB8)
        doc.add_paragraph(s["tendencia"])
        doc.add_paragraph().add_run("Riesgos principales").bold = True
        for x in s["riesgos_principales"]:
            doc.add_paragraph(x["texto"] + risk_suffix(x["texto"], x["cve_ids"]), style="List Bullet")
        doc.add_paragraph().add_run("Recomendaciones").bold = True
        for x in s["recomendaciones"]:
            doc.add_paragraph(x, style="List Bullet")
        note = doc.add_paragraph("Texto redactado por un modelo de lenguaje a partir de las cifras de este radar; revíselo antes de difundirlo.")
        note.runs[0].italic, note.runs[0].font.size = True, Pt(8)
        del h

    for n in report.notes:
        doc.add_paragraph(n).runs[0].font.color.rgb = RGBColor(0x8A, 0x53, 0x00)

    for table in report.tables:
        doc.add_heading(table.title, level=1)
        if not table.rows:
            doc.add_paragraph("Sin datos.")
            continue
        t = doc.add_table(rows=1, cols=len(table.columns))
        t.style = "Light Grid Accent 1"
        for i, c in enumerate(table.columns):
            cell = t.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(c)
            run.bold, run.font.size = True, Pt(8.5)
        for row in table.rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                para = cells[i].paragraphs[0]
                run = para.add_run(str(v))
                run.font.size = Pt(8.5)
                if i in table.right:
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if table.note:
            doc.add_paragraph(table.note).runs[0].font.size = Pt(8)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
