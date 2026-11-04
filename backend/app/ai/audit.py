"""Registro de cada llamada a la IA: usuario, prompt, fuentes, modelo, tokens y latencia (ai_interactions)
y un evento en la bitácora de auditoría. Se registra también cuando falla."""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from app.ai import providers
from app.models.ops import AiInteraction
from app.services.audit import write_audit


class Tracker:
    def __init__(self, row: AiInteraction) -> None:
        self.row = row
        self._t0 = time.monotonic()

    def add_usage(self, message: Any) -> None:
        """Suma los tokens de un AIMessage de LangChain (usage_metadata)."""
        usage = getattr(message, "usage_metadata", None) or {}
        self.row.tokens_in = (self.row.tokens_in or 0) + int(usage.get("input_tokens", 0) or 0)
        self.row.tokens_out = (self.row.tokens_out or 0) + int(usage.get("output_tokens", 0) or 0)

    def set_output(self, output: dict[str, Any] | None, status: str = "ok", error: str | None = None) -> None:
        self.row.output = output
        self.row.status = status
        self.row.error = error

    def mark_engine(self, engine: str) -> None:
        self.row.engine = engine


@contextmanager
def tracked(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    feature: str,
    prompt: str,
    sources: dict[str, Any],
    actor: str = "user",
) -> Iterator[Tracker]:
    meta = providers.info()
    row = AiInteraction(
        user_id=user_id, feature=feature, provider=meta.provider, model=meta.model,
        prompt=prompt[:20_000], sources=sources, latency_ms=0, status="ok",
    )  # fmt: skip
    db.add(row)
    tracker = Tracker(row)
    try:
        yield tracker
    except Exception as e:  # noqa: BLE001 - se registra y se relanza
        if row.status == "ok":  # un estado ya fijado (p. ej. "ungrounded") se conserva
            row.status = "error"
            row.error = f"{e.__class__.__name__}: {e}"[:500]
        raise
    finally:
        row.latency_ms = int((time.monotonic() - tracker._t0) * 1000)
        db.flush()
        write_audit(
            db, module="ai", action=feature, result="success" if row.status == "ok" else "failure",
            user_id=user_id, actor=actor,
            detail={"interaction": str(row.id), "provider": row.provider, "model": row.model, "engine": row.engine,
                    "status": row.status, "tokens_in": row.tokens_in, "tokens_out": row.tokens_out,
                    "latency_ms": row.latency_ms},
        )  # fmt: skip
