from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["sistema"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Disponibilidad: responde 200 solo si la base de datos contesta."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Base de datos no disponible") from None
    return {"status": "ready"}
