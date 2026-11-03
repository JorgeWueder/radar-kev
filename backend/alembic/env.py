from sqlalchemy import create_engine

import app.models  # noqa: F401  (registra las tablas en Base.metadata)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
