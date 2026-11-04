# Workflow de n8n: Radar diario KEV/EPSS

Archivos versionados en `n8n/workflows/`:

| Archivo | Qué es |
|---|---|
| `radar_diario.json` | Flujo principal (id `RadarDiario01`), publicado: cron diario 06:00 (America/Lima) y webhook `POST /webhook/radar-manual` |
| `radar_error.json` | Flujo de errores (id `RadarError01`): ante un fallo no controlado marca la ejecución como fallida en la app |

## Importación automática (por defecto)

`docker compose up -d` ejecuta el servicio de una sola vez `n8n-import` **antes** de n8n:

1. Crea la credencial `PostgreSQL de n8n (registro propio)` a partir de variables de entorno (`n8n/import.sh`; el JSON versionado no contiene secretos).
2. Importa los dos workflows y publica `RadarDiario01`.

Después de cambiar un JSON: `docker compose up -d --force-recreate n8n-import n8n`.

## Importación manual (alternativa)

1. En n8n (http://localhost:5678) → **Credentials → Create** → tipo *Postgres*: host `postgres`, base `n8n`, usuario `n8n`, contraseña `N8N_DB_PASSWORD`. Ponle el nombre "PostgreSQL de n8n (registro propio)".
2. **Workflows → Import from file** → `radar_error.json`, luego `radar_diario.json`. En el nodo *PostgreSQL* selecciona la credencial.
3. En *Settings* del flujo principal elige `Radar: registro de errores` como *Error workflow* y **publica** el flujo.
4. n8n necesita las variables `RADAR_SERVICE_KEY`, `RADAR_API_URL`, `KEV_URL` y `EPSS_API_URL` (ya definidas en `docker-compose.yml`) y `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.

## Diseño (30 nodos)

```
Cron diario / Webhook manual (autenticado con X-Service-Key)
  → Iniciar ejecución  (si ya hubo una exitosa hoy y no es manual → "omitida")
  → HTTP KEV (reintentos 3×5 s) → Ingesta KEV
  → CVEs del inventario → Lotes EPSS (≤100 CVEs, ≤1900 caracteres) → HTTP EPSS (1 lote/s, reintentos)
        ├─ éxito → Agregar EPSS → Ingesta EPSS
        └─ error → Respaldo: CSV diario de EPSS
  → Cruce con inventario (pandas, en el backend)
  → ¿Hay nueva entrada KEV en mi entorno?
        ├─ sí → Registro propio de n8n (PostgreSQL) → Alerta urgente y tickets
        │        → (si hay tickets nuevos) Enriquecer ticket con IA, uno a uno, opcional → Bitácora: cierre
        └─ no → Bitácora: cierre
Errores de KEV (descarga o ingesta) → Fallo: registrado en la app (ejecución "Fallida" + alerta interna)
```

- **n8n no toca las tablas de la app.** Todo pasa por `/api/v1/internal/*` con `X-Service-Key` (validado y auditado en el backend). El nodo PostgreSQL escribe `radar_run_log` en la base propia de n8n.
- **Idempotencia:** `kev_matched_at` se fija una sola vez por hallazgo y `alerts`/`tickets` tienen UNIQUE por vulnerabilidad; ejecutar el flujo dos veces el mismo día no crea alertas, tickets ni correos nuevos.
- La detección es **determinista** (sin IA). El enriquecimiento de tickets con IA es un paso **opcional** posterior: si el LLM falla o no está configurado, el flujo continúa y la ejecución queda "con avisos" (tickets sin enriquecer).

## Probar a mano

```bash
curl -X POST http://localhost:5678/webhook/radar-manual \
  -H "X-Service-Key: $RADAR_SERVICE_KEY" -H "Content-Type: application/json" -d '{}'
```

Sin la clave responde `401`. El resultado aparece en la app (Ejecuciones) y los correos en Mailpit (http://localhost:8025).

> n8n 3.1 avisa de que PostgreSQL 16 "recibe soporte de compatibilidad"; el stack usa 16 por requisito del proyecto y funciona.
