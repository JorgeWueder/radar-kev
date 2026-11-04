from fastapi import Request
from slowapi import Limiter

from app.core.config import get_settings


def client_key(request: Request) -> str:
    """Clave del límite de uso: la IP real del cliente. Detrás de nginx, request.client es el proxy (un único cubo
    para todos los usuarios); con TRUST_PROXY_HEADERS se usa X-Forwarded-For, que nginx sobrescribe con $remote_addr."""
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "desconocido"


limiter = Limiter(key_func=client_key)
