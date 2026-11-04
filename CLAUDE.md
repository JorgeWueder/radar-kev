# CLAUDE.md — Radar de explotación activa (KEV/EPSS)

Caso 08. Cruza a diario el inventario propio con CISA KEV y FIRST EPSS. Plan completo en
`C:\Users\Jorge\.claude\plans\pasted-content-id-f06a-rol-act-a-iridescent-kurzweil.md`.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, pandas (`backend/`)
- BD: PostgreSQL 16 con tres bases aisladas: `radar` (app), `n8n`, `langflow`
- Orquestación: n8n self-hosted (`n8n/workflows/*.json`)
- IA: LangChain (en el backend) + LangFlow (`langflow/flows/*.json`); proveedor por `.env` (`LLM_PROVIDER`)
- Frontend: React + Vite + TypeScript, Tailwind v4 (plugin Vite), motion, Phosphor, sonner (`frontend/`)
- UI toda en español; interfaz muestra hora en America/Lima, BD guarda UTC

## Comandos
- Levantar todo: `docker compose up -d --build` (generar `.env` antes: `sh scripts/gen-secrets.sh` o `scripts/gen-secrets.ps1`)
- Con Ollama: `docker compose --profile ollama up -d`
- Tests backend: `docker compose run --rm backend pytest`
- Lint/tipos backend: `docker compose run --rm backend sh -c "ruff check . && mypy app"`
- Migrar: `docker compose run --rm backend alembic upgrade head`; nueva: `alembic revision --autogenerate -m "msg"`
- Frontend (en `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`
- Servicios: app :8080, API :8000 (`/docs`), n8n :5678, LangFlow :7860, Mailpit :8025

## Convenciones
- Python local es 3.11: el backend se ejecuta y prueba SIEMPRE en el contenedor (3.12).
- Ningún secreto en el código; todo en `.env` (fuera de git). `.env.example` documentado.
- Permisos `módulo:acción` validados en el backend; el frontend solo oculta.
- n8n NUNCA escribe en tablas de la app: usa `/api/v1/internal/*` con `X-Service-Key`.
- Cruce, score y SLA: lógica determinista en `backend/app/services` (pandas); la IA nunca decide detección.
- La IA solo responde con datos recuperados (grounding), con salida estructurada y registro en bitácora.
- `audit_log` es solo de añadir (trigger + hash encadenado). Sin endpoints de edición/borrado.
- Antes de cerrar una fase: lint + tipos + tests + build, demostración y commit. Sin errores pendientes.
- Diseño: skills en `.claude/skills` (emil-design-eng, impeccable, design-taste-frontend). Modo "Operate": densidad legible,
  severidad con color + texto/icono, animaciones <300 ms, `prefers-reduced-motion`.
- Fuentes externas verificadas el 2026-11-03: ver sección 0 del plan (campos, límites, dominio del CSV de EPSS).

## Estado de fases
- Fases 0 (base), 1 (identidad/RBAC/bitácora), 2 (activos, importación), 3 (KEV, EPSS, cruce, score/SLA, catálogo KEV, configuración, ejecuciones) 4 (n8n, alertas, tickets, integraciones) 5 (módulo de IA) y 6 (dashboard y reportes) completas.
- Muestras para importar en `samples/` (`hallazgos_demo.csv`, `demo.nessus`); copia en `backend/tests/data/` para los tests (mantener ambas iguales).
- Importación: previsualiza (no escribe hallazgos) y luego confirma; un host desconocido crea un activo `auto_created` (criticidad Media, Producción) marcado "Por completar".
- Un FQDN del escáner se asocia al activo de nombre corto existente (y no al revés).
- Tests del backend usan un esquema PostgreSQL temporal (`tests/conftest.py::isolated_schema`); nunca tocan `public`.
- Nota de herramienta: heredocs de Bash con comillas simples/`
` fallan en este entorno; crear archivos con la herramienta Write.

## Fase 3: cruce y score
- Actualizar a mano con datos reales: `docker compose exec backend python -m app.refresh` (descarga KEV y EPSS, ingesta y cruza).
- Lógica en `backend/app/services/`: `scoring.py` (fórmula y SLA, funciones puras), `intel.py` (ingesta KEV/EPSS, config versionada),
  `correlation.py` (pandas), `feeds.py` (descargas con reintentos; lotes EPSS ≤100 CVEs y ≤1900 caracteres).
- `/api/v1/internal/*` exige `X-Service-Key` (= `RADAR_SERVICE_KEY`) y no aparece en Swagger.
- `kev_matched_at` solo se fija una vez: es la base de la idempotencia (la 2ª ejecución del día no genera "nuevas" coincidencias).
  Recalcular tras cambiar la fórmula usa `mark_matches=False` para no gastar esas coincidencias.
- EPSS/CVSS ausentes cuentan 0 en el score (no se inventan). Con los pesos por defecto todo CVE en KEV tiende a saturar en 90 a 100.
- El seed (`SEED_ON_START=true`) crea 16 activos y ~40 hallazgos reales (`app/seed_demo.py`); idempotente.

## Fase 4: n8n, alertas y tickets
- Workflow en `n8n/workflows/` (ver `n8n/README.md`). Se importa y publica solo al levantar (`n8n-import`); tras editar un JSON:
  `docker compose up -d --force-recreate n8n-import`. Los `.sh` deben tener finales de línea LF (`.gitattributes`).
- Disparo manual: `curl -X POST localhost:5678/webhook/radar-manual -H "X-Service-Key: $RADAR_SERVICE_KEY" -d '{}'` o el botón "Ejecutar ahora".
- `services/alerting.py`: alerta + ticket por coincidencia NUEVA (UNIQUE + ON CONFLICT DO NOTHING) y UN correo/webhook resumen por ejecución.
  Un canal caído no detiene al otro; el resultado queda en `alert_deliveries`.
- Resolver un ticket mitiga el hallazgo; aceptar el riesgo lo marca `accepted`; reabrir lo devuelve a `open`.
- SMTP/webhook configurables en la app (secretos cifrados con Fernet) con respaldo en `.env`. Mailpit (:8025) captura los correos en desarrollo.
- Los tests nunca envían correo real (fixture autouse `_no_real_smtp`).
- Los errores de fuentes externas se truncan al registrarlos (pueden ser páginas HTML enteras).

## Fase 5: módulo de IA
- **Proveedor por defecto: Ollama local** (`LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:3b`, servicio `ollama` + `ollama-pull` con `COMPOSE_PROFILES=ollama`).
  GPU NVIDIA: `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` (+ `COMPOSE_PATH_SEPARATOR=:` en Windows). Anthropic/OpenAI: cambiar `LLM_PROVIDER`/`LLM_MODEL` y la clave en `.env`.
- Código en `backend/app/ai/`: `providers.py` (fábrica + `llm_slot` que serializa llamadas con Ollama), `grounding.py` (datos no confiables + validación de CVE/host/URL),
  `enrichment.py` (LangFlow primero, LangChain de respaldo, `refine()` filtra lo no respaldado), `assistant.py` (7 herramientas de solo lectura con RBAC), `summary.py`, `audit.py` (tabla `ai_interactions`).
- Flow de LangFlow versionado en `langflow/flows/ticket_enrichment.json`; se carga solo (`LANGFLOW_LOAD_FLOWS_PATH`). El backend lo ejecuta por la API (`/api/v1/run/ticket-enrichment`).
  Debe fijarse `LANGFLOW_SECRET_KEY` (si cambia, se invalidan las claves de API de LangFlow) y `LANGFLOW_SSRF_ALLOWED_HOSTS=ollama`.
- Modelo pequeño: se limitan tokens (`num_predict`), se penaliza la repetición y los esquemas llevan `max_length` (evita bucles). Las herramientas del asistente normalizan argumentos sucios.
- IMPORTANTE en `.env`: no poner comentarios en la misma línea de una variable vacía (Docker Compose los toma como valor). Comentarios en línea aparte.
- Tests de IA con modelos simulados (`tests/ai_fakes.py`); el LLM real solo se usa en verificaciones manuales.

## Fase 6: dashboard y reportes
- `services/stats.py` es la fuente única de cifras (dashboard, reportes, asistente y resumen ejecutivo). `ensure_history` reconstruye el historial de
  tendencia desde `first_seen`/`resolved_at`/alta en KEV (no inventa; nunca antes del primer hallazgo ni sobre la foto de hoy).
- El cruce NO recalcula score ni SLA de hallazgos cerrados (`mitigated`, `false_positive`): así el MTTR y el cumplimiento históricos no cambian al editar la fórmula.
- Reportes en `services/reports/` (modelo común `Report` + `builders.py` + `render_pdf|docx|xlsx.py`). PDF con WeasyPrint (fuente DejaVu; Jinja2 con autoescape),
  Excel con openpyxl (formato, filtros, paneles fijos, gráfico nativo; texto externo escapado contra inyección de fórmulas), Word con python-docx.
- `POST /api/v1/reports/{tipo}?fmt=pdf|docx|xlsx&date_from&date_to&ai_summary&cve_id` (permiso `reports:export`); cada exportación queda en la bitácora.
  El resumen con IA solo aplica a los 4 de gestión y, si la IA falla, el reporte sale igual con un aviso.
