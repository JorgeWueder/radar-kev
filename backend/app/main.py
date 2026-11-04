import uuid

from cryptography.fernet import Fernet
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api import internal
from app.api.health import router as health_router
from app.api.v1 import (
    ai,
    alerts,
    assets,
    audit,
    auth,
    dashboard,
    imports,
    kev,
    reports,
    roles,
    settings,
    tickets,
    users,
    vulnerabilities,
    workflow,
)
from app.core.config import Settings, get_settings
from app.core.ratelimit import limiter

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}

API_DESCRIPTION = (
    "API del **Radar de explotación activa (KEV/EPSS)**: cruce diario del inventario propio con el catálogo KEV de CISA "
    "y los scores EPSS de FIRST (NIST CSF ID.RA-1).\n\n"
    "**Autenticación:** `POST /api/v1/auth/login` devuelve un JWT; úselo con *Authorize* (esquema Bearer). Los permisos "
    "(`módulo:acción`) se validan siempre en el servidor. Los endpoints `/api/v1/internal/*` son solo para n8n y no se documentan aquí."
)
TAGS = [
    {"name": "autenticación", "description": "Inicio y cierre de sesión, refresco y perfil."},
    {"name": "usuarios", "description": "Cuentas de usuario."}, {"name": "roles", "description": "Roles y matriz de permisos."},
    {"name": "bitácora", "description": "Auditoría solo de añadir, encadenada por hash; filtros, exportación y verificación."},
    {"name": "activos", "description": "Inventario de activos."}, {"name": "importación", "description": "Importación CSV y Nessus con previsualización."},
    {"name": "vulnerabilidades", "description": "Hallazgos por activo con KEV, EPSS, score y SLA."},
    {"name": "catálogo KEV", "description": "Catálogo de CISA y su presencia en el entorno."},
    {"name": "tickets", "description": "Remediación: estados, responsables, historial."}, {"name": "alertas", "description": "Alertas urgentes y su entrega."},
    {"name": "ejecuciones", "description": "Historial del workflow de n8n y disparo manual."},
    {"name": "configuración", "description": "Fórmula del score (versionada), SLA y canales de alerta."},
    {"name": "dashboard", "description": "KPIs, tendencia y activos más expuestos."}, {"name": "reportes", "description": "Reportes en PDF, Word y Excel."},
    {"name": "IA", "description": "Asistente de consulta, enriquecimiento de tickets y resumen ejecutivo. Todo contenido generado va marcado."},
    {"name": "sistema", "description": "Salud y disponibilidad."},
]


def validate_runtime_settings(cfg: Settings) -> None:
    """Falla al arrancar, con un mensaje claro, si falta un secreto o quedó un valor de ejemplo."""
    problems: list[str] = []
    for name, value, minimum in (
        ("JWT_SECRET", cfg.jwt_secret.get_secret_value(), 32),
        ("RADAR_SERVICE_KEY", cfg.radar_service_key.get_secret_value(), 24),
        ("FERNET_KEY", cfg.fernet_key.get_secret_value(), 32),
    ):
        if len(value) < minimum or "CHANGE_ME" in value:
            problems.append(f"{name} falta, es muy corto (mínimo {minimum}) o es el valor de ejemplo")
    try:
        Fernet(cfg.fernet_key.get_secret_value().encode())
    except Exception:  # noqa: BLE001
        problems.append("FERNET_KEY no es una clave Fernet válida (base64 urlsafe de 32 bytes)")
    if problems:
        raise RuntimeError("Configuración insegura: " + "; ".join(dict.fromkeys(problems)) + ". Genere los secretos con scripts/gen-secrets.")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if get_settings().environment == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")  # solo con TLS delante
        for key, value in SECURITY_HEADERS.items():
            # Swagger UI necesita sus propios recursos; no se le aplica la CSP estricta.
            is_docs = request.url.path.startswith(("/docs", "/redoc"))
            if key == "Content-Security-Policy" and is_docs:
                continue
            response.headers.setdefault(key, value)
        return response


def create_app() -> FastAPI:
    cfg = get_settings()
    if cfg.environment != "test":
        validate_runtime_settings(cfg)
    docs_on = cfg.enable_docs_explicit or (cfg.enable_docs and cfg.environment != "production")
    app = FastAPI(
        title="Radar de explotación activa (KEV/EPSS)",
        version="1.0.0",
        description=API_DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Se omite `input`: FastAPI reenvía el valor enviado, que podría ser una contraseña o un token.
        errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, __: Exception) -> JSONResponse:
        # Nunca se filtran detalles internos; el request_id permite correlacionar con los logs.
        return JSONResponse(
            status_code=500,
            content={"error": "Error interno del servidor", "request_id": str(uuid.uuid4())},
        )

    app.include_router(health_router)
    api = APIRouter(prefix="/api/v1")
    for module in (
        auth, users, roles, audit, assets, imports, vulnerabilities, kev, settings, workflow, alerts, tickets, ai, dashboard, reports, internal,
    ):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
