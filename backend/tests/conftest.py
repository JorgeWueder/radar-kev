import os

# Debe fijarse antes de importar la app.
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123456"
os.environ["TRUST_PROXY_HEADERS"] = "false"

import uuid  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db.audit_ddl import apply_audit_immutability  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_roles, seed_users  # noqa: E402

PASSWORD = "Radar-Demo-2026!"


@contextmanager
def isolated_schema() -> Iterator[sessionmaker[Session]]:
    """Esquema PostgreSQL temporal con tablas, trigger y datos semilla (no toca el esquema public)."""
    name = f"t_{uuid.uuid4().hex[:10]}"
    url = get_settings().database_url
    admin = create_engine(url)
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {name}"))
    engine = create_engine(url, connect_args={"options": f"-c search_path={name},public"})
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as c:
            apply_audit_immutability(c)
        maker = sessionmaker(bind=engine, expire_on_commit=False)
        with maker() as s:
            seed_roles(s)
            seed_users(s, PASSWORD)
            s.commit()
        yield maker
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA {name} CASCADE"))
        admin.dispose()


def client_for(maker: sessionmaker[Session]) -> TestClient:
    def override() -> Iterator[Session]:
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = override
    return TestClient(app)


@pytest.fixture(scope="session")
def maker() -> Iterator[sessionmaker[Session]]:
    with isolated_schema() as m:
        yield m


@pytest.fixture
def client(maker: sessionmaker[Session]) -> Iterator[TestClient]:
    limiter.enabled = False
    limiter.reset()
    yield client_for(maker)
    app.dependency_overrides.clear()


def login(c: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
