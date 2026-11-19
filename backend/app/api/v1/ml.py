"""Laboratorio de modelos (experimental). Fase 1: datasets. Nada de esto toca la detección ni el score."""

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import audit, require
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.ml import dataset as ds
from app.ml import jobs, profile, sources
from app.models.auth import User
from app.models.intel import KevEntry
from app.models.ml import MlDataset, MlJob

router = APIRouter(prefix="/ml", tags=["laboratorio"])


class DatasetIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field("", max_length=2000)
    start: date = date(2025, 1, 1)
    horizon_days: Literal[30, 90, 180] = 90
    neg_rate: float = Field(0.05, ge=0.005, le=0.5)
    seed: int = Field(7, ge=0, le=1_000_000)


class DatasetPatch(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=120)
    description: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=10000)
    tags: list[str] | None = Field(None, max_length=20)


def _out(d: MlDataset) -> dict[str, Any]:
    return {"id": str(d.id), "name": d.name, "description": d.description, "notes": d.notes, "tags": d.tags,
            "status": d.status, "params": d.params, "sources": d.sources, "stats": d.stats,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}  # fmt: skip


def _job_out(j: MlJob) -> dict[str, Any]:
    return {"id": str(j.id), "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
            "log": j.log[-60:], "target_id": str(j.target_id) if j.target_id else None, "started_at": j.started_at.isoformat(),
            "finished_at": j.finished_at.isoformat() if j.finished_at else None}  # fmt: skip


def _get(db: Session, dataset_id: uuid.UUID) -> MlDataset:
    d = db.get(MlDataset, dataset_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado")
    return d


def _ready(d: MlDataset) -> Path:
    if d.status != "ready" or not d.file_path or not Path(d.file_path).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "El dataset aún no está listo")
    return Path(d.file_path)


@router.get("/features")
def features(_: User = Depends(require("ml", "view"))) -> list[dict[str, str]]:
    """Diccionario de variables: qué es cada una, de qué fuente sale y cómo se evita usar datos del futuro."""
    return ds.FEATURES


@router.get("/datasets")
def list_datasets(_: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(MlDataset).order_by(MlDataset.created_at.desc())).scalars().all()
    return [_out(d) for d in rows]


@router.post("/datasets", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("6/hour")
def create_dataset(request: Request, body: DatasetIn, actor: User = Depends(require("ml", "create")),
                   db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Construye un dataset en segundo plano (descarga EPSS, NVD y Exploit-DB; minutos la primera vez)."""
    kev_rows = db.execute(select(KevEntry.cve_id, KevEntry.date_added)).all()
    if not kev_rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El catálogo KEV está vacío: ejecute primero el flujo diario")
    kev = pd.DataFrame(kev_rows, columns=["cve", "date_added"])
    until = min(max(kev["date_added"]), date.today())
    shots = ds.snapshots(body.start, until, body.horizon_days)
    if len(shots) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Con esa fecha de inicio y horizonte hay menos de 3 fotos mensuales: adelante la fecha de inicio")  # fmt: skip
    d = MlDataset(name=body.name, description=body.description, status="building", created_by=actor.id, tags=[], sources=[],
                  params={"start": body.start.isoformat(), "until": until.isoformat(), "horizon_days": body.horizon_days,
                          "neg_rate": body.neg_rate, "seed": body.seed, "snapshots": len(shots), "split": "temporal 70/15/15"},
                  stats={})  # fmt: skip
    db.add(d)
    db.commit()
    db.refresh(d)
    dataset_id = d.id
    out_path = sources.data_dir() / "datasets" / f"{dataset_id}.csv.gz"

    def work(rep: jobs.Reporter, maker: jobs.Maker) -> None:
        res = ds.build(kev, body.start, until, body.horizon_days, body.neg_rate, body.seed, out_path, rep)
        rep(98, "Calculando el perfil (estadística y validación)")
        prof = profile.profile(ds.load(out_path), body.neg_rate)
        out_path.with_suffix("").with_suffix(".profile.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        with maker() as s:
            row = s.get(MlDataset, dataset_id)
            assert row is not None
            row.status, row.sources, row.stats, row.file_path = "ready", res["sources"], res["stats"], str(out_path)
            s.commit()

    bind = db.get_bind()

    def failed(msg: str) -> None:
        with sessionmaker(bind=bind)() as s:
            row = s.get(MlDataset, dataset_id)
            if row is not None:
                row.status = "failed"
                row.stats = {"error": msg}
                s.commit()

    try:
        job = jobs.start(db, "dataset", dataset_id, actor.id, work, failed)
    except jobs.JobBusy as e:
        db.delete(d)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    audit(db, request, "ml", "dataset_create", user=actor, detail={"dataset": str(dataset_id), **d.params})
    db.commit()
    return {"dataset_id": str(dataset_id), "job_id": str(job.id)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(_get(db, dataset_id)) | {"features": ds.FEATURES, "excluded": ds.EXCLUDED}


@router.patch("/datasets/{dataset_id}")
def edit_dataset(request: Request, dataset_id: uuid.UUID, body: DatasetPatch, actor: User = Depends(require("ml", "edit")),
                 db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Editor de metadata: nombre, descripción, notas y etiquetas (las fuentes y estadísticas no se editan)."""
    d = _get(db, dataset_id)
    changes = body.model_dump(exclude_none=True)
    if "tags" in changes:
        changes["tags"] = sorted({t.strip()[:40] for t in changes["tags"] if t.strip()})
    for k, v in changes.items():
        setattr(d, k, v)
    audit(db, request, "ml", "dataset_edit", user=actor, detail={"dataset": str(dataset_id), "fields": sorted(changes)})
    db.commit()
    db.refresh(d)
    return _out(d)


@router.get("/datasets/{dataset_id}/profile")
def dataset_profile(dataset_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    d = _get(db, dataset_id)
    path = _ready(d)
    cache = path.with_suffix("").with_suffix(".profile.json")
    if cache.exists():
        data: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return data
    prof = profile.profile(ds.load(path), float(d.params.get("neg_rate", 0.05)))  # type: ignore[arg-type]
    cache.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    return prof


@router.get("/datasets/{dataset_id}/sample")
def dataset_sample(dataset_id: uuid.UUID, label: int | None = Query(None, ge=0, le=1), limit: int = Query(50, ge=1, le=200),
                   _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    return profile.sample(ds.load(_ready(_get(db, dataset_id))), limit, label)


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    j = db.get(MlJob, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajo no encontrado")
    return _job_out(j)


@router.get("/jobs")
def list_jobs(kind: str | None = None, limit: int = Query(20, ge=1, le=100), _: User = Depends(require("ml", "view")),
              db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    q = select(MlJob).order_by(MlJob.started_at.desc()).limit(limit)
    if kind:
        q = q.where(MlJob.kind == kind)
    return [_job_out(j) for j in db.execute(q).scalars().all()]
