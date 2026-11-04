"""Proveedor de LLM intercambiable por .env (ollama | anthropic | openai | none). El código de negocio nunca
importa un SDK concreto: pide `get_chat_model()` y usa la interfaz común de LangChain."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings


class AIUnavailable(RuntimeError):
    """La IA está desactivada, mal configurada o no responde: el núcleo sigue funcionando sin ella."""


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model: str


_factory: Callable[[], BaseChatModel] | None = None  # los tests inyectan un modelo simulado


def set_factory(factory: Callable[[], BaseChatModel] | None) -> None:
    global _factory
    _factory = factory


def info() -> ModelInfo:
    cfg = get_settings()
    return ModelInfo(cfg.llm_provider.lower(), cfg.llm_model)


def is_configured() -> bool:
    if _factory is not None:
        return True
    cfg = get_settings()
    provider = cfg.llm_provider.lower()
    if provider == "ollama":
        return bool(cfg.ollama_base_url)
    if provider == "anthropic":
        return bool(cfg.anthropic_api_key.get_secret_value())
    if provider == "openai":
        return bool(cfg.openai_api_key.get_secret_value())
    return False


_sem: threading.BoundedSemaphore | None = None
_sem_lock = threading.Lock()
_held = threading.local()  # el hilo que ya tiene la ranura puede volver a pedirla


@contextmanager
def llm_slot() -> Iterator[None]:
    """Limita las llamadas simultáneas al modelo: una GPU local atiende de una en una; en paralelo todas se
    estorban hasta agotar el tiempo de espera. Con proveedores en la nube se permiten varias a la vez."""
    global _sem
    with _sem_lock:
        if _sem is None:
            cfg = get_settings()
            _sem = threading.BoundedSemaphore(cfg.llm_concurrency or (1 if cfg.llm_provider.lower() == "ollama" else 4))
        sem = _sem
    if getattr(_held, "depth", 0) > 0:
        yield
        return
    with sem:
        _held.depth = 1
        try:
            yield
        finally:
            _held.depth = 0


_TRANSIENT = ("ResponseError", "ConnectError", "RemoteProtocolError", "ConnectTimeout")


def call_llm(fn: Callable[[], Any]) -> Any:
    """Reintenta UNA vez ante un fallo transitorio del servidor del modelo (p. ej. un 500 de Ollama al recargar).
    Los tiempos de espera agotados no se reintentan: ya consumieron el presupuesto de la llamada."""
    for attempt in range(2):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if attempt == 0 and e.__class__.__name__ in _TRANSIENT:
                time.sleep(2)
                continue
            raise


def get_chat_model() -> BaseChatModel:
    if _factory is not None:
        return _factory()
    cfg = get_settings()
    provider = cfg.llm_provider.lower()
    kwargs: dict[str, Any]
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=cfg.llm_model, base_url=cfg.ollama_base_url, temperature=0, num_ctx=4096, num_predict=900, repeat_penalty=1.15,
            client_kwargs={"timeout": cfg.llm_timeout},
        )  # fmt: skip
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        key = cfg.anthropic_api_key.get_secret_value()
        if not key:
            raise AIUnavailable("Falta ANTHROPIC_API_KEY en la configuración")
        kwargs = {"model": cfg.llm_model, "api_key": key, "temperature": 0, "timeout": cfg.llm_timeout}
        return ChatAnthropic(**kwargs)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        key = cfg.openai_api_key.get_secret_value()
        if not key:
            raise AIUnavailable("Falta OPENAI_API_KEY en la configuración")
        return ChatOpenAI(model=cfg.llm_model, api_key=key, temperature=0, timeout=cfg.llm_timeout)
    raise AIUnavailable("La IA está desactivada (LLM_PROVIDER=none)")
