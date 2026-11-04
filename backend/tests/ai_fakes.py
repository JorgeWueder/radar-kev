"""Modelos de lenguaje simulados: los tests de la capa de IA nunca llaman a un LLM real."""

from collections.abc import Iterator
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field


class FakeLLM(GenericFakeChatModel):
    """Simula salida estructurada (`structured`: cola de dicts; el último se repite) y tool calling
    (`messages`: iterador de AIMessage, con `tool_calls` para el agente)."""

    structured: list[dict[str, Any]] = Field(default_factory=list)
    calls: list[Any] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any) -> Any:
        def run(messages: Any) -> dict[str, Any]:
            self.calls.append(messages)
            data = self.structured.pop(0) if len(self.structured) > 1 else self.structured[0]
            raw = AIMessage(content="", usage_metadata={"input_tokens": 120, "output_tokens": 45, "total_tokens": 165})
            return {"raw": raw, "parsed": schema.model_validate(data), "parsing_error": None}

        return RunnableLambda(run)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeLLM":
        return self


def fake(structured: list[dict[str, Any]] | None = None, messages: list[AIMessage] | None = None) -> FakeLLM:
    it: Iterator[AIMessage] = iter(messages or [AIMessage(content="ok")])
    return FakeLLM(messages=it, structured=structured or [])


GOOD_ENRICHMENT = {
    "resumen": "CVE-2021-44228 es una falla de Log4j2 explotada activamente; afecta a srv-a.",
    "por_que_urgente": [
        "CVE-2021-44228 está en el catálogo KEV de CISA: explotación activa confirmada.",
        "El equipo srv-a tiene criticidad Crítica y EPSS de 97 %.",
        "Hay uso conocido en campañas de ransomware.",
    ],
    "pasos_remediacion": ["Aplicar el parche del proveedor según la acción requerida por CISA."],
}
