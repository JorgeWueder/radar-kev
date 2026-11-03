import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api.health import router as health_router
from app.api.v1 import audit, auth, roles, users
from app.core.config import get_settings
from app.core.ratelimit import limiter

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            # Swagger UI necesita sus propios recursos; no se le aplica la CSP estricta.
            is_docs = request.url.path.startswith(("/docs", "/redoc"))
            if key == "Content-Security-Policy" and is_docs:
                continue
            response.headers.setdefault(key, value)
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.environment != "test" and len(settings.jwt_secret.get_secret_value()) < 32:
        raise RuntimeError("JWT_SECRET debe tener al menos 32 caracteres (ver .env.example)")
    app = FastAPI(
        title="Radar de explotación activa (KEV/EPSS)",
        version="0.2.0",
        description="API del radar: cruce diario de inventario con CISA KEV y FIRST EPSS.",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, __: Exception) -> JSONResponse:
        # Nunca se filtran detalles internos; el request_id permite correlacionar con los logs.
        return JSONResponse(
            status_code=500,
            content={"error": "Error interno del servidor", "request_id": str(uuid.uuid4())},
        )

    app.include_router(health_router)
    api = APIRouter(prefix="/api/v1")
    for module in (auth, users, roles, audit):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
