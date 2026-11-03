# Radar de explotación activa (KEV/EPSS)

Cruce diario del inventario propio con el catálogo KEV de CISA y los scores EPSS de FIRST (Caso 08, NIST CSF ID.RA-1).
Estado: **Fase 0 (esqueleto)**. El README completo (credenciales semilla, importación del workflow, tests) se entrega en la fase 7.

## Requisitos
Docker Desktop (Compose v2) y Node 22+ (solo para desarrollo del frontend).

## Puesta en marcha
```bash
sh scripts/gen-secrets.sh        # Windows: powershell -File scripts/gen-secrets.ps1
docker compose up -d --build
```
App http://localhost:8080 · API http://localhost:8000/docs · n8n http://localhost:5678 · LangFlow http://localhost:7860 · Mailpit http://localhost:8025

## Tests
```bash
docker compose run --rm backend pytest
cd frontend && npm test
```
Ver `CLAUDE.md` para todos los comandos y convenciones.
