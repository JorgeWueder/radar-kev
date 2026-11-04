"""Cliente de la API de LangFlow. El flow `ticket_enrichment` (langflow/flows/) se ejecuta con
POST /api/v1/run/{nombre-del-endpoint}; si LangFlow falla, el backend usa la cadena LangChain equivalente."""

import json
import re
from typing import Any

import httpx

from app.core.config import get_settings


class LangflowError(RuntimeError):
    pass


def is_configured() -> bool:
    cfg = get_settings()
    return bool(cfg.langflow_url) and bool(
        cfg.langflow_api_key.get_secret_value()
        or (cfg.langflow_superuser and cfg.langflow_superuser_password.get_secret_value())
    )


_session_key: str | None = None  # clave de API creada con el usuario del sistema; vive solo en memoria


def _headers(client: httpx.Client) -> dict[str, str]:
    """La API /run exige una clave de API. Si no hay LANGFLOW_API_KEY, se inicia sesión con el superusuario del
    sistema y se crea una clave que se reutiliza mientras viva el proceso."""
    global _session_key
    cfg = get_settings()
    key = cfg.langflow_api_key.get_secret_value() or _session_key
    if key:
        return {"x-api-key": key}
    r = client.post(
        f"{cfg.langflow_url}/api/v1/login",
        data={"username": cfg.langflow_superuser, "password": cfg.langflow_superuser_password.get_secret_value()},
    )
    if r.status_code != 200:
        raise LangflowError(f"LangFlow rechazó el inicio de sesión ({r.status_code})")
    k = client.post(
        f"{cfg.langflow_url}/api/v1/api_key/", json={"name": "radar-backend"},
        headers={"Authorization": f"Bearer {r.json()['access_token']}"},
    )
    if k.status_code not in (200, 201) or "api_key" not in k.json():
        raise LangflowError(f"No se pudo crear la clave de API de LangFlow ({k.status_code})")
    _session_key = str(k.json()["api_key"])
    return {"x-api-key": _session_key}


def reset_session() -> None:
    global _session_key
    _session_key = None


def extract_text(data: Any) -> str | None:
    """Busca el texto de la salida del chat en la respuesta (la estructura anida `outputs` dos veces)."""
    if isinstance(data, dict):
        msg = data.get("message")
        if isinstance(msg, dict):
            if isinstance(msg.get("text"), str):
                return str(msg["text"])
            inner = msg.get("data")
            if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                return str(inner["text"])
        if isinstance(data.get("text"), str) and "results" not in data:
            return str(data["text"])
        for v in data.values():
            found = extract_text(v)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = extract_text(v)
            if found:
                return found
    return None


def parse_json_object(text: str) -> dict[str, Any]:
    """El modelo puede envolver el JSON en ```; se toma el primer objeto completo."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LangflowError("La respuesta del flow no contiene un objeto JSON")
    try:
        obj = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as e:
        raise LangflowError(f"JSON inválido en la respuesta del flow: {e.msg}") from None
    if not isinstance(obj, dict):
        raise LangflowError("La respuesta del flow no es un objeto JSON")
    return obj


def run_flow(input_text: str, tweaks: dict[str, Any] | None = None, timeout: float | None = None) -> str:
    cfg = get_settings()
    flow = cfg.langflow_enrich_flow
    try:
        with httpx.Client(timeout=timeout or cfg.llm_timeout + 30) as client:
            headers = _headers(client)
            r = client.post(
                f"{cfg.langflow_url}/api/v1/run/{flow}",
                params={"stream": "false"},
                headers=headers,
                json={"input_value": input_text, "input_type": "chat", "output_type": "chat", "tweaks": tweaks or {}},
            )
    except httpx.HTTPError as e:
        raise LangflowError(f"LangFlow no disponible: {e.__class__.__name__}") from None
    if r.status_code in (401, 403):
        reset_session()  # clave vencida o revocada: la próxima llamada crea otra
    if r.status_code != 200:
        raise LangflowError(f"LangFlow respondió {r.status_code}")
    text = extract_text(r.json())
    if not text:
        raise LangflowError("LangFlow no devolvió texto")
    return text
