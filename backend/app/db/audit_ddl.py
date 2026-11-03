"""DDL que vuelve inmutable audit_log. Lo usan la migración y los tests."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

AUDIT_IMMUTABLE_SQL = [
    """
    CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'audit_log es solo de anadir (UPDATE/DELETE/TRUNCATE prohibidos)';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
    """,
    """
    CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()
    """,
]


def apply_audit_immutability(conn: Connection) -> None:
    for stmt in AUDIT_IMMUTABLE_SQL:
        conn.execute(text(stmt))
