# Fase 1 · Informe de auditoría del Laboratorio de modelos (Entregable 1)

Fecha: 2026-11-20. Alcance: `backend/app/ml` en el commit `062152a`, dataset «KEV en 90 días v2 (sin fuga)»
(`8f99a75b…`), semilla 7. Todo lo que sigue sale de ejecuciones sobre ese dataset; los archivos de resultados están
en `articulo/protocolo/resultados/` (`f1_auditoria.json`, `f1_embargo_rapido.json`) y los scripts en
`articulo/protocolo/scripts/`. Ningún archivo del backend se modificó en esta fase.

## 1. Estructura de los datos

| Concepto | Valor |
|---|---|
| Unidad de análisis | CVE × foto mensual (el CVE aún no está en KEV en la foto S) |
| Fotos | 20 (2025-01-01 a 2026-08-01); horizonte N = 90 días |
| Filas / positivos (filas) | 301 167 / 602 |
| **Eventos únicos (CVE positivos distintos)** | **264** (desarrollo 193, validación 55, prueba 57) |
| Negativos | muestreados al 5 %, peso 20 (todos); positivos peso 1 |
| Prevalencia real por foto | 0,006 % a 0,016 % (≈ 10 a 50 positivos entre ≈ 270 000 CVE) |
| Partición | desarrollo 14 fotos (2025-01 a 2026-02), validación 3 (2026-03 a 05), prueba 3 (2026-06 a 08) |
| Positivos (filas) por partición | 418 / 91 / 93 |

Positivos por foto (filas): 30, 36, 27, 23, 27, 29, 22, 33, 31, 34, 17, 23, 37, 49 | 46, 31, 14 | 24, 32, 37.

**Hallazgo estructural.** Las «24 a 37 positivos por mes» del README son *filas*, no eventos. Un CVE que entra a KEV
queda etiquetado positivo en todas las fotos mensuales cuya ventana de 90 días lo contiene: 145 de los 264 eventos
aparecen en 3 fotos, 48 en 2 y 71 en 1. El tamaño muestral efectivo es **264 eventos**, no 602, y en prueba **57**,
no 93. Cualquier IC calculado a nivel de fila (o de foto) subestima la incertidumbre. El bootstrap de `assess.py`
remuestrea por CVE (correcto en eso), pero ver la sección 4.

## 2. Variables

Usadas (14): `epss`, `percentile`, `epss_delta`, `epss_model`, `cvss` + `av/ac/pr/ui` (solo CVSS de la CNA), `cwe` (CNA),
`cna`, `days_published`, `edb_exploits` (fecha ≤ S), `cna_kev_prior` (KEV ≤ S). Excluidas por fuga, según `dataset.EXCLUDED`:
SSVC (la ausencia delataba la etiqueta: 99,5 % de positivos «sin evaluar» vs 62 %), CVSS/CWE añadidos por NVD o ADP
(todos los positivos tenían CVSS), `n_refs` (estado actual) y Metasploit (solo `mod_time`). No encontré en el código
ninguna variable adicional con fecha posterior a S. Riesgo residual a verificar en Fase 3: `days_published` usa la
fecha de publicación del NVD y se anula si es posterior a S (correcto); `cwe` y `cvss` de la CNA son campos que la CNA puede
editar después (el feed es un estado actual, no una versión histórica). No se puede cuantificar con las fuentes actuales.

## 3. Reproducción de las cifras declaradas

Reproducidas desde las predicciones guardadas (`*.preds.csv.gz`) con `metrics.evaluate`; y, para logística, RF y HGB,
reentrenando con los hiperparámetros guardados (resultado idéntico al almacenado).

| Cifra declarada | Reproducida | Estado |
|---|---|---|
| RF prueba PR-AUC 0,0178 / ROC 0,914 | 0,01781 / 0,9145 | ✔ |
| HGB completo: CV PR-AUC 0,080 | 0,0798 | ✔ |
| HGB prueba 0,0017; validación 0,0189 | 0,00168; 0,01893 | ✔ |
| Logística prueba 0,0115; EPSS solo 0,0006 | 0,01151; 0,00057 | ✔ |
| HGB sin EPSS ≈ 0,012; sin CVSS ≈ 0,013 | 0,01246; 0,01301 | ✔ |
| Logística con espacio del estudio: ROC 0,853, PR 0,0076 | 0,8525; 0,00764 | ✔ |
| Sobreestimación O/E 0,5–0,8; logística reentrenada O/E 0,12 | no recalculado | Pendiente (Fase 5) |
| Resultados de `explain` y `optimize` (fANOVA 90 %) | no recalculados | Pendiente |

Referencias en prueba (mismo cálculo): CVSS solo PR-AUC 0,0013 / ROC 0,786; azar PR-AUC ≈ 0,0001 (= prevalencia 0,009 %).
Un PR-AUC de 0,0178 es ≈ 200 veces la prevalencia, pero 0,0017 (HGB) es solo ≈ 19 veces: con 57 eventos, la diferencia
entre 0,0017 y 0,0178 puede ser en gran parte azar (no se cuantifica aquí; es objeto de la Fase 5).

CV anidada (PR-AUC media en 5 pliegues externos): HGB 0,0798 y 0,0538/0,0548 (ablaciones); logística 0,0030; RF 0,0028;
EPSS 0,0195. Es decir, en CV el HGB gana 4 a 5 veces y la logística y el RF pierden frente a EPSS, justo al revés que en
prueba. Es una inversión que merece explicación; la fuga de la sección 4(a) es una candidata (los pliegues de CV
también la tienen), pero no se ha probado que sea la causa.

## 4. Riesgos de fuga

### (a) Falta de embargo — CONFIRMADO, efecto grande

Las etiquetas miran 90 días hacia delante, pero las particiones y los pliegues se cortan por foto sin separación.

| Frontera | Fotos cuya ventana cruza la frontera | Positivos cuyo evento ocurre *después* del inicio del bloque siguiente |
|---|---|---|
| Desarrollo → validación (2026-03-01) | 2026-01, 2026-02 | 49 de 418 positivos de desarrollo |
| Validación → prueba (2026-06-01) | 2026-04, 2026-05 | 9 de 91 positivos de validación |
| CV externa, pliegue 1 a 5 | 3, 2, 2, 2, 2 fotos de entrenamiento | 23, 19, 30, 10, 23 positivos de entrenamiento |
| Búsqueda interna del modelo final | 2 fotos en cada uno de los 3 pliegues | — |

Además, el *mismo CVE* es positivo en dos particiones: 34 CVE en desarrollo y validación, 7 en validación y prueba (0 entre
desarrollo y prueba). Es decir, el modelo se entrena con la etiqueta de un evento y luego se «valida» sobre ese mismo
evento visto en otra foto. El coste del embargo con N = 90 es **2 fotos por frontera** (14 → 12 en desarrollo; en validación
quedaría 1 de 3 si se purga hacia la prueba).

**Efecto cuantificado** (reentrenando con los hiperparámetros guardados, semilla 7, un solo ajuste por modelo; exploratorio):
se quitan de desarrollo las 2 fotos cuya ventana cruza la validación.

| Modelo | Validación PR-AUC (sin → con embargo) | Prueba PR-AUC (sin → con) | Prueba ROC-AUC (sin → con) |
|---|---|---|---|
| Logística | 0,0128 → 0,0124 | 0,0115 → 0,0217 | 0,920 → 0,917 |
| Random forest | 0,0182 → **0,0032** | 0,0178 → **0,0029** | 0,915 → 0,900 |
| HGB | 0,0189 → **0,0024** | 0,0017 → 0,0016 | 0,852 → 0,853 |

Lectura honesta: (i) la validación de RF y HGB estaba **inflada ~6 a 8 veces** por la fuga, y el HGB fue «elegido en
validación» por esa razón; (ii) con embargo la ventaja de RF en prueba desaparece (0,0178 → 0,0029) y la logística la
supera (0,0217): el orden de los modelos en prueba cambia, lo que apunta a que parte del resultado del RF dependía de
las fotos con ventana solapada y a una gran inestabilidad (un solo ajuste, 57 eventos); (iii) las cifras de prueba con un
solo ajuste no son concluyentes: hay que repetir con varias semillas y con IC por bloques (Fase 4). No se declara
ganador. El número de fotos para entrenar baja de 14 a 12 y para la CV externa el primer pliegue pierde 3 de 4 fotos, así que
**el diseño 5×3 deja de ser factible con 14 fotos** (ver §6).

### (b) Cambio de versión de EPSS — CONFIRMADO, riesgo de deriva (no de fuga)

Tres versiones: v2023.03.01 (2025-01 a 03), v2025.03.14 (2025-04 a 2026-06) y v2026.06.15 (2026-07 y 08). El percentil 99 de `epss`
baja de 0,86 a 0,75 y a 0,55: la escala cambia. `epss_delta` en 2025-04 y 2026-07 mezcla dos versiones. La prueba contiene
una foto con la versión antigua (2026-06) y dos con la nueva; `epss_model` como categórica desconocida en desarrollo
cae en «infrecuente». No es fuga, pero sí desajuste entre entrenamiento y prueba: `percentile` es robusto; `epss` y
`epss_delta` no.

### (c) CVE repetidos — CONFIRMADO

Promedio 1,51 filas por CVE. Positivos: 602 filas / 264 CVE (sección 1). Falta comprobar cuántos negativos de prueba
también están en desarrollo (pendiente; no cambia la etiqueta pero sí la independencia).

### (d) Pesos — PARCIAL

Los negativos pesan 20 (1/0,05) y se pasan como `sample_weight`. Para `class_weight="balanced"` sklearn multiplica el peso de
clase por `sample_weight`: el desbalance se corrige **dos veces** (muestreo y balanced), lo que sesga las probabilidades
hacia arriba y empeora la calibración; los modelos elegidos con `none` evitan ese efecto. La PR-AUC ponderada es
coherente con la prevalencia real; el PR-AUC de CV promedia pliegues de 14 a 50 positivos-fila (~10 a 25 eventos): muy ruidoso.

### (e) Uso de prueba para elegir — NO ENCONTRADO en el código

`assess.best` se elige en validación; `test_best` solo se muestra; la calibración de Platt y el umbral usan validación;
Optuna usa solo desarrollo. Observaciones: (1) la validación estaba contaminada por (a), así que «elegido en validación»
no era un criterio limpio; (2) según CLAUDE.md, la comparación de la logística reentrenada con el espacio del estudio se informó
con cifras de prueba; fue descriptiva, pero debe quedar registrada como análisis posterior, no como decisión.

## 5. Suficiencia de datos

193 eventos en desarrollo (≈ 160 con embargo), 55 en validación, 57 en prueba. Regla orientativa de 10 a 20 eventos por
parámetro efectivo: la logística con one-hot de CWE y CNA (cientos de columnas, regularizada fuerte) funciona solo
porque la regularización lo compensa; RF y HGB con 4 a 6 hiperparámetros optimizados sobre pliegues de 10 a 25 eventos
son muy inestables. Con 55 y 57 eventos, un IC 95 % de la PR-AUC cubre fácilmente un orden de magnitud. Recomendación para la
Fase 2: máximo 2 a 3 hiperparámetros por modelo; fANOVA para fijar el resto; reportar siempre IC por bloques/CVE;
no declarar ganadores entre los modelos sin prueba pareada y corrección de Holm.

## 6. Qué cambia en el diseño (adelanto para la Fase 2, a aprobar)

1. **Embargo ≥ 90 días** entre desarrollo/validación, validación/prueba y dentro de cada pliegue de la CV. Con 20 fotos
   el diseño sin pérdidas ya no cabe. Opciones: (A) ampliar fotos hacia atrás (EPSS diario desde ≥ nov-2024 según
   CLAUDE.md: +2 fotos, requiere verificar disponibilidad y volver a construir el dataset); (B) reducir la CV externa a 4×3
   con embargo interno; (C) reducir la validación a 1 foto efectiva. Hay que decidirlo con tus preferencias y el plazo.
2. Dedup por evento para métricas: reportar eventos únicos y bootstrap por CVE en bloques.
3. `class_weight="balanced"` con `sample_weight`: eliminarlo del espacio o documentarlo como doble corrección.
4. Percentil y versión de EPSS: valorar excluir `epss_delta` o usar solo `percentile` en el horizonte de las fotos de
   dos versiones.

## 7. Pendiente / no verificado en esta fase

- O/E, calibración de la Fase 6, fANOVA y atribución de `explain`: no recalculados.
- Negativos compartidos entre particiones, y el efecto aislado de EPSS-versión: no medidos.
- Datos de EPSS antes de 2025-01 y su disponibilidad: no verificada.
- El efecto de embargo se midió con un único ajuste y una semilla; es evidencia de dirección, no de magnitud.
