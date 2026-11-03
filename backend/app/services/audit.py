import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

GENESIS = b"\x00" * 32
ADVISORY_LOCK_KEY = 7001


def canonical(entry: dict[str, Any]) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str).encode()


def compute_hash(prev_hash: bytes, entry: dict[str, Any]) -> bytes:
    return hashlib.sha256(prev_hash + canonical(entry)).digest()


def _entry_of(row: AuditLog) -> dict[str, Any]:
    return {
        "ts": row.ts.astimezone(UTC).isoformat(),
        "user_id": str(row.user_id) if row.user_id else None,
        "actor": row.actor,
        "module": row.module,
        "action": row.action,
        "result": row.result,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "duration_ms": row.duration_ms,
        "detail": row.detail,
    }


def write_audit(
    db: Session,
    *,
    module: str,
    action: str,
    result: str = "success",
    user_id: Any = None,
    actor: str = "user",
    ip: str | None = None,
    user_agent: str | None = None,
    duration_ms: int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Añade un eslabón a la cadena; el lock serializa las escrituras para que prev_hash sea coherente."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
    last = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
    prev = last if last is not None else GENESIS
    row = AuditLog(
        ts=datetime.now(UTC),
        user_id=user_id,
        actor=actor,
        module=module,
        action=action,
        result=result,
        ip=ip,
        user_agent=(user_agent or "")[:300] or None,
        duration_ms=duration_ms,
        detail=detail or {},
        prev_hash=prev,
        hash=b"",
    )
    row.hash = compute_hash(prev, _entry_of(row))
    db.add(row)
    db.flush()
    return row


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    first_broken_id: int | None


def verify_chain(db: Session) -> VerifyResult:
    prev = GENESIS
    checked = 0
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        expected = compute_hash(prev, _entry_of(row))
        if row.prev_hash != prev or row.hash != expected:
            return VerifyResult(False, checked, row.id)
        prev = row.hash
        checked += 1
    return VerifyResult(True, checked, None)
