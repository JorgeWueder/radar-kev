import csv
import io
import ipaddress
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from openpyxl import Workbook
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.db.session import get_db
from app.models.auth import User
from app.models.inventory import ASSET_TYPES, ENVIRONMENTS, Asset

router = APIRouter(prefix="/assets", tags=["activos"])

AssetType = Literal["server", "workstation", "network", "database", "application", "cloud", "other"]
Environment = Literal["prod", "staging", "dev"]
HOST_PATTERN = r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$"


class AssetBase(BaseModel):
    hostname: str = Field(min_length=1, max_length=255, pattern=HOST_PATTERN)
    ip: str | None = Field(default=None, max_length=45)
    asset_type: AssetType = "server"
    os: str | None = Field(default=None, max_length=120)
    owner_id: uuid.UUID | None = None
    criticality: int = Field(default=2, ge=1, le=4)
    environment: Environment = "prod"

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return str(ipaddress.ip_address(v))
        except ValueError:
            raise ValueError("IP no válida") from None

    @field_validator("hostname")
    @classmethod
    def lower_host(cls, v: str) -> str:
        return v.lower()


class AssetCreate(AssetBase):
    pass


class AssetPatch(BaseModel):
    hostname: str | None = Field(default=None, min_length=1, max_length=255, pattern=HOST_PATTERN)
    ip: str | None = Field(default=None, max_length=45)
    asset_type: AssetType | None = None
    os: str | None = Field(default=None, max_length=120)
    owner_id: uuid.UUID | None = None
    criticality: int | None = Field(default=None, ge=1, le=4)
    environment: Environment | None = None
    is_active: bool | None = None

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, v: str | None) -> str | None:
        return AssetBase.valid_ip(v)


class AssetOut(BaseModel):
    id: uuid.UUID
    hostname: str
    ip: str | None
    asset_type: str
    os: str | None
    owner_id: uuid.UUID | None
    owner_name: str | None
    criticality: int
    environment: str
    is_active: bool
    auto_created: bool


class AssetList(BaseModel):
    items: list[AssetOut]
    total: int


def to_out(a: Asset) -> AssetOut:
    return AssetOut(
        id=a.id,
        hostname=a.hostname,
        ip=str(a.ip) if a.ip else None,
        asset_type=a.asset_type,
        os=a.os,
        owner_id=a.owner_id,
        owner_name=a.owner.full_name if a.owner else None,
        criticality=a.criticality,
        environment=a.environment,
        is_active=a.is_active,
        auto_created=a.auto_created,
    )


def _filtered(
    q: str | None, environment: str | None, criticality: int | None, asset_type: str | None
) -> Select[tuple[Asset]]:
    stmt = select(Asset)
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(or_(Asset.hostname.ilike(like), func.host(Asset.ip).ilike(like), Asset.os.ilike(like)))
    if environment in ENVIRONMENTS:
        stmt = stmt.where(Asset.environment == environment)
    if criticality:
        stmt = stmt.where(Asset.criticality == criticality)
    if asset_type in ASSET_TYPES:
        stmt = stmt.where(Asset.asset_type == asset_type)
    return stmt


@router.get("", response_model=AssetList)
def list_assets(
    q: str | None = None,
    environment: str | None = None,
    criticality: int | None = Query(None, ge=1, le=4),
    asset_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("assets", "view")),
    db: Session = Depends(get_db),
) -> AssetList:
    stmt = _filtered(q, environment, criticality, asset_type)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Asset.criticality.desc(), Asset.hostname).limit(limit).offset(offset)).scalars().all()
    return AssetList(items=[to_out(a) for a in rows], total=total)


@router.get("/export")
def export_assets(
    request: Request,
    fmt: Literal["csv", "xlsx"] = "xlsx",
    q: str | None = None,
    environment: str | None = None,
    criticality: int | None = Query(None, ge=1, le=4),
    asset_type: str | None = None,
    user: User = Depends(require("assets", "export")),
    db: Session = Depends(get_db),
) -> Response:
    rows = db.execute(_filtered(q, environment, criticality, asset_type).order_by(Asset.hostname).limit(50_000)).scalars().all()
    header = ["hostname", "ip", "tipo", "so", "dueno", "criticidad", "entorno", "activo"]
    data = [
        [a.hostname, str(a.ip) if a.ip else "", a.asset_type, a.os or "", a.owner.full_name if a.owner else "",
         a.criticality, a.environment, "si" if a.is_active else "no"]
        for a in rows
    ]
    audit(db, request, "assets", "export", user=user, detail={"fmt": fmt, "rows": len(data)})
    db.commit()

    def safe(c: object) -> object:
        # Evita inyección de fórmulas al abrir en una hoja de cálculo.
        return f"'{c}" if isinstance(c, str) and c[:1] in "=+-@" else c

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        for line in data:
            w.writerow([safe(c) for c in line])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="activos.csv"'})
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(header)
    for line in data:
        ws.append([safe(c) for c in line])
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="activos.xlsx"'})


def _get(db: Session, asset_id: uuid.UUID) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activo no encontrado")
    return a


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: uuid.UUID, _: User = Depends(require("assets", "view")), db: Session = Depends(get_db)
) -> AssetOut:
    return to_out(_get(db, asset_id))


def _check_owner(db: Session, owner_id: uuid.UUID | None) -> None:
    if owner_id is not None and db.get(User, owner_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Responsable inexistente")


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    request: Request,
    body: AssetCreate,
    actor: User = Depends(require("assets", "create")),
    db: Session = Depends(get_db),
) -> AssetOut:
    _check_owner(db, body.owner_id)
    asset = Asset(**body.model_dump())
    db.add(asset)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un activo con ese hostname en ese entorno") from None
    db.refresh(asset)
    audit(db, request, "assets", "create", user=actor, detail={"asset": str(asset.id), "hostname": asset.hostname})
    db.commit()
    return to_out(asset)


@router.patch("/{asset_id}", response_model=AssetOut)
def patch_asset(
    request: Request,
    asset_id: uuid.UUID,
    body: AssetPatch,
    actor: User = Depends(require("assets", "edit")),
    db: Session = Depends(get_db),
) -> AssetOut:
    asset = _get(db, asset_id)
    changes: dict[str, object] = {}
    data = body.model_dump(exclude_unset=True)
    if "owner_id" in data:
        _check_owner(db, data["owner_id"])
    for key, value in data.items():
        if key == "hostname" and isinstance(value, str):
            value = value.lower()
        old = getattr(asset, key)
        before = str(old) if old is not None else None
        after = str(value) if value is not None else None
        if before != after:
            changes[key] = [before, after]
        setattr(asset, key, value)
    if changes:
        asset.auto_created = False  # un analista ya revisó sus datos
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un activo con ese hostname en ese entorno") from None
    db.refresh(asset)
    audit(db, request, "assets", "edit", user=actor, detail={"asset": str(asset.id), "changes": changes})
    db.commit()
    return to_out(asset)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_asset(
    request: Request,
    asset_id: uuid.UUID,
    actor: User = Depends(require("assets", "delete")),
    db: Session = Depends(get_db),
) -> None:
    asset = _get(db, asset_id)
    asset.is_active = False  # baja lógica: se conservan sus hallazgos y su historial
    audit(db, request, "assets", "delete", user=actor, detail={"asset": str(asset.id), "hostname": asset.hostname})
    db.commit()
