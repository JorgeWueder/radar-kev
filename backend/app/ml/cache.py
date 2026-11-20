"""Rutas de caché del laboratorio, compartidas por la API y los reportes (para que lean exactamente lo mismo)."""

import hashlib
import uuid
from collections.abc import Iterable
from pathlib import Path

from app.ml import sources

EVAL_VERSION = "v4"
EXPLAIN_VERSION = "v4"


def evaluation(dataset_id: uuid.UUID, model_ids: Iterable[uuid.UUID], op: int) -> Path:
    """La clave incluye los modelos listos y el punto de operación: entrenar otro modelo invalida la caché sola."""
    key = hashlib.sha256(("|".join(str(m) for m in model_ids) + f"|{op}|{EVAL_VERSION}").encode()).hexdigest()[:16]
    return sources.data_dir() / "cache" / f"eval_{dataset_id}_{key}.json"


def explanation(model_id: uuid.UUID) -> Path:
    return sources.data_dir() / "cache" / f"explain_{model_id}_{EXPLAIN_VERSION}.json"
