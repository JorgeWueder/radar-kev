# Fase 3 · Implementación del protocolo (Entregable 8)

Fecha: 2026-11-20. Decisiones D1 a D6 aprobadas. Esta fase **no entrenó ni reconstruyó nada con datos reales**: solo cambió
código y pruebas. No se tocó la detección, el score ni las alertas.

## Cambios de código

| Archivo | Cambio |
|---|---|
| `ml/dataset.py` | `embargoed_split` (S + N ≤ inicio del bloque siguiente; fotos que cruzan = «excluida» y no se escriben), `purge`; `build(..., embargo=True)` guarda `split_snapshots`, `events` por partición y `embargo_days`; `epss_delta` sigue midiéndose contra la foto mensual anterior aunque esté excluida |
| `ml/training.py` | `embargo_folds`, `feasible_embargo`, pliegues purgados en CV externa e interna; parada anticipada temporal del HGB (`hgb_best_iter`); poda por mediana tras cada pliegue interno; muestreador `tpe` o `random`; pliegues sin positivos se omiten y se registran (`skipped_folds`) |
| `ml/algorithms.py` | `SPACES` nuevos (≤ 4 hiperparámetros, sin `class_weight`), `FIXED`, grupo `epss_version`, enteros en escala log (`"log": true`) |
| `ml/optimize.py` | Los estudios usan los mismos pliegues purgados (`cfg.horizon`, `cfg.v_in`) |
| `ml/assess.py` | Bootstrap por clúster de CVE y por bloques de fotos, Holm, Wilcoxon (descriptivo), lift al 1 y 5 %, eventos únicos, Brier relativo |
| `ml/inference.py` | `compare_calibrators`: Platt frente a isotónica, deriva y recalibración reciente |
| `ml/experiment.py` (nuevo) | Un experimento por JSON: `python -m app.ml.experiment config.json` |
| `api/v1/ml.py` | `DatasetIn.embargo` (defecto `True`, inicio `2023-04-01`); CV 4×2 con embargo si el dataset lo tiene; 409 ante una configuración idéntica; `sampler`; `drop` con `epss_version` |
| `ml/profile.py` | Etiquetas de partición con el porcentaje real de fotos |
| Frontend (`Lab.tsx`, `Training.tsx`, `types.ts`, `LabReports.tsx`) | Inicio por defecto 2023-04, aviso del embargo, fotos excluidas y eventos únicos en el resumen |
| `README.md`, `CLAUDE.md` | Protocolo, advertencia sobre datasets heredados y comando de pruebas con código local |

Modelos y datasets ya guardados siguen funcionando (`params.get` con valores heredados; sin `params.embargo` se usa 5×3 sin embargo).

## Pruebas nuevas (`tests/test_ml_protocol.py`, 15)

Embargo (ninguna ventana cruza; reproduce 25/6/6/4 de `f2_layout.json`), error con pocas fotos, pliegues purgados (11/14/17/20 fotos),
viabilidad, entrenamiento de punta a punta con embargo, parada anticipada del HGB (y `max_iter` fijo heredado), espacios sin `class_weight`,
grupo de ablación, Holm (ejemplo de libro), límite del Wilcoxon, bootstrap por clúster, lift y Brier relativo, comparación de calibradores,
runner reproducible (mismas predicciones por SHA-256 del contenido), y el endpoint (4 pliegues, 409 en duplicado, 422 si no cabe).
Se actualizaron 2 pruebas heredadas por el cambio de espacios (`test_ml_optimize`) y 2 aserciones de `test_ml_dataset`.

## Verificación

Ver el resumen de ejecución al final del turno: `ruff check`, `mypy app`, `pytest` completo y, en frontend, `lint`, `typecheck` y `test`.

## Qué falta (Fase 4)

1. Construir el dataset nuevo (descarga ≈ 40 EPSS + NVD; 15 a 40 min estimados) y **confirmar** eventos por partición y la disponibilidad de EPSS 2023-04 en adelante.
2. Plan reducido: logística, RF y HGB, 10 pruebas, 1 semilla; luego embargo frente a sin embargo, ablaciones y horizontes.
3. `class_weight`, early-stopping HGB y espacios nuevos nunca se han ejecutado con datos reales: su efecto es desconocido hasta la Fase 4.
4. Ruido en el diff: por error corrí `ruff format` sobre `app/ml` y `api/v1/ml.py`; revertí los archivos que no tocaba (`cache`, `explain`, `jobs`, `metrics`, `profile`, `sources`, y `optimize.py` y dos tests, reaplicando solo mis cambios), pero `algorithms`, `assess`, `dataset`, `inference`, `training` y `api/v1/ml.py` quedaron reflujados: el diff de esos archivos es mayor que el cambio real.
