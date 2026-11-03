import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.auth import User
from app.services.audit import write_audit


def client_ip(request: Request) -> str | None:
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def client_ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


def audit(
    db: Session,
    request: Request,
    module: str,
    action: str,
    *,
    user: User | None = None,
    result: str = "success",
    detail: dict[str, object] | None = None,
    duration_ms: int | None = None,
) -> None:
    write_audit(
        db,
        module=module,
        action=action,
        result=result,
        user_id=user.id if user else None,
        ip=client_ip(request),
        user_agent=client_ua(request),
        duration_ms=duration_ms,
        detail=detail,
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized
    try:
        payload = decode_token(token, "access")
    except jwt.ExpiredSignatureError:
        # Sesión expirada: se registra a quién pertenecía el token (la firma sí se verificó).
        try:
            claims = decode_token(token, "access", verify_exp=False)
            audit(db, request, "auth", "session_expired", user=db.get(User, uuid.UUID(claims["sub"])))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada") from None
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user


def user_permissions(user: User) -> set[str]:
    return {f"{p.module}:{p.action}" for p in user.role.permissions}


def require(module: str, action: str) -> Callable[..., User]:
    """Dependencia RBAC: la validación real ocurre en el backend; el frontend solo oculta."""
    code = f"{module}:{action}"

    def checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if code not in user_permissions(user):
            audit(db, request, module, "access_denied", user=user, result="denied",
                  detail={"permission": code, "path": request.url.path})
            db.commit()
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tiene permiso para esta acción")
        return user

    return checker
