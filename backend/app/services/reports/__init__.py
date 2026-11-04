from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.services.reports import builders, render_docx, render_pdf, render_xlsx
from app.services.reports.builders import CATALOG, MANAGEMENT
from app.services.reports.model import Report, ReportError

Fmt = Literal["pdf", "docx", "xlsx"]
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

__all__ = ["CATALOG", "CONTENT_TYPES", "MANAGEMENT", "Generated", "ReportError", "build_report", "render"]


@dataclass
class Generated:
    content: bytes
    content_type: str
    filename: str
    rows: int


def default_period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or datetime.now(UTC).date()
    return (date_from or end - timedelta(days=29)), end


def build_report(db: Session, key: str, date_from: date | None, date_to: date | None, cve_id: str | None) -> Report:
    start, end = default_period(date_from, date_to)
    return builders.build(db, key, start, end, cve_id)


def render(report: Report, fmt: Fmt) -> Generated:
    data = {"pdf": render_pdf.render, "docx": render_docx.render, "xlsx": render_xlsx.render}[fmt](report)
    stamp = report.generated_at.strftime("%Y%m%d")
    return Generated(data, CONTENT_TYPES[fmt], f"radar_{report.key}_{stamp}.{fmt}", sum(len(t.rows) for t in report.tables))
