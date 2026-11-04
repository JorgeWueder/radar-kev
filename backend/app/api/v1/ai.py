import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import assistant, providers
from app.ai.enrichment import EnrichmentError, Ungrounded, enrich_ticket
from app.ai.schemas import AssistantAnswer
from app.ai.summary import executive_summary
from app.api.deps import require
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.models.auth import User
from app.models.ops import AiInteraction, Ticket

router = APIRouter(prefix="/ai", tags=["IA"])


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    history: list[ChatTurn] = Field(default=[], max_length=10)


class StatusOut(BaseModel):
    enabled: bool
    provider: str
    model: str


class InteractionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user: str | None
    feature: str
    engine: str
    provider: str
    model: str
    status: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    prompt: str
    sources: dict[str, Any]
    error: str | None


class InteractionList(BaseModel):
    items: list[InteractionOut]
    total: int


def ai_errors(db: Session, e: Exception) -> HTTPException:
    """Si la IA falla, el núcleo sigue funcionando: se informa 503/422 y la llamada queda registrada."""
    db.commit()  # conserva el registro de la interacción fallida
    if isinstance(e, Ungrounded):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "La IA generó contenido no respaldado por los datos; se descartó")
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"IA no disponible: {e}")


@router.get("/status", response_model=StatusOut)
def ai_status(_: User = Depends(require("ai", "view"))) -> StatusOut:
    meta = providers.info()
    return StatusOut(enabled=providers.is_configured(), provider=meta.provider, model=meta.model)


@router.post("/assistant/chat", response_model=AssistantAnswer)
@limiter.limit("30/minute")
def chat(request: Request, body: ChatIn, user: User = Depends(require("ai", "view")), db: Session = Depends(get_db)) -> AssistantAnswer:
    try:
        answer = assistant.ask(db, user, body.question, [t.model_dump() for t in body.history])
    except (providers.AIUnavailable, EnrichmentError) as e:
        raise ai_errors(db, e) from None
    db.commit()
    return answer


@router.post("/tickets/{ticket_id}/enrich")
def enrich(
    ticket_id: uuid.UUID, user: User = Depends(require("tickets", "edit")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    if "ai:view" not in {f"{p.module}:{p.action}" for p in user.role.permissions}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para usar la IA")
    t = db.get(Ticket, ticket_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket no encontrado")
    try:
        result = enrich_ticket(db, t, user_id=user.id)
    except (providers.AIUnavailable, EnrichmentError) as e:
        raise ai_errors(db, e) from None
    db.commit()
    return result.model_dump()


@router.post("/executive-summary")
def summary(user: User = Depends(require("ai", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    if "reports:view" not in {f"{p.module}:{p.action}" for p in user.role.permissions}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para generar resúmenes de gestión")
    try:
        out = executive_summary(db, user_id=user.id)
    except (providers.AIUnavailable, EnrichmentError) as e:
        raise ai_errors(db, e) from None
    db.commit()
    return out


@router.get("/interactions", response_model=InteractionList)
def interactions(
    feature: str | None = Query(None, pattern="^(enrich|assistant|exec_summary)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("audit", "view")),
    db: Session = Depends(get_db),
) -> InteractionList:
    stmt = select(AiInteraction)
    if feature:
        stmt = stmt.where(AiInteraction.feature == feature)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AiInteraction.created_at.desc()).limit(limit).offset(offset)).scalars().unique().all()
    return InteractionList(
        total=total,
        items=[
            InteractionOut(
                id=r.id, created_at=r.created_at, user=r.user.full_name if r.user else None, feature=r.feature, engine=r.engine,
                provider=r.provider, model=r.model, status=r.status, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
                latency_ms=r.latency_ms, prompt=r.prompt[:4000], sources=r.sources, error=r.error,
            )
            for r in rows
        ],
    )
