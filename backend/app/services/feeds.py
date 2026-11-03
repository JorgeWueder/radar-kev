"""Descarga de fuentes externas (CISA KEV, FIRST EPSS). El workflow de n8n hace lo mismo con sus nodos HTTP;
este módulo sirve al respaldo por CSV, a la actualización manual (`python -m app.refresh`) y a las pruebas."""

import time
from typing import Any

import httpx

from app.core.config import get_settings

EPSS_BATCH = 100
EPSS_MAX_CHARS = 1900  # la API admite como máximo 2000 caracteres en `cve`
TIMEOUT = httpx.Timeout(60.0)
RETRIES = 3


def _get(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = client.get(url, params=params)
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Fuente no disponible tras {RETRIES} intentos: {url} ({last.__class__.__name__})")


def fetch_kev() -> dict[str, Any]:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
        data: dict[str, Any] = _get(c, get_settings().kev_url).json()
        return data


def epss_batches(cves: list[str]) -> list[list[str]]:
    """Lotes de ≤100 CVEs y ≤1900 caracteres (incluidas las comas)."""
    batches: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for cve in cves:
        add = len(cve) + (1 if cur else 0)
        if cur and (len(cur) >= EPSS_BATCH or size + add > EPSS_MAX_CHARS):
            batches.append(cur)
            cur, size, add = [], 0, len(cve)
        cur.append(cve)
        size += add
    if cur:
        batches.append(cur)
    return batches


def fetch_epss(cves: list[str], pause: float = 1.0) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with httpx.Client(timeout=TIMEOUT) as c:
        for i, batch in enumerate(epss_batches(sorted(set(cves)))):
            if i:
                time.sleep(pause)  # lotes en serie con pausa: el límite de uso no está publicado
            body = _get(c, get_settings().epss_api_url, {"cve": ",".join(batch)}).json()
            items.extend(body.get("data", []))
    return items


def fetch_epss_csv() -> bytes:
    with httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True) as c:
        return _get(c, get_settings().epss_csv_url).content
