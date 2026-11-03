import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.api.v1.auth import EMAIL_PATTERN, UserOut, user_out
from app.core.security import hash_password, validate_password
from app.db.session import get_db
from app.models.auth import Role, User

router = APIRouter(tags=["usuarios"])


class UserCreate(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(max_length=256)
    role_id: int


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role_id: int | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=256)


class UserList(BaseModel):
    items: list[UserOut]
    total: int


def _get(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return user


@router.get("/users", response_model=UserList)
def list_users(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require("users", "view")),
    db: Session = Depends(get_db),
) -> UserList:
    stmt = select(User)
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(User.created_at).limit(limit).offset(offset)).scalars().all()
    return UserList(items=[user_out(u) for u in rows], total=total)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    request: Request,
    body: UserCreate,
    actor: User = Depends(require("users", "create")),
    db: Session = Depends(get_db),
) -> UserOut:
    problems = validate_password(body.password, body.email)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems))
    if db.get(Role, body.role_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rol inexistente")
    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role_id=body.role_id,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un usuario con ese correo") from None
    db.refresh(user)
    audit(db, request, "users", "create", user=actor,
          detail={"target": str(user.id), "email": user.email, "role_id": body.role_id})
    db.commit()
    return user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    request: Request,
    user_id: uuid.UUID,
    body: UserPatch,
    actor: User = Depends(require("users", "edit")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    changes: dict[str, object] = {}
    if body.full_name is not None and body.full_name != user.full_name:
        changes["full_name"] = [user.full_name, body.full_name]
        user.full_name = body.full_name
    if body.role_id is not None and body.role_id != user.role_id:
        new_role = db.get(Role, body.role_id)
        if new_role is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rol inexistente")
        changes["role"] = [user.role.name, new_role.name]  # cambio de permisos: queda en bitácora
        user.role_id = body.role_id
        user.role = new_role
    if body.is_active is not None and body.is_active != user.is_active:
        if user.id == actor.id and not body.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puede desactivarse a sí mismo")
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active
    if body.password is not None:
        problems = validate_password(body.password, user.email)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems))
        user.password_hash = hash_password(body.password)
        user.password_changed_at = datetime.now(UTC)
        changes["password"] = "restablecida"  # noqa: S105
    audit(db, request, "users", "edit", user=actor, detail={"target": str(user.id), "changes": changes})
    db.commit()
    return user_out(user)


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    request: Request,
    user_id: uuid.UUID,
    actor: User = Depends(require("users", "edit")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get(db, user_id)
    user.locked_until = None
    user.failed_attempts = 0
    audit(db, request, "users", "unlock", user=actor, detail={"target": str(user.id)})
    db.commit()
    return user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    request: Request,
    user_id: uuid.UUID,
    actor: User = Depends(require("users", "delete")),
    db: Session = Depends(get_db),
) -> None:
    user = _get(db, user_id)
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puede desactivarse a sí mismo")
    user.is_active = False  # baja lógica: se conserva la trazabilidad de la bitácora
    audit(db, request, "users", "delete", user=actor, detail={"target": str(user.id)})
    db.commit()
