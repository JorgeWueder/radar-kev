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
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

ASSET_TYPES = ("server", "workstation", "network", "database", "application", "cloud", "other")
ENVIRONMENTS = ("prod", "staging", "dev")
VULN_STATUSES = ("open", "in_progress", "mitigated", "accepted", "false_positive")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("hostname", "environment"),
        CheckConstraint("criticality BETWEEN 1 AND 4", name="ck_assets_criticality"),
        CheckConstraint(
            "asset_type IN ('server','workstation','network','database','application','cloud','other')",
            name="ck_assets_type",
        ),
        CheckConstraint("environment IN ('prod','staging','dev')", name="ck_assets_environment"),
        Index("ix_assets_criticality", "criticality"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname: Mapped[str] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    asset_type: Mapped[str] = mapped_column(String(20), default="server")
    os: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    criticality: Mapped[int] = mapped_column(SmallInteger, default=2)
    environment: Mapped[str] = mapped_column(String(10), default="prod")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Creado automáticamente por una importación: faltan datos de negocio por completar.
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", lazy="joined")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(10))  # csv | nessus
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="preview")  # preview | committed
    rows_ok: Mapped[int] = mapped_column(Integer, default=0)
    rows_error: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    payload: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    __table_args__ = (
        UniqueConstraint("asset_id", "cve_id"),
        CheckConstraint("cve_id ~ '^CVE-[0-9]{4}-[0-9]{4,}$'", name="ck_vuln_cve_format"),
        CheckConstraint("cvss_score IS NULL OR cvss_score BETWEEN 0 AND 10", name="ck_vuln_cvss"),
        CheckConstraint(
            "status IN ('open','in_progress','mitigated','accepted','false_positive')",
            name="ck_vuln_status",
        ),
        Index("ix_vuln_cve", "cve_id"),
        Index("ix_vuln_status_sla", "status", "sla_due_date"),
        Index("ix_vuln_risk", text("risk_score DESC")),
        Index(
            "ix_vuln_kev_matched",
            "kev_matched_at",
            postgresql_where=text("kev_matched_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    cve_id: Mapped[str] = mapped_column(String(20))
    cvss_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    cvss_vector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="open")
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Los rellena el cruce diario (fase 3).
    kev_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    risk_band: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sla_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped[Asset] = relationship(lazy="joined")
