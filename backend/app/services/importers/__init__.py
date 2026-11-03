from app.services.importers.common import MAX_BYTES, ImportRejected, ParseResult
from app.services.importers.csv_importer import TEMPLATE, parse_csv
from app.services.importers.nessus_importer import parse_nessus

__all__ = ["MAX_BYTES", "TEMPLATE", "ImportRejected", "ParseResult", "parse_upload"]

ALLOWED = {".csv": "csv", ".nessus": "nessus"}


def parse_upload(filename: str, data: bytes) -> ParseResult:
    """Valida tipo (extensión), tamaño y contenido real antes de interpretar el archivo."""
    name = filename.lower()
    ext = next((e for e in ALLOWED if name.endswith(e)), None)
    if ext is None:
        raise ImportRejected("Tipo de archivo no permitido: use .csv o .nessus")
    if not data:
        raise ImportRejected("El archivo está vacío")
    if len(data) > MAX_BYTES:
        raise ImportRejected(f"El archivo supera el máximo de {MAX_BYTES // (1024 * 1024)} MB")
    head = data[:512].lstrip()
    looks_xml = head.startswith(b"<?xml") or head.startswith(b"<NessusClientData_v2")
    if ext == ".nessus":
        if not looks_xml:
            raise ImportRejected("El contenido no coincide con un archivo .nessus (XML)")
        return parse_nessus(data)
    if looks_xml or head.startswith(b"<"):
        raise ImportRejected("El contenido es XML/HTML pero la extensión es .csv")
    return parse_csv(data)
