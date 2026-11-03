import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

_hasher = PasswordHash.recommended()  # argon2id

ACCESS_MINUTES = 15
REFRESH_DAYS = 7
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 12

# Hash descartable para igualar tiempos cuando el email no existe (evita enumeración de usuarios).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    try:
        return _hasher.verify(password, password_hash)
    except Exception:
        return False


def validate_password(password: str, email: str = "") -> list[str]:
    """Devuelve la lista de incumplimientos de la política (vacía si es válida)."""
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    classes = sum(
        bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    if classes < 3:
        errors.append("Debe combinar al menos 3 de: minúsculas, mayúsculas, números y símbolos")
    local = email.split("@")[0].lower()
    if len(local) >= 3 and local in password.lower():
        errors.append("No debe contener la parte local del correo")
    return errors


def _secret() -> str:
    return get_settings().jwt_secret.get_secret_value()


def create_token(user_id: uuid.UUID, kind: str, expires: timedelta, jti: uuid.UUID | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": kind,
        "iat": now,
        "exp": now + expires,
        "jti": str(jti or uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str, kind: str, verify_exp: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = jwt.decode(
        token,
        _secret(),
        algorithms=["HS256"],
        options={"verify_exp": verify_exp, "require": ["sub", "exp", "type"]},
    )
    if payload.get("type") != kind:
        raise jwt.InvalidTokenError("tipo de token incorrecto")
    return payload
