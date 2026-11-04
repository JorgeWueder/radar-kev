"""Salidas estructuradas de la IA. Todo lo que se guarda en BD o en tickets pasa por estos modelos."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Short = Annotated[str, StringConstraints(max_length=320)]


class AffectedAsset(BaseModel):
    hostname: str
    criticidad: str
    entorno: str


class LLMEnrichment(BaseModel):
    """Lo único que redacta el modelo; el resto del enriquecimiento sale directamente de la base de datos."""

    resumen: Annotated[str, StringConstraints(max_length=700)] = Field(description="Qué es la vulnerabilidad, en 2 o 3 frases, citando el CVE")
    por_que_urgente: list[Short] = Field(max_length=5, description="Razones de urgencia: KEV, EPSS, criticidad del activo, ransomware")
    pasos_remediacion: list[Short] = Field(max_length=4, description="Pasos de remediación basados SOLO en la acción requerida y las referencias")


class TicketEnrichment(BaseModel):
    """Salida final guardada en el ticket: texto del modelo, ya filtrado, más datos tomados de la BD."""

    resumen: str
    por_que_urgente: list[str]
    pasos_remediacion: list[str]
    activos_afectados: list[AffectedAsset]
    referencias: list[str]
    fuentes: list[str]


class Citation(BaseModel):
    cve_id: str | None = None
    hostname: str | None = None


class AssistantAnswer(BaseModel):
    respuesta: str
    citas: list[Citation] = []
    sin_datos: bool = False
    advertencias: list[str] = []


class RiskItem(BaseModel):
    texto: Short
    cve_ids: list[str] = Field(default=[], max_length=6)
    activos: list[str] = Field(default=[], max_length=6)


class ExecutiveSummary(BaseModel):
    tendencia: Annotated[str, StringConstraints(max_length=700)] = Field(description="Cómo evoluciona la exposición, en 2 o 3 frases, con las cifras dadas")
    riesgos_principales: list[RiskItem] = Field(max_length=5, description="De 3 a 5 riesgos, cada uno con sus CVE y activos")
    recomendaciones: list[Short] = Field(max_length=5, description="Acciones concretas y priorizadas")
