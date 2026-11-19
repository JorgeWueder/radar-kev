"""Laboratorio de modelos (experimental): datasets construidos y trabajos en segundo plano.

Nada de esto alimenta la detección ni el score: es un módulo de análisis aparte."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MlDataset(Base):
    __tablename__ = "ml_datasets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(12), default="building")  # building | ready | failed
    params: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)  # fotos, horizonte, muestreo, semilla
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)  # URL, fecha, sha256, licencia
    stats: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)  # filas, positivos, por partición
    file_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MlJob(Base):
    """Trabajo en segundo plano (construir un dataset, entrenar…) con su progreso, para el monitoreo en vivo."""

    __tablename__ = "ml_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))  # dataset | train …
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | running | done | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0 a 100
    message: Mapped[str] = mapped_column(String(300), default="")
    log: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)  # [{t, msg}]
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # dataset o modelo
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
