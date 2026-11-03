from sqlalchemy import create_engine

from alembic import context
from app.core.config import get_settings

target_metadata = None  # se enlaza al Base.metadata de los modelos en la fase 1


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
