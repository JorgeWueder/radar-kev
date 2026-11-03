import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import audit, client_ip, client_ua, get_current_user, user_permissions
from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.core.security import (
    ACCESS_MINUTES,
    LOCK_MINUTES,
    MAX_FAILED_ATTEMPTS,
    REFRESH_DAYS,
    create_token,
    decode_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.db.session import get_db
from app.models.auth import RefreshToken, User

router = APIRouter(prefix="/auth", tags=["autenticación"])
COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginIn(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    permissions: list[str]
    preferences: dict[str, object]
    is_active: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class PreferencesIn(BaseModel):
    theme: str | None = Field(default=None, pattern="^(light|dark)$")
    density: str | None = Field(default=None, pattern="^(comfortable|compact)$")


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.name,
        permissions=sorted(user_permissions(user)),
        preferences=user.preferences or {},
        is_active=user.is_active,
    )


def _issue(db: Session, request: Request, response: Response, user: User) -> TokenOut:
    jti = uuid.uuid4()
    refresh = create_token(user.id, "refresh", timedelta(days=REFRESH_DAYS), jti)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=REFRESH_DAYS),
            ip=client_ip(request),
            user_agent=(client_ua(request) or "")[:300] or None,
        )
    )
    response.set_cookie(
        COOKIE,
        refresh,
        max_age=REFRESH_DAYS * 86400,
        httponly=True,
        secure=get_settings().environment == "production",
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenOut(
        access_token=create_token(user.id, "access", timedelta(minutes=ACCESS_MINUTES)),
        expires_in=ACCESS_MINUTES * 60,
        user=user_out(user),
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit("5/minute")
def login(
    request: Request, response: Response, body: LoginIn, db: Session = Depends(get_db)
) -> TokenOut:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is not None and user.locked_until and user.locked_until > now:
        audit(db, request, "auth", "login", user=user, result="denied", detail={"reason": "bloqueada"})
        db.commit()
        raise HTTPException(status.HTTP_423_LOCKED, "Cuenta bloqueada temporalmente")
    ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        detail: dict[str, object] = {"email": body.email}
        if user is not None and user.is_active:
            user.failed_attempts += 1
            if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_attempts = 0
                detail["locked"] = True
        audit(db, request, "auth", "login", user=user, result="failure", detail=detail)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    user.failed_attempts = 0
    user.locked_until = None
    out = _issue(db, request, response, user)
    audit(db, request, "auth", "login", user=user)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sin sesión")
    try:
        claims = decode_token(token, "refresh")
    except jwt.ExpiredSignatureError:
        old = decode_token(token, "refresh", verify_exp=False)
        audit(db, request, "auth", "session_expired", user=db.get(User, uuid.UUID(old["sub"])))
        db.commit()
        response.delete_cookie(COOKIE, path=COOKIE_PATH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada") from None
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida") from None
    stored = db.get(RefreshToken, uuid.UUID(claims["jti"]))
    user = db.get(User, uuid.UUID(claims["sub"]))
    if stored is None or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    if stored.revoked_at is not None:
        # Reutilización de un refresh ya rotado: posible robo; se revoca toda la familia.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        audit(db, request, "auth", "refresh_reuse_detected", user=user, result="denied")
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    stored.revoked_at = datetime.now(UTC)
    out = _issue(db, request, response, user)
    db.commit()
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(COOKIE)
    if token:
        try:
            claims = decode_token(token, "refresh", verify_exp=False)
            stored = db.get(RefreshToken, uuid.UUID(claims["jti"]))
            if stored and stored.revoked_at is None:
                stored.revoked_at = datetime.now(UTC)
            audit(db, request, "auth", "logout", user=db.get(User, uuid.UUID(claims["sub"])))
            db.commit()
        except jwt.PyJWTError:
            db.rollback()
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    out.delete_cookie(COOKIE, path=COOKIE_PATH)
    return out


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: Request,
    body: PasswordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(body.current_password, user.password_hash):
        audit(db, request, "auth", "change_password", user=user, result="failure")
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta")
    problems = validate_password(body.new_password, user.email)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems))
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = datetime.now(UTC)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit(db, request, "auth", "change_password", user=user)
    db.commit()


@router.put("/me/preferences", response_model=UserOut)
def update_preferences(
    body: PreferencesIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    prefs = dict(user.preferences or {})
    prefs.update(body.model_dump(exclude_none=True))
    user.preferences = prefs
    db.commit()
    return user_out(user)
