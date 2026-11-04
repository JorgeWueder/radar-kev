"""Referencias y descripción de un CVE desde NVD (caché de 7 días). Es opcional: si NVD no responde, el
enriquecimiento continúa solo con KEV y la base de datos."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ops import NvdCache

TTL = timedelta(days=7)
MAX_REFS = 8


def parse(payload: dict[str, Any]) -> dict[str, Any] | None:
    vulns = payload.get("vulnerabilities") or []
    if not vulns:
        return None
    cve = vulns[0].get("cve", {})
    desc = next((d.get("value", "") for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
    refs = [r["url"] for r in cve.get("references", []) if str(r.get("url", "")).startswith("http")][:MAX_REFS]
    return {"description": desc[:1200], "references": refs}


def get_cve(db: Session, cve_id: str) -> dict[str, Any] | None:
    row = db.get(NvdCache, cve_id)
    now = datetime.now(UTC)
    if row and now - row.fetched_at < TTL:
        return row.data or None
    try:
        r = httpx.get(get_settings().nvd_api_url, params={"cveId": cve_id}, timeout=15)
        r.raise_for_status()
        data = parse(r.json())
    except (httpx.HTTPError, ValueError):
        return row.data if row else None  # sin red: se usa lo último que se tenía, si existe
    if data is not None:
        if row:
            row.data, row.fetched_at = data, now
        else:
            db.add(NvdCache(cve_id=cve_id, data=data, fetched_at=now))
        db.flush()
    return data
