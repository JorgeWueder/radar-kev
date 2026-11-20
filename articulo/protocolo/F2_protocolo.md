# Fase 2 · Protocolo de entrenamiento, validación y optimización (Entregables 2 a 7)

Fecha: 2026-11-20. Pregunta: ¿qué CVE que hoy no están en KEV entrarán al catálogo en los próximos N = 90 días?
Este documento es un **diseño** (nada de lo que sigue se ha ejecutado salvo lo marcado «medido»). Los parámetros que
no se pueden fijar con la evidencia actual se declaran como *provisionales* con lo que hace falta para confirmarlos.
Resultados de apoyo: `resultados/f2_layout.json` (script `scripts/f2_layout.py`) y `resultados/f1_*.json`.

## 0. Decisiones que necesito de ti (con mi propuesta por defecto)

| # | Decisión | Propuesta | Alternativa |
|---|---|---|---|
| D1 | Construir un dataset nuevo desde **2023-04** (41 fotos) | Sí | Desde 2024-01 (32 fotos): CV anidada casi inviable (ver §3) |
| D2 | CV anidada reducida a **4 externos × 2 internos** (bloques de 3 y 2 fotos) | Sí | 5×3 original: no cabe con embargo |
| D3 | Quitar `class_weight="balanced"` de los tres espacios (doble corrección con el peso de muestreo) | Sí | Mantenerlo como candidato |
| D4 | `epss_model` y `epss_delta` fuera del conjunto principal; solo `percentile` y `epss` | Sí, con ablación «sin versión EPSS» | Mantener todo |
| D5 | Umbrales de utilidad práctica (§7.4) fijados **antes** de ver la prueba | Los de §7.4 | Otros |
| D6 | Almacenamiento de Optuna en archivo SQLite del volumen `ml_data` | Sí | Esquema en PostgreSQL |

## 1. Técnicas de entrenamiento: seleccionadas y descartadas (Entregable 2)

| Técnica | Decisión | Justificación (datos y costo) |
|---|---|---|
| Supervisado sobre fotos mensuales, **ventana expansiva** | Principal | Usa todo el pasado disponible; con ≈ 15 a 25 eventos por pliegue una ventana corta perdería positivos |
| **Ventana deslizante** (últimas 18 fotos) | Complementaria | Mide si los datos viejos (EPSS v2023) dañan; no principal por falta de eventos |
| Desbalance por **muestreo de negativos 5 % con peso 1/tasa** (ya existe) | Se mantiene | La prevalencia real es 0,006 a 0,016 %; sin muestreo hay ≈ 270 000 filas por foto. Los pesos conservan la prevalencia en PR-AUC |
| `class_weight="balanced"` encima del peso | **Descartado** (D3) | Corrige el desbalance dos veces; sesga probabilidades (auditoría §4d). Se conserva como análisis de sensibilidad único |
| Horizontes 30, 60, 90, 180 | 90 principal; 30 y 180 como sensibilidad (60 solo si sobra tiempo) | Cada horizonte exige su propio dataset y su propio embargo (N); a 180 días se pierden más fotos |
| Ablación EPSS / CVSS | Se mantiene; **grupo nuevo «versión EPSS»** (`epss_model`, `epss_delta`) | La versión cambia entre dev y prueba (auditoría §4b) |
| Reentrenamiento periódico + recalibración | Se evalúa **solo la recalibración** con datos recientes (Platt sobre la última porción de validación) | Barato; el reentrenamiento mensual completo multiplica el costo y no cabe en el plazo |
| Épocas, learning-rate scheduling, early stopping de redes | **No aplican** | Son modelos de scikit-learn (convexos o por árboles), no redes entrenadas por épocas; la única «época» es `max_iter`/`n_estimators` |
| Transfer learning, aumento de datos, SMOTE | **No aplican / descartado** | No hay modelo preentrenado para este problema. SMOTE sintetizaría CVE con variables categóricas (CWE, CNA) sin sentido y rompería el orden temporal |
| XGBoost / LightGBM / CatBoost | No se agregan | HGB ya es la misma familia (histogramas); solo se justificaría con evidencia de mejora, que no existe |

## 2. Diseño de los datos y variables

- Unidad: CVE × foto mensual (sin cambio). Etiqueta: entra a KEV en (S, S+90].
- Variables: las 14 actuales, con D4 aplicado al conjunto principal.
- Nuevo: columna `event_id = cve` y `event_date = kev_date` para agrupar por evento en el bootstrap.
- Disponibilidad medida: el CSV de EPSS responde 200 para 2023-06, 2024-01, 2024-03, 2024-06, 2024-09, 2024-10 y 2024-11 (el 2024-12-01 da 403 y
  el sistema cae al 2024-12-02). **Sin verificar** 2023-04, 2023-05 y el resto de meses: lo confirma el constructor al descargarlos.
- Volumen esperado (orden de magnitud, de `kev_entries`): 468 altas en KEV entre 2023-Q2 y 2025-Q2 (dev), ≈ 190 en
  2025-Q3 a 2026-Q1 (val) y ≈ 250 desde 2026-Q1 (prueba), antes de excluir las que no están en EPSS. Hoy hay 193, 55 y 57 eventos.
  Se confirma al construir.

## 3. Partición 70/15/15 con embargo (Entregable 3)

Regla: una foto S pertenece a un bloque solo si S + N ≤ inicio del bloque siguiente; las fotos que no cumplen se **excluyen**
de todos los conjuntos (su etiqueta mira dentro del bloque siguiente). Proporciones sobre las fotos que quedan.

| Inicio del dataset | Fotos | Desarrollo | Validación | Prueba | Excluidas por embargo | % (dev/val/test) |
|---|---|---|---|---|---|---|
| 2025-01 (actual) | 20 | 10 (2025-01 a 10) | 3 | 3 | 4 | 62,5 / 18,8 / 18,8 |
| 2024-01 | 32 | 18 | 5 | 5 | 4 | 64,3 / 17,9 / 17,9 |
| **2023-04 (propuesto)** | **41** | **25 (2023-04 a 2025-04)** | **6 (2025-07 a 12)** | **6 (2026-03 a 08)** | **4** | **67,6 / 16,2 / 16,2** |

(Medido en `f2_layout.json`. El 70/15/15 exacto es imposible con embargo; la desviación se declara en el artículo.)

```
fotos   2023-04 ───────────────── 2025-04 │▒▒│ 2025-07 ──── 2025-12 │▒▒│ 2026-03 ──── 2026-08
bloque  ████████ DESARROLLO (25) ████████ │ E │ ██ VALIDACIÓN (6) ██ │ E │ ███ PRUEBA (6) ███
ventana cada foto S mira (S, S+90]; 2025-05 y 2025-06 (cuyas ventanas llegan a 2025-07) y 2026-01 y 2026-02 (llegan a 2026-03)
        quedan fuera: E = 2 fotos excluidas por frontera
```

Efecto de la prueba sobre la elección: la prueba solo se evalúa **una vez**, con el modelo y el umbral fijados en validación.
Positivos: se informa por bloque filas, **eventos únicos** y fotos; si la prueba tiene < 30 eventos o la validación < 30 se advierte.

Cuestión de deriva (medida): con este diseño el desarrollo es casi todo EPSS v2023.03.01 (24 de 25 fotos) mientras validación y
prueba son v2025.03.14 y v2026.06.15 (desde 2026-07). Un modelo entrenado sobre la escala v3 se aplica a escalas distintas. Por eso D4 (preferir
`percentile`) y la ablación «sin versión EPSS» son parte obligatoria del protocolo. **No se puede cuantificar de antemano**; se reporta como limitación
principal si el resultado depende de `epss`.

## 4. Validación cruzada temporal anidada (Entregable 5)

| Parámetro | Configuración | Justificación |
|---|---|---|
| Pliegues externos | **4**, bloques de **3 fotos**, ventana expansiva | Con 25 fotos de desarrollo y embargo, 5×3 deja el primer pliegue sin historia (medido para 20 y 32 fotos); (4,3,2,2) es viable en los 4 pliegues con 25 fotos |
| Pliegues internos | **2**, bloques de **2 fotos**, mínimo 3 fotos de entrenamiento | Mínimo para un Optuna con señal; más pliegues quitan fotos de entrenamiento |
| Embargo | En cada pliegue (externo e interno): se excluyen las fotos con S + 90 > inicio del bloque de validación | Evita la fuga (a) de la auditoría |
| Ventana | Expansiva (principal); deslizante de 12 fotos (complementaria) | |
| Criterio | PR-AUC ponderada por pliegue; se informan también recall al 1 % y 5 % y log-loss ponderado | |
| Pliegues sin positivos | Se excluyen y se registran (conteo y motivo); un pliegue con < 5 eventos se marca «poco fiable» | |
| Aclaración | La CV vive **dentro de desarrollo**; la validación (15 %) elige algoritmo, umbral y calibración; la prueba se usa una vez | |

Pliegues externos (embargados, `f2_layout.json`): validan 2024-05 a 07, 2024-08 a 10, 2024-11 a 2025-01 y 2025-02 a 04, con 11, 14, 17 y 20 fotos de
entrenamiento tras el embargo (ya purgadas).

Alternativa evaluada y descartada: CV no anidada con un solo nivel purgado. Se justificaría solo si el costo no cabe; la validación independiente ya da una
estimación no sesgada de la elección, y la CV anidada se usa para estimar la variabilidad del procedimiento de ajuste.

## 5. Fichas técnicas por modelo (Entregable 4)

Convenciones: *inicial* = valor de la prueba 0 de Optuna (enqueued); *rango* = espacio de búsqueda; las razones de los rangos citan lo observado
(estudios de la Fase 7: logística con `class_weight=none` explicaba el 90 % de la varianza; en HGB pesan `learning_rate` y `min_samples_leaf`).
Todos los rangos son **provisionales** hasta ver avisos de borde y fANOVA con el dataset nuevo.

### 5.1 Regresión logística (L2)

Función: modelo lineal interpretable y línea base entrenada; con ≈ 400 eventos de desarrollo es el que mejor se sostiene con pocos datos.
Preparación: log(x+c) para `epss`, `days_published`, `edb_exploits`, `cna_kev_prior`; mediana + indicador de faltante; estandarizar; one-hot con categorías raras
(< 20 filas) agrupadas en «otras» (ya implementado).

| Parámetro | Inicial | Rango | Escala | Justificación |
|---|---|---|---|---|
| `C` | 0,01 | 1e-4 a 1 | log | El estudio previo terminó en el borde inferior (C = 0,0012); ampliar hacia arriba (hasta 10) empeoró en validación y prueba. Rango estrecho |
| `class_weight` | `none` (fijo) | — | — | D3; el muestreo con pesos ya corrige el desbalance |

Parada: `lbfgs`, `max_iter = 3000`, `tol = 1e-4`; se registra `n_iter_` y se marca la prueba si no converge. Pruebas Optuna: 20.
Candidato adicional justificado: **logística parsimoniosa** (`percentile`, `cvss`, `edb_exploits`, `days_published`, `cna_kev_prior`), porque 5 variables
caben en la regla de 10 a 20 eventos por parámetro con holgura.

### 5.2 Random forest

Función: capta interacciones sin escalar; el promedio de árboles es estable con pocos positivos.
Preparación: igual que la logística (one-hot; con árboles el log no cambia nada).

| Parámetro | Inicial | Rango | Escala | Justificación |
|---|---|---|---|---|
| `n_estimators` | 300 (fijo) | — | — | Más árboles no sobreajustan; fijarlo reduce dimensiones. Se verifica la estabilidad del OOB/PR-AUC entre 300 y 600 en una sola prueba |
| `max_depth` | 8 | 3 a 16 | lineal | Con ≈ 400 eventos, árboles profundos memorizan; el previo eligió 10 |
| `min_samples_leaf` | 30 | 5 a 200 | log | El previo eligió 34; hojas pequeñas dan probabilidades ruidosas |
| `max_features` | `sqrt` | {`sqrt`, 0,3} | cat | 0,5 se elimina (coste sin evidencia de mejora previa) |
| `class_weight` | `none` (fijo) | — | — | D3 |

Parada: sin iteraciones; la «condición de parada» es el número de árboles (fijo) y `min_samples_leaf`. Pruebas Optuna: 25.

### 5.3 Gradient boosting con histogramas

Función: modelo no lineal más flexible; el que más se sobreajustó (CV 0,080 frente a prueba 0,0017 en la versión previa).
Preparación: categorías ordinales nativas, `NaN` admitidos, categorías raras agrupadas (ya implementado).

| Parámetro | Inicial | Rango | Escala | Justificación |
|---|---|---|---|---|
| `learning_rate` | 0,05 | 0,01 a 0,2 | log | El previo cubría hasta 0,3; tasas altas con pocos eventos sobreajustan |
| `max_iter` | por parada anticipada | tope 500 | — | Ver abajo; no se optimiza |
| `max_leaf_nodes` | 15 | 4 a 31 | lineal | Árboles pequeños: pocos eventos |
| `min_samples_leaf` | 100 | 20 a 500 | log | Fue de los dos parámetros importantes; se amplía hacia arriba |
| `l2_regularization` | 0,1 | 1e-3 a 10 | log | El estudio previo la dejó en el borde alto |
| `class_weight` | `none` (fijo) | — | — | D3 |

Parada anticipada (a implementar): el `early_stopping` interno de scikit-learn usa una **fracción aleatoria**, que mezcla fotos y reintroduce fuga temporal,
así que se hace propio: se ajusta con `max_iter = 500`, se evalúa con `staged_predict_proba` la log-loss ponderada sobre la **última fracción temporal de
entrenamiento** (las últimas 20 % fotos del entrenamiento, tras el embargo), `n_iter_no_change = 20`, `tol = 1e-4`; se toma el mejor número de iteraciones
y se reajusta con ese valor sobre todo el entrenamiento. Pruebas Optuna: 30 (4 hiperparámetros).

### 5.4 Qué se informa de cada modelo y criterio de selección

Selección del modelo ganador: **PR-AUC ponderada en validación** (criterio principal); desempate 1.º cobertura (recall) al 1 %, 2.º calibración (Brier/log-loss en
validación). Se declara empate práctico si el IC 95 % de la diferencia de PR-AUC incluye 0; en ese caso se prefiere el modelo más simple (logística).
Se informa de cada uno: hiperparámetros iniciales, rango, elegidos, `n_iter_`, tiempo, PR-AUC, ROC-AUC, recall 1 % y 5 %, lift, Brier y calibración.

## 6. Optuna (Entregable 6)

| Elemento | Configuración |
|---|---|
| Objetivo | Maximizar la PR-AUC ponderada media sobre los pliegues internos (con embargo); desempate por log-loss |
| Muestreador | `TPESampler(seed)`, `n_startup_trials = 10` (con 20 pruebas, 10 azarosas son demasiadas: 5 en logística); `RandomSampler(seed)` como control en una ejecución |
| Poda | `MedianPruner(n_startup_trials = 5, n_warmup_steps = 0)`: se reporta tras el primer pliegue interno y se poda si está bajo la mediana |
| Pruebas | Logística 20; RF 25; HGB 30 (reducido: 10, 10, 10) |
| Tiempo máximo | 30 min por estudio en el plan reducido; 90 min en el completo |
| Detención anticipada | 8 pruebas seguidas sin mejora > 1 % relativo, y botón de detener entre pruebas (ya existe) |
| Espacio | Máximo 4 hiperparámetros; reducir con fANOVA (descartar los de importancia < 5 %) y relanzar si hay avisos de borde |
| Prueba | **Nunca** participa; solo desarrollo e internos |
| Persistencia | Estudios en SQLite (`/data/ml/optuna.db`, D6) además de la tabla `ml_studies`; reanudables con el mismo nombre y semilla |
| Reproducibilidad | Semilla del muestreador, de los modelos y del remuestreo; `n_jobs` de Optuna = 1 (evita no determinismo) |

Caso de la logística: el estudio previo ampliaba `C` hasta 10 y el modelo reentrenado fue peor en validación y prueba. Con 400 eventos el rango razonable es de
1e-4 a 1: se adopta (§5.1). El aviso de borde sigue activo y, si el óptimo vuelve al borde inferior, se reporta como «regularización máxima admisible», no se amplía sin límite.

## 7. Evaluación y calibración (Entregable 7)

### 7.1 Protocolo común

Sobre la prueba, con una sola evaluación: modelos entrenados, **EPSS**, **CVSS de la CNA** y **orden aleatorio** (promedio de 200 permutaciones).
Métricas: PR-AUC y ROC-AUC ponderadas; recall al 1 % y 5 %; precisión y lift (precisión / prevalencia) en el umbral fijado en validación;
Brier ponderado y su cociente con el de predecir la tasa base; estabilidad por mes; tamaño: filas, **eventos únicos** y fotos.

### 7.2 Incertidumbre

Bootstrap **por clúster de CVE** (todas las filas de un CVE se remuestrean juntas, estratificado por eventos/no eventos; el actual `assess` ya remuestrea por CVE).
Como el mismo mes comparte contexto (versión de EPSS, ritmo de KEV), se añade como análisis de sensibilidad un **bootstrap por bloques de fotos** (bloques de 2). IC al 95 %
con 2 000 remuestreos en el plan completo, 500 en el reducido. Con < 30 eventos, los IC se marcan como «orientativos».

### 7.3 Pruebas de hipótesis

| Prueba | Uso | Observación |
|---|---|---|
| Bootstrap pareado de ΔPR-AUC y ΔROC-AUC | Principal para comparar modelos (por CVE) | |
| McNemar | Aciertos en el punto de operación (1 % y 5 %) | Con ≈ 100 eventos tiene poca potencia |
| Wilcoxon pareado sobre los 4 pliegues externos | Complementario | Con n = 4 el menor valor p exacto bilateral es 0,125: **nunca puede dar p < 0,05**; se reporta solo como descriptivo |
| Friedman sobre 4 pliegues | Complementario | Potencia muy baja; se declara |
| Corrección de **Holm** | Sobre todas las comparaciones del mismo conjunto (cada modelo vs EPSS, vs CVSS, vs el mejor) | |

### 7.4 Significancia estadística frente a utilidad práctica (D5, a fijar antes de ver la prueba)

Una diferencia es **estadísticamente significativa** si el IC 95 % del bootstrap pareado de ΔPR-AUC excluye 0 y el valor p ajustado por Holm es < 0,05.
Es **prácticamente útil** si además el modelo, revisando el 1 % del universo, cubre al menos **5 puntos porcentuales** más de eventos que EPSS y su PR-AUC es al menos
**2×** la de EPSS. Si es significativa pero no útil, se dice; si no es significativa, se dice «no distinguible del azar» sin elegir ganador.

### 7.5 Calibración

Platt frente a isotónica, ajustadas en validación. Elección por log-loss con validación cruzada temporal **dentro de validación** (2 pliegues); la isotónica solo se acepta con ≥ 50 eventos
en validación (si no, Platt). En prueba: observado/esperado, pendiente e intercepto con IC bootstrap, Hosmer-Lemeshow por tramos, curva de calibración y Brier. La **deriva**
validación → prueba se cuantifica como diferencia de O/E entre la última mitad de validación y la prueba, y se evalúa la recalibración con la porción reciente de validación.

### 7.6 Análisis de sensibilidad

Horizonte (30, 90, 180), versión de EPSS (con y sin el grupo), ablación (EPSS, CVSS), ventana (expansiva y deslizante), semilla (5 semillas en el plan completo, 3 en el reducido; se informa mediana y rango).

## 8. Explicabilidad

Se conserva (oclusión por grupo, importancia por permutación en prueba, dependencia parcial 1D/2D, explicación por caso). Verificación pendiente en Fase 3: todo se calcula en prueba y
en la escala original (el código actual lo hace según su documentación; se comprobará con un test). Límite: la importancia indica influencia en el modelo, no causalidad de la explotación.

## 9. Cambios de código previstos para la Fase 3 (Entregable 8, borrador)

1. `dataset.py`: `snapshots` desde 2023-04; `split_of` → `embargoed_split(dates, horizon, frac)` con la regla S + N ≤ inicio siguiente; columna `excluded` (fotos fuera) y estadísticas de eventos únicos por bloque.
2. `training.py`: `forward_folds` → versión con fechas y embargo; k_out = 4, k_in = 2, bloques 3/2; registro de pliegues excluidos; `feasible()` con las nuevas reglas.
3. `algorithms.py`: espacios nuevos (§5), `class_weight` fijo, parada anticipada temporal propia del HGB; grupo de ablación «versión EPSS».
4. `optimize.py`: MedianPruner por pliegue interno, sampler aleatorio de control, SQLite persistente, `n_jobs = 1`.
5. `assess.py`: bootstrap por clúster de CVE y por bloques, Wilcoxon (descriptivo) y Holm, lift, Brier relativo, eventos únicos.
6. `inference.py`: isotónica frente a Platt; deriva y recalibración.
7. Nuevo `ml/experiment.py`: ejecuta un experimento desde un JSON de configuración y escribe `resultados/<id>.json` y CSV; un comando (`python -m app.ml.experiment config.json`).
8. Registro: versiones de bibliotecas, hardware, semillas, tiempos y SHA-256 de cada fuente en cada resultado.
9. Pruebas: embargo (ninguna etiqueta de entrenamiento cruza la frontera), conservación de eventos, pliegues viables, parada anticipada temporal, bootstrap por clúster, Holm, reproducibilidad con semilla.
   Frontend: tabla de particiones con embargo y aviso de eventos únicos. Bitácora: cada acción de experimento.
   Protecciones: rechazo de entrenamientos duplicados (misma configuración e identificador de dataset) y límite de trabajos simultáneos (1 entrenamiento a la vez; ya existe `llm_slot` equivalente en IA, no en ML: se verifica).

## 10. Cómputo y plan (estimación)

Base medida: modelos previos tardaron 461 s (logística, 276 ajustes ≈ 1,7 s/ajuste), 366 s (RF, 5 pruebas, ≈ 96 ajustes ≈ 3,8 s) y 1039 s (HGB, 15 pruebas, 276 ajustes ≈ 3,8 s) con ≈ 200 000 filas.
El dataset nuevo tendrá ≈ 2× filas, y nested(4×2) ejecuta 5·(2T+1) ajustes por modelo. Estimación (± 50 %):

| Experimento | Pruebas | Ajustes | Tiempo estimado |
|---|---|---|---|
| Construir dataset 2023-04 (descarga ≈ 40 CSV de EPSS + NVD en caché) | — | — | 15 a 40 min (depende de la red; no verificado) |
| **Plan reducido**: logística, RF, HGB, 1 semilla | 10 cada uno | 105 c/u | LR ≈ 6 min, RF ≈ 13 min, HGB ≈ 13 min |
| Reducido + embargo vs sin embargo (para el artículo) | — | — | +30 min |
| Ablaciones del HGB (sin EPSS, sin CVSS, sin versión) | 10 | 105 c/u | ≈ 40 min |
| **Plan completo**: 3 algoritmos, 20/25/30 pruebas, 5 semillas | | | LR ≈ 1,5 h, RF ≈ 3 h, HGB ≈ 3,5 h por semilla → 40 h, **no cabe** |
| **Plan completo recortado**: 3 semillas solo para el modelo ganador y la logística | | | ≈ 8 a 10 h |
| Sensibilidad horizontes 30 y 180 (logística + RF, reducido) | 10 | | ≈ 1,5 h + dataset (30 a 60 min cada uno) |

Prioridad (cambian las conclusiones del artículo): embargo → calibración → comparación estadística → ablación de versión EPSS → horizontes.
Los entrenamientos corren en segundo plano; **no se reinicia el backend** mientras corren (el trabajo queda «interrumpido»).

## 11. Pendiente / limitaciones ya conocidas

- Volumen real de eventos del dataset nuevo y disponibilidad de EPSS 2023-04 a 2024-12: por confirmar al construir.
- La deriva entre EPSS v3 (desarrollo) y v4/v5 (validación y prueba) puede dominar cualquier resultado; el protocolo la reporta, no la resuelve.
- Los CVSS, CWE y CNA vienen de un feed actual, no de una versión histórica: no se puede descartar edición posterior por la CNA.
- Una sola fuente de datos (KEV) y un solo horizonte principal.
- Los umbrales de utilidad práctica y los rangos de Optuna son propuestas, no resultados.
