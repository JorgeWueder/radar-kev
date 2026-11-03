from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.core.rbac import ADMIN, all_permission_codes
from app.db.session import get_db
from app.models.auth import Permission, Role, User

router = APIRouter(tags=["roles"])


class RoleOut(BaseModel):
    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    description: str = Field(default="", max_length=255)
    permissions: list[str] = []


class PermissionsIn(BaseModel):
    permissions: list[str]


class PermissionCatalog(BaseModel):
    modules: list[str]
    actions: list[str]


def _out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=sorted(f"{p.module}:{p.action}" for p in role.permissions),
    )


def _resolve(db: Session, codes: list[str]) -> list[Permission]:
    valid = all_permission_codes()
    unknown = sorted(set(codes) - valid)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Permisos desconocidos: {unknown}")
    perms = db.execute(select(Permission)).scalars().all()
    wanted = set(codes)
    return [p for p in perms if f"{p.module}:{p.action}" in wanted]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    _: User = Depends(require("roles", "view")), db: Session = Depends(get_db)
) -> list[RoleOut]:
    return [_out(r) for r in db.execute(select(Role).order_by(Role.id)).scalars().all()]


@router.get("/permissions", response_model=PermissionCatalog)
def permission_catalog(_: User = Depends(require("roles", "view"))) -> PermissionCatalog:
    from app.core.rbac import ACTIONS, MODULES

    return PermissionCatalog(modules=MODULES, actions=ACTIONS)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    request: Request,
    body: RoleCreate,
    actor: User = Depends(require("roles", "create")),
    db: Session = Depends(get_db),
) -> RoleOut:
    role = Role(name=body.name, description=body.description, is_system=False)
    role.permissions = _resolve(db, body.permissions)
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un rol con ese nombre") from None
    audit(db, request, "roles", "create", user=actor,
          detail={"role": role.name, "permissions": sorted(body.permissions)})
    db.commit()
    return _out(role)


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
def set_permissions(
    request: Request,
    role_id: int,
    body: PermissionsIn,
    actor: User = Depends(require("roles", "edit")),
    db: Session = Depends(get_db),
) -> RoleOut:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rol no encontrado")
    if role.name == ADMIN:
        # Evita que un error de configuración deje el sistema sin administración.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Los permisos del Administrador no se editan")
    before = {f"{p.module}:{p.action}" for p in role.permissions}
    role.permissions = _resolve(db, body.permissions)
    after = set(body.permissions)
    audit(db, request, "roles", "edit_permissions", user=actor,
          detail={"role": role.name, "added": sorted(after - before), "removed": sorted(before - after)})
    db.commit()
    return _out(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    request: Request,
    role_id: int,
    actor: User = Depends(require("roles", "delete")),
    db: Session = Depends(get_db),
) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rol no encontrado")
    if role.is_system:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Los roles de sistema no se eliminan")
    if db.execute(select(User.id).where(User.role_id == role.id).limit(1)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "El rol tiene usuarios asignados")
    name = role.name
    db.delete(role)
    audit(db, request, "roles", "delete", user=actor, detail={"role": name})
    db.commit()
