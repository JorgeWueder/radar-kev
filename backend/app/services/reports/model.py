"""Modelo común de reporte: los constructores producen un Report y los renderizadores lo dibujan en PDF, Word o Excel."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


class ReportError(ValueError):
    """Parámetros inválidos o datos inexistentes (se informa al usuario con un 4xx)."""


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[Any]]
    note: str = ""
    how_to_read: str = ""  # interpretación en lenguaje llano de la tabla
    right: set[int] = field(default_factory=set)  # columnas numéricas (alineadas a la derecha)


@dataclass
class Chart:
    """`line`: series sobre etiquetas (fechas). `bar`: una serie de conteos por etiqueta (tramos).
    `xy`: curvas con puntos (x, y) en [0, 1] (ROC y precisión-cobertura); `ref` dibuja la referencia:
    "diagonal" (azar) o "h:<valor>" (línea base horizontal)."""

    title: str
    labels: list[str]
    series: list[tuple[str, list[float]]]
    how_to_read: str = ""
    kind: str = "line"
    xy: list[tuple[str, list[tuple[float, float]]]] = field(default_factory=list)
    x_label: str = ""
    y_label: str = ""
    ref: str = ""
    y_max: float | None = None  # tope del eje vertical en curvas XY (p. ej. precisión de ~1 %); por defecto 1

    @property
    def empty(self) -> bool:
        return not (self.xy if self.kind == "xy" else self.labels)


@dataclass
class Report:
    key: str
    title: str
    subtitle: str
    generated_at: datetime
    kpis: list[tuple[str, str]] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    chart: Chart | None = None
    charts: list[Chart] = field(default_factory=list)  # figuras adicionales (además de `chart`)
    ai: dict[str, Any] | None = None  # resumen ejecutivo generado por IA (marcado como tal en todos los formatos)
    notes: list[str] = field(default_factory=list)  # avisos (se dibujan resaltados)
    findings: list[str] = field(default_factory=list)  # lectura de los resultados (texto neutro)

    @property
    def figures(self) -> list[Chart]:
        return [c for c in ([self.chart] if self.chart else []) + self.charts if not c.empty]

    @property
    def wide(self) -> bool:
        return any(len(t.columns) > 7 for t in self.tables)


def fmt_date(d: Any) -> str:
    return d.strftime("%d/%m/%Y") if d is not None else "—"


def fmt_num(v: float | None, digits: int = 1, suffix: str = "") -> str:
    return "—" if v is None else f"{v:,.{digits}f}".replace(",", " ").replace(".", ",") + suffix


BAND = {"critical": "Crítico", "high": "Alto", "medium": "Medio", "low": "Bajo"}
SLA = {"vencido": "Vencido", "por_vencer": "Por vencer", "en_plazo": "En plazo", "no_aplica": "No aplica"}
CRIT = {1: "Baja", 2: "Media", 3: "Alta", 4: "Crítica"}
PRIORITY = {"critical": "Crítica", "high": "Alta", "medium": "Media", "low": "Baja"}
TICKET = {"open": "Abierto", "in_progress": "En remediación", "resolved": "Resuelto", "closed": "Cerrado", "risk_accepted": "Riesgo aceptado"}


def risk_suffix(texto: str, cve_ids: list[str]) -> str:
    """CVE de un riesgo que el texto aún no menciona (evita repetirlos entre paréntesis)."""
    extra = [c for c in cve_ids if c.upper() not in texto.upper()]
    return f" ({', '.join(extra)})" if extra else ""
