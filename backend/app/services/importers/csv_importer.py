import csv
import io

from app.services.importers.common import (
    MAX_ROWS,
    ImportRejected,
    ParseResult,
    clean_row,
    dedupe,
)

ALIASES = {
    "hostname": {"hostname", "host", "asset", "activo", "nombre"},
    "ip": {"ip", "ip_address", "direccion_ip", "address"},
    "cve": {"cve", "cve_id", "cveid"},
    "cvss": {"cvss", "cvss_score", "cvss_base_score", "score"},
    "vector": {"cvss_vector", "vector"},
    "os": {"os", "operating_system", "sistema_operativo"},
}

TEMPLATE = (
    "hostname,ip,cve,cvss,os\n"
    "web-prod-01,10.10.1.21,CVE-2021-44228,10.0,Ubuntu 22.04\n"
    "db-prod-01,10.10.2.15,CVE-2022-0778,7.5,RHEL 8\n"
)


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in fieldnames:
        low = name.strip().lower().lstrip("﻿")
        for canonical, names in ALIASES.items():
            if low in names and canonical not in mapping:
                mapping[canonical] = name
    return mapping


def _get(raw: dict[str, str], mapping: dict[str, str], key: str) -> str | None:
    return raw.get(mapping[key]) if key in mapping else None


def parse_csv(data: bytes) -> ParseResult:
    if b"\x00" in data:
        raise ImportRejected("El archivo no es un CSV de texto")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError:
            raise ImportRejected("Codificación no reconocida (use UTF-8)") from None
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ImportRejected("El CSV no tiene encabezados")
    mapping = _map_headers(list(reader.fieldnames))
    if "cve" not in mapping or not ({"hostname", "ip"} & mapping.keys()):
        raise ImportRejected(
            "Faltan columnas obligatorias: se requiere 'cve' y 'hostname' (o 'ip'). "
            "Descargue la plantilla desde la pantalla de importación."
        )
    result = ParseResult(source="csv")
    for i, raw in enumerate(reader, start=2):  # la fila 1 es el encabezado
        if len(result.rows) + result.total_errors >= MAX_ROWS:
            raise ImportRejected(f"El archivo supera el máximo de {MAX_ROWS} filas")
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue  # fila vacía
        try:
            result.rows.append(
                clean_row(*(_get(raw, mapping, k) for k in ("hostname", "ip", "cve", "cvss", "vector", "os")))
            )
        except ValueError as e:
            result.add_error(i, str(e))
    dedupe(result)
    return result
