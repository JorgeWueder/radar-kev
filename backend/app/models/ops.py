import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

TICKET_STATUSES = ("open", "in_progress", "resolved", "closed", "risk_accepted")
TICKET_PRIORITIES = ("critical", "high", "medium", "low")
ticket_code_seq = Sequence("ticket_code_seq", metadata=Base.metadata)


class Ticket(Base):
    """Ticket de remediación. UNIQUE(vulnerability_id): un hallazgo genera un solo ticket (idempotencia)."""

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','resolved','closed','risk_accepted')", name="ck_ticket_status"),
        CheckConstraint("priority IN ('critical','high','medium','low')", name="ck_ticket_priority"),
        Index("ix_tickets_status_due", "status", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    vulnerability_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(15), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="high")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ai_enrichment: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vulnerability = relationship("Vulnerability", lazy="joined")
    assignee = relationship("User", lazy="joined")


class TicketEvent(Base):
    __tablename__ = "ticket_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(30))  # created|status|assignee|priority|comment|enriched
    data: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", lazy="joined")


class Alert(Base):
    """UNIQUE(vulnerability_id, alert_type): la misma coincidencia nunca alerta dos veces."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("vulnerability_id", "alert_type"),
        Index("ix_alerts_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vulnerability_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"), nullable=True
    )
    alert_type: Mapped[str] = mapped_column(String(30))  # kev_new_in_env | source_unavailable
    severity: Mapped[str] = mapped_column(String(10), default="high")
    message: Mapped[str] = mapped_column(Text)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vulnerability = relationship("Vulnerability", lazy="joined")
    deliveries = relationship("AlertDelivery", lazy="selectin")


class AlertRead(Base):
    __tablename__ = "alert_reads"

    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("alert_id", "channel"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(10))  # email | webhook
    status: Mapped[str] = mapped_column(String(10), default="pending")  # sent | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationSetting(Base):
    """Configuración editable desde la app (SMTP, webhook). Los secretos se guardan cifrados (Fernet)."""

    __tablename__ = "integration_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiInteraction(Base):
    """Bitácora de IA: quién, qué prompt, con qué fuentes, qué modelo, tokens y latencia."""

    __tablename__ = "ai_interactions"
    __table_args__ = (Index("ix_ai_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    feature: Mapped[str] = mapped_column(String(20))  # enrich | assistant | exec_summary
    engine: Mapped[str] = mapped_column(String(20), default="langchain")  # langchain | langflow
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    output: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(15), default="ok")  # ok | error | ungrounded
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", lazy="joined")


class NvdCache(Base):
    __tablename__ = "nvd_cache"

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
