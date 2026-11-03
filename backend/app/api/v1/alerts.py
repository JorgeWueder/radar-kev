import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import require
from app.db.session import get_db
from app.models.auth import User
from app.models.ops import Alert, AlertRead
from app.services.alerting import unread_count

router = APIRouter(prefix="/alerts", tags=["alertas"])


class DeliveryOut(BaseModel):
    channel: str
    status: str
    last_error: str | None


class AlertOut(BaseModel):
    id: uuid.UUID
    alert_type: str
    severity: str
    message: str
    created_at: datetime
    is_read: bool
    cve_id: str | None
    hostname: str | None
    ticket_id: uuid.UUID | None
    deliveries: list[DeliveryOut]


class AlertList(BaseModel):
    items: list[AlertOut]
    total: int
    unread: int


@router.get("/unread-count")
def get_unread(user: User = Depends(require("alerts", "view")), db: Session = Depends(get_db)) -> dict[str, int]:
    return {"unread": unread_count(db, user.id)}


@router.get("", response_model=AlertList)
def list_alerts(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require("alerts", "view")),
    db: Session = Depends(get_db),
) -> AlertList:
    from app.models.ops import Ticket

    read_ids = select(AlertRead.alert_id).where(AlertRead.user_id == user.id)
    stmt = select(Alert)
    if unread_only:
        stmt = stmt.where(Alert.id.not_in(read_ids))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)).scalars().unique().all()
    read = set(db.execute(read_ids).scalars())
    tickets = {
        t.vulnerability_id: t.id
        for t in db.execute(
            select(Ticket).where(Ticket.vulnerability_id.in_([a.vulnerability_id for a in rows if a.vulnerability_id]))
        ).scalars().unique()
    }
    items = [
        AlertOut(
            id=a.id, alert_type=a.alert_type, severity=a.severity, message=a.message, created_at=a.created_at,
            is_read=a.id in read, cve_id=a.vulnerability.cve_id if a.vulnerability else None,
            hostname=a.vulnerability.asset.hostname if a.vulnerability else None,
            ticket_id=tickets.get(a.vulnerability_id) if a.vulnerability_id else None,
            deliveries=[DeliveryOut(channel=d.channel, status=d.status, last_error=d.last_error) for d in a.deliveries],
        )
        for a in rows
    ]
    return AlertList(items=items, total=total, unread=unread_count(db, user.id))


def _mark(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    if ids:
        db.execute(
            insert(AlertRead).values([{"alert_id": i, "user_id": user_id} for i in ids]).on_conflict_do_nothing()
        )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all(user: User = Depends(require("alerts", "view")), db: Session = Depends(get_db)) -> None:
    _mark(db, user.id, list(db.execute(select(Alert.id)).scalars()))
    db.commit()


@router.post("/{alert_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(
    alert_id: uuid.UUID, user: User = Depends(require("alerts", "view")), db: Session = Depends(get_db)
) -> None:
    if db.get(Alert, alert_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta no encontrada")
    _mark(db, user.id, [alert_id])
    db.commit()
