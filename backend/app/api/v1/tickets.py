import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.models.inventory import Asset, Vulnerability
from app.models.ops import Ticket, TicketEvent
from app.services.intel import get_active_config
from app.services.scoring import ScoringParams, sla_state

router = APIRouter(prefix="/tickets", tags=["tickets"])

Status = Literal["open", "in_progress", "resolved", "closed", "risk_accepted"]
Priority = Literal["critical", "high", "medium", "low"]
OPEN = ("open", "in_progress")
# Estado del ticket → estado del hallazgo (resolver un ticket mitiga el hallazgo, aceptar el riesgo lo acepta).
VULN_STATUS = {"open": "open", "in_progress": "in_progress", "resolved": "mitigated", "closed": "mitigated",
               "risk_accepted": "accepted"}  # fmt: skip
DONE = ("resolved", "closed", "risk_accepted")


class Person(BaseModel):
    id: uuid.UUID
    name: str


class TicketOut(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    status: str
    priority: str
    assignee: Person | None
    due_date: date | None
    sla_state: str
    cve_id: str
    hostname: str
    created_at: datetime
    ai_generated: bool


class EventOut(BaseModel):
    id: int
    event: str
    user: str | None
    data: dict[str, Any]
    at: datetime


class TicketDetail(TicketOut):
    description: str
    ai_enrichment: dict[str, Any] | None
    vulnerability_id: uuid.UUID
    cvss_score: float | None
    risk_score: float | None
    asset_criticality: int
    resolved_at: datetime | None
    events: list[EventOut]


class TicketList(BaseModel):
    items: list[TicketOut]
    total: int


class TicketPatch(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    assignee_id: uuid.UUID | None = None


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _out(t: Ticket, params: ScoringParams, today: date) -> TicketOut:
    v = t.vulnerability
    return TicketOut(
        id=t.id, code=t.code, title=t.title, status=t.status, priority=t.priority,
        assignee=Person(id=t.assignee.id, name=t.assignee.full_name) if t.assignee else None,
        due_date=t.due_date, sla_state=sla_state(params, t.due_date, today, active=t.status in OPEN),
        cve_id=v.cve_id, hostname=v.asset.hostname, created_at=t.created_at, ai_generated=t.ai_generated,
    )  # fmt: skip


def _get(db: Session, ticket_id: uuid.UUID) -> Ticket:
    t = db.get(Ticket, ticket_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket no encontrado")
    return t


@router.get("", response_model=TicketList)
def list_tickets(
    q: str | None = None,
    status_: str | None = Query(None, alias="status", pattern="^(open|in_progress|resolved|closed|risk_accepted|active)$"),
    priority: Priority | None = None,
    assignee_id: uuid.UUID | None = None,
    mine: bool = False,
    overdue: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require("tickets", "view")),
    db: Session = Depends(get_db),
) -> TicketList:
    stmt = select(Ticket).join(Vulnerability, Vulnerability.id == Ticket.vulnerability_id).join(
        Asset, Asset.id == Vulnerability.asset_id
    )
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(or_(Ticket.code.ilike(like), Ticket.title.ilike(like),
                              Vulnerability.cve_id.ilike(like), Asset.hostname.ilike(like)))  # fmt: skip
    if status_ == "active":
        stmt = stmt.where(Ticket.status.in_(OPEN))
    elif status_:
        stmt = stmt.where(Ticket.status == status_)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if assignee_id:
        stmt = stmt.where(Ticket.assignee_id == assignee_id)
    if mine:
        stmt = stmt.where(Ticket.assignee_id == user.id)
    if overdue:
        stmt = stmt.where(Ticket.status.in_(OPEN), Ticket.due_date < datetime.now(UTC).date())
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rank = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=Ticket.priority, else_=4)
    rows = db.execute(stmt.order_by(rank, Ticket.due_date.asc().nulls_last(), Ticket.code).limit(limit).offset(offset)).scalars().unique().all()
    _, params = get_active_config(db)
    today = datetime.now(UTC).date()
    return TicketList(items=[_out(t, params, today) for t in rows], total=total)


@router.get("/{ticket_id}", response_model=TicketDetail)
def get_ticket(
    ticket_id: uuid.UUID, _: User = Depends(require("tickets", "view")), db: Session = Depends(get_db)
) -> TicketDetail:
    t = _get(db, ticket_id)
    _cfg, params = get_active_config(db)
    v = t.vulnerability
    events = db.execute(
        select(TicketEvent).where(TicketEvent.ticket_id == t.id).order_by(TicketEvent.at.desc(), TicketEvent.id.desc())
    ).scalars().unique().all()
    base = _out(t, params, datetime.now(UTC).date())
    return TicketDetail(
        **base.model_dump(), description=t.description, ai_enrichment=t.ai_enrichment, vulnerability_id=v.id,
        cvss_score=float(v.cvss_score) if v.cvss_score is not None else None,
        risk_score=float(v.risk_score) if v.risk_score is not None else None,
        asset_criticality=v.asset.criticality, resolved_at=t.resolved_at,
        events=[EventOut(id=e.id, event=e.event, user=e.user.full_name if e.user else None, data=e.data, at=e.at)
                for e in events],
    )  # fmt: skip


@router.patch("/{ticket_id}", response_model=TicketOut)
def patch_ticket(
    request: Request,
    ticket_id: uuid.UUID,
    body: TicketPatch,
    actor: User = Depends(require("tickets", "edit")),
    db: Session = Depends(get_db),
) -> TicketOut:
    t = _get(db, ticket_id)
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    if body.status is not None and body.status != t.status:
        old = t.status
        t.status = body.status
        t.resolved_at = datetime.now(UTC) if body.status in DONE else None
        vuln = t.vulnerability
        vuln.status = VULN_STATUS[body.status]
        vuln.resolved_at = datetime.now(UTC) if body.status in DONE else None
        db.add(TicketEvent(ticket_id=t.id, user_id=actor.id, event="status", data={"from": old, "to": body.status}))
        changes["status"] = [old, body.status]
    if body.priority is not None and body.priority != t.priority:
        db.add(TicketEvent(ticket_id=t.id, user_id=actor.id, event="priority", data={"from": t.priority, "to": body.priority}))
        changes["priority"] = [t.priority, body.priority]
        t.priority = body.priority
    if "assignee_id" in sent and body.assignee_id != t.assignee_id:
        new = None
        if body.assignee_id is not None:
            new = db.get(User, body.assignee_id)
            if new is None or not new.is_active:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Responsable inexistente o inactivo")
        db.add(TicketEvent(ticket_id=t.id, user_id=actor.id, event="assignee",
                           data={"to": new.full_name if new else None}))  # fmt: skip
        changes["assignee"] = new.full_name if new else None
        t.assignee_id = body.assignee_id
        t.assignee = new
    if changes:
        audit(db, request, "tickets", "edit", user=actor, detail={"ticket": t.code, "changes": changes})
    db.commit()
    _, params = get_active_config(db)
    return _out(t, params, datetime.now(UTC).date())


@router.post("/{ticket_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    request: Request,
    ticket_id: uuid.UUID,
    body: CommentIn,
    actor: User = Depends(require("tickets", "edit")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    t = _get(db, ticket_id)
    db.add(TicketEvent(ticket_id=t.id, user_id=actor.id, event="comment", data={"text": body.text}))
    audit(db, request, "tickets", "comment", user=actor, detail={"ticket": t.code})
    db.commit()
    return {"status": "ok"}
