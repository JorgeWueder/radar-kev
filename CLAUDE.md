# CLAUDE.md — Radar de explotación activa (KEV/EPSS)

Caso 08. Cruza a diario el inventario propio con CISA KEV y FIRST EPSS. Plan completo en
`C:\Users\Jorge\.claude\plans\pasted-content-id-f06a-rol-act-a-iridescent-kurzweil.md`.

## Sistema visual
- El sistema de diseño oficial del proyecto es @DESIGN.md (raíz).
- Tiene prioridad sobre cualquier otro DESIGN.md, incluido el de la skill stitch-design-taste.
- Fuente: Inter (sustituye a SF Pro). No usar colores, radios ni fuentes fuera de @DESIGN.md.

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
- Sistema visual: `DESIGN.md` (estilo Apple: Carbon/Black/Polar White, Purchase Blue solo en botones, botones e inputs en píldora, tarjetas de 28 px, sin sombras). Tokens en `frontend/src/index.css`; tipografía SF Pro con respaldo de sistema (Inter/Segoe UI), sin dependencia nueva.
- Diseño: skills en `.claude/skills` (emil-design-eng, impeccable, design-taste-frontend). Modo "Operate": densidad legible,
  severidad con color + texto/icono, animaciones <300 ms, `prefers-reduced-motion`.
- Fuentes externas verificadas el 2026-11-03: ver sección 0 del plan (campos, límites, dominio del CSV de EPSS).

## Estado de fases
- Fases 0 (base), 1 (identidad/RBAC/bitácora), 2 (activos, importación), 3 (KEV, EPSS, cruce, score/SLA, catálogo KEV, configuración, ejecuciones) 4 (n8n, alertas, tickets, integraciones) 5 (módulo de IA) 6 (dashboard y reportes) y 7 (auditoría visual, endurecimiento, README) completas.
- Muestras para importar en `samples/` (`hallazgos_demo.csv`, `demo.nessus`); copia en `backend/tests/data/` para los tests (mantener ambas iguales).
- Importación: previsualiza (no escribe hallazgos) y luego confirma; un host desconocido crea un activo `auto_created` (criticidad Media, Producción) marcado "Por completar".
- Un FQDN del escáner se asocia al activo de nombre corto existente (y no al revés).
- Tests del backend usan un esquema PostgreSQL temporal (`tests/conftest.py::isolated_schema`); nunca tocan `public`.
- Nota de herramienta: heredocs de Bash con comillas simples/`
` fallan en este entorno; crear archivos con la herramienta Write.

## Sitio público (landing)
- `/` es una página pública (`frontend/src/pages/Landing.tsx`, fragmentos de interfaz en `src/landing/Fragments.tsx`); `/login` y el panel siguen igual y `*` vuelve a `/`.
- Estructura (Layout de DESIGN.md): barra global 44 px + barra local 52 px (Carbon); portada negra con titular centrado en mayúsculas, fragmento vivo del dashboard flotando (3 ejemplos con chips) y botón azul compacto; `Highlights` (banda Carbon con baldosa de 28 px, foto B/N y métrica en Battery Green: cumplimiento de SLA, cifra de demostración); `CloseLook` (negro, chips-acordeón a la izquierda y render recortado a la derecha); luego 4 bahías (`src/landing/Bays.tsx`: frase sola, grilla de 1000 puntos con ~5 % en verde y cita pendiente en `FUENTE_CINCO_POR_CIENTO`, tiles KEV/EPSS con gauge, inventario con chips de peso), Dos CVE…Preguntas (tema de la app), `Informacion` (baldosas blancas con enlaces Link Blue) y pie Polar White. Portada, destacados y close-look viven en `src/landing/Stage.tsx`.
- Las secciones oscuras usan la clase `dark` y las claras fijas `light` (definida en `index.css`) para no depender del tema del usuario. Battery Green solo para métricas de desempeño.
- Inter (`@fontsource/inter`, 400/600) solo en el sitio público, con la clase `.landing-font`; la app sigue con SF Pro y respaldo de sistema.
- La calculadora usa `src/lib/score.ts`, réplica de `scoring.py` con los pesos por defecto: si cambia la fórmula del backend, actualizar ambos (hay test).
- Fotos de Unsplash en `frontend/public/img/*-1200.webp|*-2400.webp` (los JPG originales de 2400 px no se versionan), servidas con `src/landing/Photo.tsx` (srcset/sizes; gris + contraste salvo `servers-*` y `fiber-*`). En uso: hero-1-baborak (hero), hero-3-dittrich-bn (destacados), servers-1-tyler (inventario), fiber-1-muller (pipeline), soc-1-kostyuk (alertas); el crédito va en el pie. La foto RT-70 de `public/fotos` ya no se usa. Sin imágenes remotas (CSP `img-src 'self' data:`). Los fragmentos de interfaz usan datos de demostración. El botón "Pedir una demostración" solo aparece si se compila con `VITE_CONTACT_EMAIL`.
- Animaciones (`motion/react`): reglas en la sección Motion de `DESIGN.md`; `MotionConfig reducedMotion="user"` en la raíz de `Landing.tsx`. Con el panel del navegador oculto los reveals no corren: mostrar el panel antes de verificar capturas.

## Panel (frontend tras /login)
- Componentes compartidos en `src/components/kit.tsx` (`Meta`, `KpiCard`, `DataTable` con header fijo, `Pagination`, `DetailDrawer`, `Tabs`, `rowOpen`) y paneles de detalle en `detail.tsx` (CVE, activo, KEV, ticket). Tipos de filas en `src/lib/types.ts`.
- Regla de color: en tablas, una sola pill por fila (la del riesgo); criticidad, KEV, ransomware y estado van en `Meta` gris, y solo el SLA vencido se pone rojo.
- Sidebar agrupada (Operación, Inventario, Gestión, Administración) en `Shell.tsx`, filtrada por permisos. Los KPI del Resumen enlazan a listas filtradas por URL (`?kev=1`, `?overdue=1`, `?status=resolved`).
- Login partido con `hero-1-baborak`; el error 401 es genérico ("Correo o contraseña incorrectos"). Verificar la UI con la sesión de demostración en :8080 (reconstruir con `docker compose up -d --build frontend`).

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
- Cron `0 6-18 * * *` (Lima): lo intenta cada hora y corre una vez al día (el backend omite si ya hubo una ejecución correcta hoy, fecha UTC; por eso termina a las 18:00). n8n no recupera disparos perdidos: con un cron único a las 06:00 y el equipo apagado, el día se perdía. Tras reimportar, reiniciar n8n (`docker compose restart n8n`) para que tome el cron. n8n borra su historial de ejecuciones a los 14 días; el historial durable es `workflow_runs`.
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

## Fase 7: endurecimiento y cierre
- Límite de uso por IP real (`core/ratelimit.py::client_key`, respeta `TRUST_PROXY_HEADERS`). Solo el frontend (8080) se publica a la red; lo demás en 127.0.0.1.
- `main.py::validate_runtime_settings` impide arrancar con secretos ausentes, cortos o de ejemplo. En `ENVIRONMENT=production` se desactiva Swagger (salvo `ENABLE_DOCS_EXPLICIT=true`) y se añade HSTS.
- `n8n-import` corre DESPUÉS de que n8n esté sano (en una instalación nueva n8n registra su clave de cifrado en el primer arranque).
- Frontend: bordes de controles con `border-line-strong` (≥3:1), `pointer-coarse:` para objetivos táctiles, `rowToggle` para filas expandibles con teclado, `Dialog` accesible.
- No versionar descargas de prueba (`radar_*.pdf|docx|xlsx` están en `.gitignore`).

## Diseño
Toda la UI sigue @DESIGN.md. Usa sus tokens (colores, tipografía, espaciado, radios) y respeta sus reglas de uso. No inventes colores ni fuentes fuera de ese archivo.

## Mejoras del Promptuario (explicabilidad, inferencia, monitoreo)
- `scoring.explain_score` desglosa el score por factor (test de coincidencia con `risk_score`); `GET /vulnerabilities/{id}/explanation` y sección "Por qué este puntaje" en el panel del CVE.
- `services/inference.py` (sin SciPy): Mann-Whitney (MTTR), z de dos proporciones con Wilson (SLA) y Mann-Kendall (tendencia KEV); `GET /dashboard/comparison` y panel en el Resumen. Con pocos casos el texto lo advierte.
- Reportes: `how_to_read` en `Table`/`Chart` ("Cómo leerla") en PDF/Word/Excel; el comparativo añade la tabla "Pruebas estadísticas"; Word usa figura PNG a 600 DPI (`reports/figures.py`, matplotlib nuevo en `requirements.txt`: reconstruir la imagen del backend), el PDF mantiene SVG vectorial.
- Ejecuciones: panel de salud (éxito últimas 30, antigüedad de la última correcta, paso que más falla).
- Estadística descriptiva: `services/descriptive.py` (funciones puras con pandas + `load_frame`), `GET /dashboard/descriptive` y panel "Perfil del inventario" al final del Resumen (`components/Descriptive.tsx`). Score, EPSS (en %) y CVSS: resumen, tramos, por criticidad/entorno y KEV frente al resto, cada bloque con su lectura. Las notas comparan valores redondeados como se muestran.
- Validación de datos y grupos: `descriptive.quality` (criticidad supuesta de activos `auto_created`, faltantes de EPSS/CVSS/score, EPSS con más de 3 días, grupos con < 5 hallazgos o con ≥ 80 %, KEV frente al resto). Bloque "Calidad de los datos" sobre la estadística, con enlace para corregir cada aviso.
- Evaluación de criterios: `services/evaluation.py` y `GET /dashboard/evaluation`. CVSS, EPSS y "score sin KEV" (= `risk_score` con `in_kev=False`) frente a KEV, por CVE único: AUC (Mann-Whitney) con IC de Hanley-McNeil, curvas ROC/PR, precisión media y matrices de confusión de reglas fijas (CVSS ≥ 7/9, EPSS ≥ 10 %, banda media). El score completo NO se evalúa (incluye KEV: sería circular). Panel `components/Evaluation.tsx` al final del Resumen.
- Reportes analíticos (`services/reports/analysis.py`, grupo "Analíticos" en Reportes): `inventory_profile` y `criteria_evaluation`, sin periodo ni IA. El modelo de reporte admite varias figuras (`Report.charts`, `figures`) de tipo `line`, `bar` o `xy` (con `ref` "diagonal" o "h:<valor>"); PDF en SVG (curvas XY lado a lado), Word en PNG a 600 DPI, Excel con gráficos nativos. `Report.findings` es la lectura neutra; `notes` son avisos (en naranja).
- Prueba prospectiva de EPSS sobre todo el universo (`services/universe.py`, tabla `universe_evaluations`, migración 0006): CSV completo de EPSS de hace 30/90/180 días (`feeds.fetch_epss_csv_for`, `epss_csv_dated_url`; si falta el día, toma hasta 3 anteriores), excluye los CVE que ya estaban en KEV y mide si anticipaba los que entraron después. `GET/POST /dashboard/evaluation/universe` (POST: `workflow:create`, 5/hora, bitácora); panel `components/Universe.tsx`; reporte `epss_universe` (422 si no hay cálculo). "Cómo leerla" sale del código, no del JSON guardado. Resultado real (nov-2026, 90 días): AUC 0,60 (IC 0,50 a 0,69); el 1 % con mayor EPSS cubre el 10 % de las entradas (10 veces el azar); el 52 % entró a KEV con EPSS < 1 %. EPSS reacciona a la explotación más de lo que la anticipa: KEV manda, EPSS pondera.
- Sensibilidad de pesos (`services/sensitivity.py`, `POST /settings/scoring/sensitivity` con `settings:view`, pestaña "Sensibilidad" en Configuración, `components/Sensitivity.tsx`): N combinaciones Dirichlet reproducibles (semilla, rangos por peso, suman exactamente 1) recalculan el score con `sensitivity.scores` (réplica vectorizada de `risk_score`; hay test de paridad) y se comparan con la vigente: Spearman (Pearson de rangos, sin SciPy), coincidencia del top 10, cambios de banda y AUC del score sin KEV. Solo consulta. Con el inventario demo: 9,9/10 del top se mantiene; la prioridad la ordena KEV.
- `*.tsbuildinfo` está en `.gitignore` (caché de `tsc -b`).

## Laboratorio de modelos (experimental, Promptuario F1 a F7)
- Pedido del profesor: entrenar modelos como sugiere el Promptuario. Problema elegido: ¿qué CVE entrarán a KEV en los próximos N días? (clasificación binaria). NUNCA alimenta la detección ni el score.
- Código en `backend/app/ml/` (`sources.py` descargas con caché + SHA-256 + licencia; `nvd.py` lector del feed NVD 2.0 registro a registro con `raw_decode`, porque `json.load` de un año ≈ 1,3 GB; `dataset.py` fotos mensuales; `profile.py` F1; `jobs.py` trabajos en hilos con progreso en `ml_jobs`). API `api/v1/ml.py` (`/ml/datasets`, `/ml/jobs`), permisos `ml:*`, tablas `ml_datasets`/`ml_jobs` (migración 0007), volumen `ml_data:/data/ml` (fuera de git).
- Fuentes verificadas (19/11/2026): EPSS histórico diario (desde ≥ nov-2024), KEV (tabla `kev_entries`), NVD feeds 2.0 por año (`nvd_feed_url`), Exploit-DB `files_exploits.csv` (`date_added`). Metasploit descartado: solo trae `mod_time` (fuga).
- Sin fuga: fila = CVE aún no en KEV en la foto S; etiqueta = entra a KEV en (S, S+N]; SSVC de CISA solo si su `timestamp` ≤ S; exploits con `date_added` ≤ S; KEV previo de la CNA ≤ S; CVSS preferido el de la CNA (`cvss_src`), el del NVD puede ser posterior (se medirá con y sin CVSS). Partición TEMPORAL 70/15/15 por fotos; negativos muestreados con semilla y `weight = 1/tasa`.
- `seed_roles` da los permisos de un módulo nuevo a los roles de sistema existentes una sola vez (cuando aparece); si luego se quitan, no vuelven.
- Frontend: `/laboratorio` (`pages/Lab.tsx`, `components/lab/`), recorrido de 7 fases; F1 con resumen, validación, variables, muestra y metadata editable; `JobProgress` consulta cada 1,5 s. `Textarea` nuevo en `ui.tsx` (radio 28 px).
- Pruebas con fuentes sintéticas (`tests/test_ml_dataset.py`, `monkeypatch` de `sources.*` y `ml_data_dir` en `tmp_path`); los hilos usan la misma conexión que la petición (esquema temporal en tests).
- Fase 2 (entrenamiento): `scikit-learn` y `optuna` en `requirements.txt`. `ml/algorithms.py` (logreg, random_forest, hgb: preparación, `SPACES` con defecto/rango/descripción, `BASELINES` EPSS y CVSS), `ml/metrics.py` (PR-AUC y ROC-AUC ponderadas por `weight`, cobertura 1 %/5 %), `ml/training.py`: CV anidada TEMPORAL 5×3 en desarrollo con `forward_folds` (ventana creciente, bloque de validación fijo `n // (k+1)`: con 14 fotos, 4 iniciales y bloques de 2), Optuna TPE con semilla (la prueba 0 = hiperparámetros por defecto), reentreno con los mejores en outer_train y UNA evaluación en outer_val; luego búsqueda en todo desarrollo, modelo final y predicciones de validación y prueba (`/data/ml/models/{id}.joblib|.preds.csv.gz`). Tabla `ml_models` (migración 0008), `POST /ml/models` (`ml:create`, 12/hora, `feasible()` valida las fotos), `GET /ml/algorithms|models`. UI `components/lab/Training.tsx` (pruebas en vivo, tabla por pliegue, agregado frente a EPSS/CVSS). Con 200 000 filas un ajuste de HGB tarda ~5 s: 15 pruebas ≈ 45 a 70 min. Los tests encogen los árboles y usan 1 hilo (`small_trees`): con datos minúsculos OpenMP cuesta más de lo que ahorra.
- Ablación (`TrainIn.drop`: "cvss", "epss"; `algorithms.GROUPS`): deja CONSTANTES (0 / "desconocido") las columnas del grupo; con NaN total el binning del HGB falla ("window shape…"). Las líneas base siempre usan los datos originales.
- Fase 3 (evaluación, `ml/assess.py`; SciPy viene con scikit-learn): en PRUEBA, umbral fijado en VALIDACIÓN para revisar el 1 % o 5 % del universo; métricas, matriz de confusión (filas y estimado con pesos), curvas ROC/PR ponderadas, Friedman sobre los 5 pliegues, bootstrap pareado estratificado (300) de ΔPR-AUC y ΔROC-AUC del mejor frente a cada criterio, McNemar en el punto de operación y estabilidad por mes con la versión de EPSS. `GET /ml/datasets/{id}/evaluation?op=1|5`: si no está en caché lanza un trabajo "evaluate" y responde `{"status": "computing", "job_id"}` (tarda minutos; un request síncrono superaba el timeout del proxy). Caché en `/data/ml/cache/eval_*.json`, clave = modelos listos + op. UI `components/lab/LabEvaluation.tsx`.
- Fase 4 (explicabilidad, `ml/explain.py`, sin dependencias nuevas): equivalentes tabulares de Grad-CAM++ (atribución por OCLUSIÓN: prob(x) − prob(x con el grupo tapado por la mediana/moda de desarrollo)), mapas de atención (importancia por PERMUTACIÓN en prueba, por grupo y variable, ΔROC-AUC con todos los positivos + 8000 negativos reponderados; dependencia parcial 1D y mapa 2D de las dos numéricas más importantes) y máscaras (oclusión caso por caso: aciertos, KEV escapados, falsas alarmas). Coeficientes solo en la logística. Todo en escala original (antes de `prepare`). `GET /ml/models/{id}/explanation` con trabajo "explain" + caché `explain_{id}_v4.json`. UI `components/lab/LabExplain.tsx`.
- Fase 5 (reportes, `services/reports/lab.py`): `ml_dataset`, `ml_training`, `ml_evaluation`, `ml_explain` por `POST /reports/{tipo}` con `dataset_id`/`model_id`/`op` (exige además `ml:view`). Leen la base y las cachés del laboratorio (`ml/cache.py`, compartido con la API); si falta la evaluación o la explicación responden 422 pidiendo calcularla. No aparecen en la página Reportes (kind "laboratorio"): se exportan desde Laboratorio → 5 · Reportes (`components/lab/LabReports.tsx`). Cambios compartidos de la plantilla: el eje de los gráficos de líneas escala a los datos (antes mínimo 1, sin decimales); celdas cortas sin cortes (`td.nw`); curvas XY con `Chart.y_max` (precisión ~1 %), hasta 7 estilos de trazo y leyenda más ancha.
- Fase 6 (inferencia, `ml/inference.py`): calibración de Platt en VALIDACIÓN (Newton-Raphson ponderado propio: `LogisticRegression` sin escalar se detenía lejos del óptimo) y 200 calibraciones bootstrap estratificadas para el IC 90 % individual. Severidad por posición en el universo de validación (Crítica 1 %, Alta 5 %, Media 20 %, Baja). Verificación en prueba: O/E y pendiente con IC bootstrap que suman el error de calibrar y el azar de prueba, Brier frente a la tasa base, Hosmer-Lemeshow por tramos y tasa real por banda (Wilson). Explicación individual por oclusión como factor sobre la probabilidad calibrada y banda «sin él». API `GET /ml/models/{id}/inference|cases|ranking` y `POST /ml/models/{id}/predict` (CVE del dataset o valores a mano; `ml:view`, bitácora `model_predict`); caché `inference_{id}_v1.json` (~5 s la primera vez) y dataset/modelo en memoria (`lru_cache`). UI `components/lab/LabInference.tsx`. Resultado real: todos los modelos SOBREESTIMAN en prueba (O/E 0,5–0,8) y la banda Crítica crece (deriva entre validación y prueba); RF y HGB sin EPSS son los mejor calibrados.
- El modelo se ELIGE en validación (`best`) y se informa en prueba; `test_best` solo se muestra (elegir mirando prueba es sesgo de selección).
- Hallazgo real: el HGB completo gana la CV (PR-AUC 0,080) y la validación, pero cae en prueba (0,0017) en los tres meses, incluido jun-2026 con la versión vieja de EPSS: no se explica solo por el cambio a v2026.06.15, generaliza peor a meses nuevos. En prueba rinden más random forest (0,0178, ROC 0,914), HGB sin EPSS/sin CVSS (~0,012–0,013) y logística (0,0115); EPSS solo 0,0006. Con 24–37 positivos por mes, las cifras mensuales son ruidosas. NO reiniciar el backend mientras entrena (el trabajo queda «interrumpido»).
