import ipaddress
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
MAX_STORED_ERRORS = 200

CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")


class ImportRejected(ValueError):
    """El archivo completo se rechaza (tipo, tamaño o contenido no válido)."""


@dataclass
class ParseResult:
    source: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    total_errors: int = 0

    def add_error(self, row: int, message: str) -> None:
        self.total_errors += 1
        if len(self.errors) < MAX_STORED_ERRORS:
            self.errors.append({"row": row, "error": message})


def clean_row(
    hostname: str | None,
    ip: str | None,
    cve: str | None,
    cvss: str | None,
    vector: str | None = None,
    os_name: str | None = None,
) -> dict[str, Any]:
    """Normaliza y valida una fila; lanza ValueError con un mensaje en español si es inválida."""
    host = (hostname or "").strip().lower()
    ip_s = (ip or "").strip()
    if not host and not ip_s:
        raise ValueError("falta hostname o IP")
    if not host:
        host = ip_s  # sin nombre: el activo se identifica por su IP
    if not HOST_RE.match(host):
        raise ValueError(f"hostname no válido: {host[:60]!r}")
    if ip_s:
        try:
            ip_s = str(ipaddress.ip_address(ip_s))
        except ValueError:
            raise ValueError(f"IP no válida: {ip_s[:45]!r}") from None
    cve_s = (cve or "").strip().upper()
    if not CVE_RE.match(cve_s):
        raise ValueError(f"CVE no válido: {cve_s[:30]!r}")
    score: float | None = None
    if cvss and cvss.strip():
        try:
            d = Decimal(cvss.strip().replace(",", "."))
        except InvalidOperation:
            raise ValueError(f"CVSS no numérico: {cvss[:20]!r}") from None
        if not (Decimal(0) <= d <= Decimal(10)):
            raise ValueError("CVSS fuera de rango (0 a 10)")
        score = float(d)
    return {
        "hostname": host,
        "ip": ip_s or None,
        "cve_id": cve_s,
        "cvss_score": score,
        "cvss_vector": (vector or "").strip()[:120] or None,
        "os": (os_name or "").strip()[:120] or None,
    }


def dedupe(result: ParseResult) -> None:
    """Un mismo (host, CVE) repetido en el archivo cuenta una sola vez (gana el CVSS más alto)."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for r in result.rows:
        key = (r["hostname"], r["cve_id"])
        cur = best.get(key)
        if cur is None or (r["cvss_score"] or 0) > (cur["cvss_score"] or 0):
            best[key] = r
    result.rows = list(best.values())
