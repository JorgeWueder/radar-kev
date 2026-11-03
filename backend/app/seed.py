"""Siembra permisos, roles de sistema y usuarios de demostración. Idempotente."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rbac import (
    ACTIONS,
    ADMIN,
    ANALYST,
    AUDITOR,
    DEFAULT_MATRIX,
    MANAGER,
    MODULES,
    ROLE_DESCRIPTIONS,
    permission_codes,
)
from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.auth import Permission, Role, User

DEMO_USERS = [
    ("admin@radar.local", "Administrador Demo", ADMIN),
    ("analista@radar.local", "Analista Demo", ANALYST),
    ("auditor@radar.local", "Auditor Demo", AUDITOR),
    ("gerencia@radar.local", "Gerencia Demo", MANAGER),
]


def seed_roles(db: Session) -> None:
    existing = {(p.module, p.action): p for p in db.execute(select(Permission)).scalars()}
    for module in MODULES:
        for action in ACTIONS:
            if (module, action) not in existing:
                perm = Permission(module=module, action=action)
                db.add(perm)
                existing[(module, action)] = perm
    db.flush()
    for name, letters in DEFAULT_MATRIX.items():
        role = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
        if role is None:
            role = Role(name=name, description=ROLE_DESCRIPTIONS[name], is_system=True)
            role.permissions = [
                existing[tuple(code.split(":"))] for code in sorted(permission_codes(letters))  # type: ignore[index]
            ]
            db.add(role)
    db.flush()


def seed_users(db: Session, password: str) -> None:
    for email, full_name, role_name in DEMO_USERS:
        if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
            continue
        role = db.execute(select(Role).where(Role.name == role_name)).scalar_one()
        db.add(User(email=email, full_name=full_name, role_id=role.id,
                    password_hash=hash_password(password)))


def run() -> None:
    settings = get_settings()
    with get_sessionmaker()() as db:
        seed_roles(db)
        if settings.seed_on_start:
            password = settings.seed_demo_password.get_secret_value()
            if password:
                seed_users(db, password)
        db.commit()


if __name__ == "__main__":
    run()
