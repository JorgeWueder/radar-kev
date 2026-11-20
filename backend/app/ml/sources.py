"""Descarga y caché en disco de las fuentes públicas del laboratorio, con su procedencia (URL, fecha, SHA-256, licencia).

Los archivos fechados (EPSS de un día) no cambian y se guardan para siempre; los que se actualizan (NVD por año,
Exploit-DB) se vuelven a descargar si tienen más de `max_age_hours`."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT = httpx.Timeout(180.0)

LICENSES = {
    "epss": ("FIRST EPSS", "Uso libre; FIRST pide citar la fuente (first.org/epss)."),
    "kev": ("CISA KEV", "Catálogo público del gobierno de EE. UU."),
    "nvd": ("NIST NVD (feeds CVE 2.0)", "Datos públicos; «este producto usa datos del NVD pero no está respaldado ni certificado por el NVD»."),
    "exploitdb": ("Exploit-DB (OffSec)", "Repositorio bajo GPLv2; se usan solo los metadatos (CVE y fecha de alta)."),
}  # fmt: skip


class SourceError(RuntimeError):
    """Una fuente no está disponible (se informa en el trabajo y la construcción se detiene)."""


def data_dir() -> Path:
    root = Path(get_settings().ml_data_dir)
    for sub in ("raw", "datasets", "cache"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _meta(kind: str, url: str, path: Path, fetched: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    name, lic = LICENSES[kind]
    return {"kind": kind, "name": name, "license": lic, "url": url, "file": path.name, "bytes": path.stat().st_size,
            "sha256": _sha256(path), "fetched_at": fetched.isoformat(), **(extra or {})}  # fmt: skip


def download(kind: str, url: str, name: str, max_age_hours: float | None = None, missing_ok: bool = False) -> dict[str, Any] | None:
    """Descarga `url` a raw/`name` (en streaming). Devuelve la procedencia, o None si no existe (404) y `missing_ok`."""
    path = data_dir() / "raw" / name
    if path.exists():
        fetched = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if max_age_hours is None or datetime.now(UTC) - fetched < timedelta(hours=max_age_hours):
            return _meta(kind, url, path, fetched, {"cached": True})
    tmp = path.with_suffix(path.suffix + ".part")
    last: Exception | None = None
    for _ in range(3):
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c, c.stream("GET", url) as r:
                if r.status_code in (403, 404) and missing_ok:  # el bucket de EPSS responde 403 (no 404) si falta el archivo de un día
                    return None
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            tmp.replace(path)
            return _meta(kind, url, path, datetime.now(UTC), {"cached": False})
        except httpx.HTTPError as e:
            last = e
    raise SourceError(f"{LICENSES[kind][0]} no disponible: {url} ({last.__class__.__name__})")


def epss_for(day: date) -> tuple[Path, date, dict[str, Any]]:
    """CSV completo de EPSS de `day` o del día publicado más cercano antes (hasta 3 días)."""
    tpl = get_settings().epss_csv_dated_url
    for back in range(4):
        d = day - timedelta(days=back)
        meta = download("epss", tpl.format(date=d.isoformat()), f"epss_{d.isoformat()}.csv.gz", missing_ok=True)
        if meta is not None:
            return data_dir() / "raw" / str(meta["file"]), d, meta | {"date": d.isoformat()}
    raise SourceError(f"FIRST no tiene el CSV de EPSS de {day.isoformat()} ni de los 3 días anteriores")


def nvd_year(year: int) -> tuple[Path, dict[str, Any]]:
    meta = download("nvd", get_settings().nvd_feed_url.format(year=year), f"nvd_{year}.json.gz", max_age_hours=24)
    assert meta is not None
    return data_dir() / "raw" / str(meta["file"]), meta | {"year": year}


def exploitdb() -> tuple[Path, dict[str, Any]]:
    meta = download("exploitdb", get_settings().exploitdb_csv_url, "exploitdb_files_exploits.csv", max_age_hours=24)
    assert meta is not None
    return data_dir() / "raw" / str(meta["file"]), meta
