import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api.health import router as health_router
from app.core.config import get_settings

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
    app = FastAPI(
        title="Radar de explotación activa (KEV/EPSS)",
        version="0.1.0",
        description="API del radar: cruce diario de inventario con CISA KEV y FIRST EPSS.",
    )
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
    return app


app = create_app()
