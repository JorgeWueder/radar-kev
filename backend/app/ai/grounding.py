"""Grounding y defensa contra prompt injection.

- Los textos de fuentes externas (KEV, NVD, nombres de activos) son DATOS: se delimitan y se neutralizan.
- Toda salida del modelo se valida contra lo recuperado de la base: un CVE, host o URL que no esté en las
  fuentes invalida la respuesta (el modelo no puede inventar CVEs, versiones ni enlaces)."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
# Nombre de host candidato: con guiones y terminado en dígitos (web-prod-01, dev-box-07).
HOST_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d{1,3}\b")
_YEAR_PART = re.compile(r"(?:^|-)(?:19|20)\d{2}(?:-|$)")  # segmento de año o fecha: no es un host
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAGS = re.compile(r"</?\s*(datos_no_confiables|contexto|system|assistant|instrucciones)[^>]*>", re.IGNORECASE)


def untrusted(source: str, text: str | None, max_len: int = 1500) -> str:
    """Envuelve texto externo como dato no confiable (sin poder cerrar el delimitador ni abrir otro)."""
    clean = _TAGS.sub("[etiqueta eliminada]", _CONTROL.sub(" ", text or "")).strip()[:max_len]
    return f'<datos_no_confiables fuente="{source}">{clean}</datos_no_confiables>'


@dataclass
class Allowed:
    """Lo que el modelo tiene permitido mencionar: únicamente lo recuperado."""

    cves: set[str] = field(default_factory=set)
    hosts: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)

    def add_cves(self, items: Iterable[str]) -> None:
        self.cves |= {c.upper() for c in items}

    def add_hosts(self, items: Iterable[str]) -> None:
        self.hosts |= {h.lower() for h in items}


def problems(text: str, allowed: Allowed) -> list[str]:
    """Devuelve las menciones no respaldadas por las fuentes (lista vacía = respuesta válida)."""
    out: list[str] = []
    for cve in sorted({m.upper() for m in CVE_RE.findall(text)} - allowed.cves):
        out.append(f"CVE no respaldado por las fuentes: {cve}")
    no_urls = URL_RE.sub(" ", text.lower())  # los identificadores dentro de URLs no son nombres de equipo
    candidates = {h for h in HOST_RE.findall(no_urls) if not _YEAR_PART.search(h) and len(h) <= 40}  # p. ej. avisos con fecha
    for host in sorted(candidates - allowed.hosts):
        out.append(f"Activo no respaldado por las fuentes: {host}")
    for url in sorted({u.rstrip(".,;") for u in URL_RE.findall(text)} - allowed.urls):
        out.append(f"URL no respaldada por las fuentes: {url[:80]}")
    return out
