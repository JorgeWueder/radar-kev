from sqlalchemy import delete, select

from app.core.rbac import ADMIN, ANALYST, MANAGER
from app.models.auth import Permission, Role, RolePermission
from app.seed import seed_roles
from tests.conftest import isolated_schema


def codes(role: Role) -> set[str]:
    return {f"{p.module}:{p.action}" for p in role.permissions}


def test_new_module_permissions_are_granted_once_to_existing_system_roles() -> None:
    with isolated_schema() as m:
        with m() as db:  # simula una base anterior al módulo «ml»
            ml_ids = select(Permission.id).where(Permission.module == "ml")
            db.execute(delete(RolePermission).where(RolePermission.permission_id.in_(ml_ids)))
            db.execute(delete(Permission).where(Permission.module == "ml"))
            db.commit()
        with m() as db:
            seed_roles(db)
            db.commit()
        with m() as db:
            roles = {r.name: r for r in db.execute(select(Role)).scalars()}
            assert {"ml:view", "ml:create", "ml:edit"} <= codes(roles[ADMIN]) and "ml:view" in codes(roles[MANAGER])
            analyst = roles[ANALYST]
            analyst.permissions = [p for p in analyst.permissions if p.module != "ml"]  # un administrador los quita
            db.commit()
        with m() as db:
            seed_roles(db)  # siguiente arranque: no se vuelven a agregar
            db.commit()
        with m() as db:
            analyst = db.execute(select(Role).where(Role.name == ANALYST)).scalar_one()
            assert not any(p.module == "ml" for p in analyst.permissions)
