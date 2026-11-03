import hashlib
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.models.inventory import ImportBatch
from app.services.importers import MAX_BYTES, TEMPLATE, ImportRejected, parse_upload
from app.services.importing import commit_batch

router = APIRouter(prefix="/imports", tags=["importación"])


class BatchOut(BaseModel):
    id: uuid.UUID
    source: str
    filename: str
    status: str
    rows_ok: int
    rows_error: int
    errors: list[dict[str, object]]
    summary: dict[str, object]
    created_at: datetime
    committed_at: datetime | None


class PreviewOut(BatchOut):
    sample: list[dict[str, object]]
    hosts: int


class BatchList(BaseModel):
    items: list[BatchOut]
    total: int


def _out(b: ImportBatch) -> BatchOut:
    return BatchOut(
        id=b.id, source=b.source, filename=b.filename, status=b.status, rows_ok=b.rows_ok,
        rows_error=b.rows_error, errors=b.errors, summary=b.summary, created_at=b.created_at,
        committed_at=b.committed_at,
    )


@router.get("/template.csv")
def template(_: User = Depends(require("imports", "view"))) -> Response:
    return Response(TEMPLATE, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_hallazgos.csv"'})


@router.post("/preview", response_model=PreviewOut, status_code=status.HTTP_201_CREATED)
def preview(
    request: Request,
    file: UploadFile,
    actor: User = Depends(require("imports", "create")),
    db: Session = Depends(get_db),
) -> PreviewOut:
    data = file.file.read(MAX_BYTES + 1)  # se lee un byte de más para detectar el exceso sin cargar todo
    name = (file.filename or "archivo")[:255]
    try:
        result = parse_upload(name, data)
    except ImportRejected as e:
        audit(db, request, "imports", "preview", user=actor, result="failure",
              detail={"filename": name, "reason": str(e)})
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    batch = ImportBatch(
        source=result.source, filename=name, sha256=hashlib.sha256(data).hexdigest(),
        rows_ok=len(result.rows), rows_error=result.total_errors, errors=result.errors,
        payload=result.rows, user_id=actor.id,
    )
    db.add(batch)
    db.flush()
    audit(db, request, "imports", "preview", user=actor,
          detail={"batch": str(batch.id), "filename": name, "rows_ok": batch.rows_ok, "rows_error": batch.rows_error})
    db.commit()
    return PreviewOut(**_out(batch).model_dump(), sample=result.rows[:10],
                      hosts=len({r["hostname"] for r in result.rows}))


@router.post("/{batch_id}/commit", response_model=BatchOut)
def commit(
    request: Request,
    batch_id: uuid.UUID,
    actor: User = Depends(require("imports", "create")),
    db: Session = Depends(get_db),
) -> BatchOut:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.user_id != actor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Importación no encontrada")
    if batch.status != "preview":
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta importación ya fue aplicada")
    if batch.rows_ok == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No hay filas válidas para importar")
    summary = commit_batch(db, batch)
    audit(db, request, "imports", "import", user=actor,
          detail={"batch": str(batch.id), "filename": batch.filename, **summary})
    db.commit()
    return _out(batch)


@router.get("", response_model=BatchList)
def list_batches(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("imports", "view")),
    db: Session = Depends(get_db),
) -> BatchList:
    total = db.execute(select(func.count()).select_from(ImportBatch)).scalar_one()
    rows = db.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return BatchList(items=[_out(b) for b in rows], total=total)
