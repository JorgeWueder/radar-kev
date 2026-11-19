from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.core.ratelimit import limiter
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


@router.get("/descriptive")
def descriptive(_: User = Depends(require("dashboard", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Estadística descriptiva de los hallazgos abiertos (score, EPSS y CVSS): resumen, distribución por tramos,
    comparación por criticidad y entorno, y KEV frente al resto. Cada bloque trae su lectura en español."""
    from app.services.descriptive import descriptive as build

    return build(db)


@router.get("/evaluation")
def evaluation(_: User = Depends(require("dashboard", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Qué tan bien separan CVSS, EPSS y el score sin KEV los CVE explotados (KEV) de los demás: ROC/AUC con IC 95 %,
    precisión-cobertura y matrices de confusión de reglas fijas. Por CVE único; no se entrena nada."""
    from app.services.evaluation import evaluation as build

    return build(db)


@router.get("/evaluation/universe")
def universe_latest(_: User = Depends(require("dashboard", "view")), db: Session = Depends(get_db)) -> dict[str, Any] | None:
    """Último resultado guardado de la prueba prospectiva de EPSS sobre todo el universo de CVE (null si no hay)."""
    from app.services import universe

    return universe.latest(db)


@router.post("/evaluation/universe")
@limiter.limit("5/hour")
def universe_compute(
    request: Request,
    horizon: int = Query(90),
    actor: User = Depends(require("workflow", "create")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recalcula la prueba prospectiva: descarga el CSV completo de EPSS de hace `horizon` días y lo cruza con KEV.
    Tarda unos segundos (el archivo tiene cientos de miles de CVE); queda en la bitácora."""
    from app.services import universe

    try:
        out = universe.compute(db, horizon)
    except (universe.UniverseError, RuntimeError) as e:
        db.rollback()
        audit(db, request, "dashboard", "universe_eval", user=actor, result="failure", detail={"error": str(e)[:200]})
        db.commit()
        code = status.HTTP_422_UNPROCESSABLE_CONTENT if isinstance(e, universe.UniverseError) else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(code, str(e)[:300]) from None
    audit(db, request, "dashboard", "universe_eval", user=actor,
          detail={"horizon": horizon, "as_of": out["as_of"], "n": out["n"], "positives": out["positives"]})  # fmt: skip
    db.commit()
    return out


@router.get("/top-assets")
def top_assets(
    limit: int = Query(10, ge=1, le=25),
    _: User = Depends(require("dashboard", "view")),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = stats.aggregates(db, top_n=limit)["top_assets"]
    return result
