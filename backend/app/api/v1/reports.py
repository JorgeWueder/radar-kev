import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai.enrichment import EnrichmentError
from app.ai.summary import executive_summary
from app.api.deps import audit, require, user_permissions
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.models.auth import User
from app.services import reports

router = APIRouter(prefix="/reports", tags=["reportes"])
TYPES = Literal[
    "kev_by_asset", "open_tickets", "sla_overdue", "cve_detail",
    "exposure_trend", "mttr", "sla_compliance", "period_comparison",
    "inventory_profile", "criteria_evaluation", "epss_universe",
    "ml_dataset", "ml_training", "ml_evaluation", "ml_explain",
]  # fmt: skip


@router.get("/catalog")
def catalog(_: User = Depends(require("reports", "view"))) -> list[dict[str, Any]]:
    return reports.CATALOG


@router.post("/{rtype}")
@limiter.limit("20/minute")
def generate(
    request: Request,
    rtype: TYPES,
    fmt: Literal["pdf", "docx", "xlsx"] = "pdf",
    date_from: date | None = None,
    date_to: date | None = None,
    ai_summary: bool = False,
    cve_id: str | None = Query(None, pattern=r"^(?i:CVE)-\d{4}-\d{4,}$"),
    dataset_id: uuid.UUID | None = None,
    model_id: uuid.UUID | None = None,
    op: int = Query(1, ge=1, le=5),
    user: User = Depends(require("reports", "export")),
    db: Session = Depends(get_db),
) -> Response:
    """Genera el reporte en el formato pedido. Cada exportación queda en la bitácora."""
    if rtype.startswith("ml_") and "ml:view" not in user_permissions(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no puede ver el laboratorio de modelos")
    if op not in (1, 5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El punto de operación debe ser 1 o 5 (% del universo)")
    try:
        report = reports.build_report(db, rtype, date_from, date_to, cve_id, dataset_id, model_id, op)
    except reports.ReportError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None

    ai_used = False
    if ai_summary and rtype in reports.MANAGEMENT:
        if "ai:view" not in user_permissions(user):
            report.notes.append("Resumen ejecutivo con IA omitido: su rol no puede usar la IA.")
        else:
            try:
                report.ai = executive_summary(db, user_id=user.id)
                ai_used = True
            except (providers.AIUnavailable, EnrichmentError) as e:
                # El núcleo no depende de la IA: el reporte se genera igual y se indica por qué no hay resumen.
                report.notes.append(f"Resumen ejecutivo con IA no disponible: {str(e)[:160]}")
            db.commit()  # conserva el registro de la interacción de IA (también si falló)

    out = reports.render(report, fmt)
    audit(db, request, "reports", "export", user=user,
          detail={"type": rtype, "fmt": fmt, "rows": out.rows, "ai_summary": ai_used, "bytes": len(out.content),
                  "period": [str(date_from), str(date_to)] if rtype in reports.MANAGEMENT else None,
                  "dataset": str(dataset_id) if dataset_id else None, "model": str(model_id) if model_id else None})  # fmt: skip
    db.commit()
    return Response(out.content, media_type=out.content_type,
                    headers={"Content-Disposition": f'attachment; filename="{out.filename}"'})
