import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KevEntry(Base):
    """Catálogo CISA KEV (known_exploited_vulnerabilities.json)."""

    __tablename__ = "kev_entries"
    __table_args__ = (Index("ix_kev_date_added", "date_added"),)

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    vendor_project: Mapped[str] = mapped_column(String(200), default="")
    product: Mapped[str] = mapped_column(String(200), default="")
    vulnerability_name: Mapped[str] = mapped_column(String(500), default="")
    date_added: Mapped[date] = mapped_column(Date)
    short_description: Mapped[str] = mapped_column(Text, default="")
    required_action: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date] = mapped_column(Date)
    ransomware_use: Mapped[str] = mapped_column(String(20), default="Unknown")
    forensic_triage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    cwes: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    catalog_version: Mapped[str] = mapped_column(String(30), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EpssScore(Base):
    __tablename__ = "epss_scores"
    __table_args__ = (
        CheckConstraint("epss BETWEEN 0 AND 1", name="ck_epss_range"),
        CheckConstraint("percentile BETWEEN 0 AND 1", name="ck_epss_percentile_range"),
        Index("ix_epss_score_date", "score_date"),
    )

    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    score_date: Mapped[date] = mapped_column(Date, primary_key=True)
    epss: Mapped[Decimal] = mapped_column(Numeric(10, 9))
    percentile: Mapped[Decimal] = mapped_column(Numeric(10, 9))
    model_version: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ScoringConfig(Base):
    """Fórmula de riesgo versionada: cada cambio crea una versión nueva; solo una está activa."""

    __tablename__ = "scoring_configs"
    __table_args__ = (
        Index("uq_scoring_active", "is_active", unique=True, postgresql_where=text("is_active")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    weights: Mapped[dict[str, float]] = mapped_column(JSONB)
    bands: Mapped[dict[str, float]] = mapped_column(JSONB)
    sla_days: Mapped[dict[str, int]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_date", "run_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_date: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(String(10), default="cron")  # cron | manual
    status: Mapped[str] = mapped_column(String(10), default="running")  # running|success|partial|failed
    n8n_execution_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kev_catalog_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    kev_total: Mapped[int] = mapped_column(Integer, default=0)
    epss_scored: Mapped[int] = mapped_column(Integer, default=0)
    new_matches: Mapped[int] = mapped_column(Integer, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExposureSnapshot(Base):
    __tablename__ = "exposure_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    kev_open: Mapped[int] = mapped_column(Integer, default=0)
    sla_overdue: Mapped[int] = mapped_column(Integer, default=0)
    critical_assets_exposed: Mapped[int] = mapped_column(Integer, default=0)
    mean_risk: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    by_band: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
