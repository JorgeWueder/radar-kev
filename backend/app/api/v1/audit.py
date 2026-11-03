import csv
import io
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user, require
from app.core.rbac import MODULES
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.auth import User
from app.services.audit import verify_chain

router = APIRouter(prefix="/audit", tags=["bitácora"])
EXPORT_LIMIT = 50_000


class AuditOut(BaseModel):
    id: int
    ts: datetime
    user_id: uuid.UUID | None
    user_email: str | None
    actor: str
    module: str
    action: str
    result: str
    ip: str | None
    user_agent: str | None
    duration_ms: int | None
    detail: dict[str, object]


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int


class VerifyOut(BaseModel):
    ok: bool
    checked: int
    first_broken_id: int | None


class NavigationIn(BaseModel):
    module: str = Field(pattern="^[a-z_]{2,40}$")
    event: Literal["enter", "leave"]
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class Filters(BaseModel):
    user_id: uuid.UUID | None = None
    module: str | None = None
    action: str | None = None
    result: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def filters(
    user_id: uuid.UUID | None = None,
    module: str | None = Query(None, max_length=40),
    action: str | None = Query(None, max_length=60),
    result: str | None = Query(None, pattern="^(success|failure|denied)$"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Filters:
    return Filters(user_id=user_id, module=module, action=action, result=result,
                   date_from=date_from, date_to=date_to)


def _query(f: Filters) -> Select[tuple[AuditLog, str | None]]:
    stmt: Select[tuple[AuditLog, str | None]] = select(AuditLog, User.email).join(
        User, User.id == AuditLog.user_id, isouter=True
    )  # type: ignore[assignment]
    if f.user_id:
        stmt = stmt.where(AuditLog.user_id == f.user_id)
    if f.module:
        stmt = stmt.where(AuditLog.module == f.module)
    if f.action:
        stmt = stmt.where(AuditLog.action == f.action)
    if f.result:
        stmt = stmt.where(AuditLog.result == f.result)
    if f.date_from:
        stmt = stmt.where(AuditLog.ts >= f.date_from)
    if f.date_to:
        stmt = stmt.where(AuditLog.ts <= f.date_to)
    return stmt


def _out(row: AuditLog, email: str | None) -> AuditOut:
    return AuditOut(
        id=row.id, ts=row.ts, user_id=row.user_id, user_email=email, actor=row.actor,
        module=row.module, action=row.action, result=row.result, ip=row.ip,
        user_agent=row.user_agent, duration_ms=row.duration_ms, detail=row.detail,
    )


@router.get("", response_model=AuditPage)
def list_audit(
    f: Filters = Depends(filters),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("audit", "view")),
    db: Session = Depends(get_db),
) -> AuditPage:
    base = _query(f)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return AuditPage(items=[_out(r, e) for r, e in rows], total=total)


@router.get("/export")
def export_audit(
    request: Request,
    fmt: Literal["csv", "xlsx"] = "csv",
    f: Filters = Depends(filters),
    user: User = Depends(require("audit", "export")),
    db: Session = Depends(get_db),
) -> Response:
    rows = db.execute(_query(f).order_by(AuditLog.id.desc()).limit(EXPORT_LIMIT)).all()
    header = ["id", "fecha_utc", "usuario", "actor", "modulo", "accion", "resultado", "ip",
              "user_agent", "duracion_ms", "detalle"]
    data = [
        [r.id, r.ts.isoformat(), e or "", r.actor, r.module, r.action, r.result, r.ip or "",
         r.user_agent or "", r.duration_ms if r.duration_ms is not None else "", str(r.detail)]
        for r, e in rows
    ]
    audit(db, request, "audit", "export", user=user, detail={"fmt": fmt, "rows": len(data)})
    db.commit()
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        for line in data:
            # Neutraliza inyección de fórmulas al abrir el CSV en una hoja de cálculo.
            writer.writerow([f"'{c}" if isinstance(c, str) and c[:1] in "=+-@" else c for c in line])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="bitacora.csv"'})
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(header)
    for line in data:
        ws.append([f"'{c}" if isinstance(c, str) and c[:1] in "=+-@" else c for c in line])
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="bitacora.xlsx"'},
    )


@router.get("/verify", response_model=VerifyOut)
def verify(_: User = Depends(require("audit", "view")), db: Session = Depends(get_db)) -> VerifyOut:
    r = verify_chain(db)
    return VerifyOut(ok=r.ok, checked=r.checked, first_broken_id=r.first_broken_id)


@router.post("/navigation", status_code=status.HTTP_204_NO_CONTENT)
def navigation(
    request: Request,
    body: NavigationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Entrada y salida de módulo reportadas por el frontend (cambio de ruta, cierre de pestaña)."""
    module = body.module if body.module in MODULES else "app"
    audit(db, request, module, f"module_{body.event}", user=user, duration_ms=body.duration_ms)
    db.commit()
