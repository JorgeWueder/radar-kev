from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require
from app.db.session import get_db
from app.models.auth import User
from app.services import stats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis")
def kpis(_: User = Depends(require("dashboard", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    """KPIs del caso: KEV presentes, nuevos (24 h y 7 días), SLA vencidos y por vencer, distribución por EPSS y por
    criticidad del activo, top de riesgos y estado de la última ejecución de n8n."""
    a = stats.aggregates(db, top_n=5)
    a.pop("trend", None)
    return a


@router.get("/trend")
def trend(
    days: int = Query(90, ge=7, le=365),
    _: User = Depends(require("dashboard", "view")),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    from datetime import UTC, datetime, timedelta

    end = datetime.now(UTC).date()
    return stats.trend(db, end - timedelta(days=days), end)


@router.get("/comparison")
def comparison(
    days: int = Query(30, ge=7, le=180),
    _: User = Depends(require("dashboard", "view")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Últimos `days` días frente a los `days` anteriores, con pruebas estadísticas (MTTR, SLA y tendencia de KEV)."""
    from datetime import UTC, datetime, timedelta

    end = datetime.now(UTC).date()
    return stats.comparison_tests(db, end - timedelta(days=days - 1), end)


@router.get("/top-assets")
def top_assets(
    limit: int = Query(10, ge=1, le=25),
    _: User = Depends(require("dashboard", "view")),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = stats.aggregates(db, top_n=limit)["top_assets"]
    return result
