"""Lectura de los feeds anuales del NVD (CVE 2.0) registro por registro, sin cargar todo el JSON en memoria.

El feed de un año ocupa ~280 MB descomprimido; `json.load` llegaría a ~1,3 GB. Aquí se recorre el arreglo
`vulnerabilities` con `raw_decode` y se guardan solo los campos que usa el laboratorio (~1 KB por CVE)."""

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd

CVSS_KEYS = ("cvssMetricV31", "cvssMetricV30", "cvssMetricV40")
COLUMNS = ["cve", "published", "cna", "cvss", "cvss_src", "av", "ac", "pr", "ui", "scope", "conf", "integ", "avail",
           "cwe", "n_refs", "ssvc_exploitation", "ssvc_automatable", "ssvc_impact", "ssvc_ts"]  # fmt: skip


def iter_cves(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        text = f.read()
    i = text.index("[", text.index('"vulnerabilities"')) + 1
    dec = json.JSONDecoder()
    n = len(text)
    while True:
        while i < n and text[i] in " \r\n\t,":
            i += 1
        if i >= n or text[i] == "]":
            return
        obj, i = dec.raw_decode(text, i)
        yield obj["cve"]


def _cvss(metrics: dict[str, Any], cna: str | None) -> dict[str, Any]:
    """CVSS SOLO si lo puso la propia CNA que publicó el CVE (v3.1 > v3.0 > v4.0). El del NVD (Primary) y el de otros
    (p. ej. CISA ADP, Secondary) se agregan después y con más frecuencia a los CVE explotados: usarlos filtraría la
    etiqueta. Se registra quién tiene puntaje en `cvss_src` solo para auditoría (no es variable del modelo)."""
    later = False
    for key in CVSS_KEYS:
        for m in metrics.get(key, []):
            if "cvssData" not in m:
                continue
            if m.get("source") == cna:
                d = m["cvssData"]
                return {
                    "cvss": d.get("baseScore"), "cvss_src": "cna", "av": d.get("attackVector"), "ac": d.get("attackComplexity"),
                    "pr": d.get("privilegesRequired"), "ui": d.get("userInteraction"), "scope": d.get("scope"),
                    "conf": d.get("confidentialityImpact", d.get("vulnConfidentialityImpact")),
                    "integ": d.get("integrityImpact", d.get("vulnIntegrityImpact")),
                    "avail": d.get("availabilityImpact", d.get("vulnAvailabilityImpact")),
                }  # fmt: skip
            later = True
    return {"cvss": None, "cvss_src": "posterior" if later else "ninguno"}


def _ssvc(metrics: dict[str, Any]) -> dict[str, Any]:
    """Evaluación SSVC de CISA (Vulnrichment) con su fecha: solo vale para fotos posteriores a esa fecha."""
    for m in metrics.get("ssvcV203", []) + metrics.get("ssvcV202", []):
        data = m.get("ssvcData") or {}
        opts = {k: v for o in data.get("options", []) for k, v in o.items()}
        return {"ssvc_exploitation": opts.get("exploitation"), "ssvc_automatable": opts.get("automatable"),
                "ssvc_impact": opts.get("technicalImpact"), "ssvc_ts": data.get("timestamp")}  # fmt: skip
    return {}


def _cwe(c: dict[str, Any]) -> str | None:
    """CWE solo de la CNA: el del NVD se asigna al analizar, a menudo después (y antes para los CVE explotados)."""
    vals = [d["value"] for w in c.get("weaknesses", []) if w.get("source") == c.get("sourceIdentifier")
            for d in w.get("description", []) if d.get("value", "").startswith("CWE-")]  # fmt: skip
    return vals[0] if vals else None


def compact(c: dict[str, Any]) -> dict[str, Any] | None:
    if c.get("vulnStatus") == "Rejected":
        return None
    metrics = c.get("metrics", {})
    return {"cve": c["id"], "published": c.get("published", "")[:10], "cna": c.get("sourceIdentifier"),
            **_cvss(metrics, c.get("sourceIdentifier")), "cwe": _cwe(c), "n_refs": len(c.get("references", [])), **_ssvc(metrics)}  # fmt: skip


def table(paths: list[Path]) -> pd.DataFrame:
    rows = [r for p in paths for c in iter_cves(p) if (r := compact(c)) is not None]
    df = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates("cve", keep="last")
    df["published"] = pd.to_datetime(df["published"], errors="coerce").dt.date
    df["ssvc_ts"] = pd.to_datetime(df["ssvc_ts"], errors="coerce", utc=True).dt.date
    return df.reset_index(drop=True)
