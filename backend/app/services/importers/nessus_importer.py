from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from app.services.importers.common import (
    MAX_ROWS,
    ImportRejected,
    ParseResult,
    clean_row,
    dedupe,
)


def _text(el: Element | None) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def parse_nessus(data: bytes) -> ParseResult:
    """Lee un .nessus (NessusClientData_v2). defusedxml con forbid_dtd bloquea XXE y 'billion laughs'."""
    try:
        root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise ImportRejected("El XML contiene construcciones no permitidas (DTD/entidades)") from None
    except SafeET.ParseError:
        raise ImportRejected("El archivo no es un XML válido") from None
    if root.tag != "NessusClientData_v2":
        raise ImportRejected("El XML no es un reporte Nessus v2 (.nessus)")

    result = ParseResult(source="nessus")
    n = 0
    for report in root.iter("Report"):
        for host in report.iter("ReportHost"):
            props = {t.get("name"): (t.text or "").strip() for t in host.iter("tag")}
            name = host.get("name") or ""
            hostname = props.get("host-fqdn") or props.get("hostname") or name
            ip = props.get("host-ip") or (name if name[:1].isdigit() else "")
            os_name = props.get("operating-system") or ""
            # Nessus puede listar varios SO separados por salto de línea: se conserva el primero.
            os_name = os_name.splitlines()[0] if os_name else ""
            for item in host.iter("ReportItem"):
                cves = [c.text.strip() for c in item.findall("cve") if c.text]
                if not cves:
                    continue  # hallazgos sin CVE no entran al cruce
                score = _text(item.find("cvss3_base_score")) or _text(item.find("cvss_base_score"))
                vector = _text(item.find("cvss3_vector")) or _text(item.find("cvss_vector"))
                for cve in cves:
                    n += 1
                    if n > MAX_ROWS:
                        raise ImportRejected(f"El archivo supera el máximo de {MAX_ROWS} hallazgos")
                    try:
                        result.rows.append(clean_row(hostname, ip, cve, score, vector, os_name))
                    except ValueError as e:
                        result.add_error(n, f"{name}: {e}")
    dedupe(result)
    return result
