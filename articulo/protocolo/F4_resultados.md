# Fase 4 · Reentrenamiento y optimización, plan reducido (Entregable 9, parte 1)

Fecha: 2026-11-20. Todo lo de abajo sale de ejecuciones reales; cada cifra está en `resultados/f4/*.json`
(configuración, versiones, SHA-256 del dataset, pliegues, pruebas de Optuna, métricas) y `controls.json`.
Semilla 7, **una sola semilla** (plan reducido), 10 pruebas de Optuna por búsqueda, CV anidada 4×2 con embargo de 90 días.
**El plan completo (más pruebas, 3 a 5 semillas, horizontes 30/180) no se ejecutó.** Los modelos no se compararon aún con
pruebas estadísticas ni se calibraron (Fase 5): las diferencias entre modelos de abajo **no se declaran significativas**.

## 1. Datos reales del dataset nuevo (confirmados)

| | v3 con embargo (principal) | v3b sin embargo (control) |
|---|---|---|
| Fotos | 41 (2023-04 a 2026-08), 4 excluidas (2025-05, 2025-06, 2026-01, 2026-02) | 41, sin exclusión |
| Desarrollo | 25 fotos, 557 filas positivas, **239 eventos** | 29 fotos |
| Validación | 6 (2025-07 a 12), 160 filas, **80 eventos** | 6 (2025-09 a 2026-02) |
| Prueba | 6 (2026-03 a 08), 184 filas, **105 eventos** | igual |
| Filas / positivos | 484 200 / 901 filas (424 eventos) | |
| EPSS | v2023.03.01 en 24 fotos de desarrollo; v2025.03.14 en 1 de desarrollo, toda la validación y 4 de prueba; v2026.06.15 en 2 de prueba | |

Hubo que corregir un fallo real del constructor: el bucket de EPSS responde **403** (no 404) cuando falta el archivo de un día
(2024-12-01), y el respaldo «hasta 3 días antes» no se activaba. Corregido con prueba.
Con respecto al diseño: eventos reales 239 / 80 / 105 (antes 193 / 55 / 57).
Los negativos muestreados de v3 y v3b difieren (la semilla se consume distinto al saltar fotos excluidas): la prueba de ambos
comparte positivos, no negativos.

## 2. Líneas base (prueba, 105 eventos; validación 80 eventos)

| | PR-AUC prueba | ROC-AUC prueba | Cobertura 1 % | PR-AUC validación | ROC-AUC validación |
|---|---|---|---|---|---|
| Azar | 0,00009 | 0,50 | 1 % | 0,00010 | 0,50 |
| EPSS | 0,00099 | 0,678 | 17,4 % | 0,0228 | 0,724 |
| CVSS de la CNA | 0,00063 | 0,705 | 11,4 % | 0,00032 | 0,660 |

Prevalencia ponderada ≈ 0,0092 %. EPSS rinde 23 veces más en validación que en prueba (0,0228 frente a 0,00099): es la deriva de versión
y de periodo, no una propiedad estable.

## 3. Modelos con embargo (CV 4×2; grupo «versión EPSS» fuera)

| Modelo | Mejor configuración | PR-AUC CV (± sd) | Val. PR / ROC | Prueba PR | Prueba ROC | Cob. 1 % | Cob. 5 % | Tiempo |
|---|---|---|---|---|---|---|---|---|
| Logística | C = 0,0012 | 0,0181 ± 0,0186 | **0,0271** / 0,878 | 0,0079 | **0,889** | 30,4 % | **54,4 %** | 2 min |
| Logística (TPE con 5 pruebas iniciales) | C = 0,0010 | 0,0017 | 0,0221 / 0,883 | 0,0080 | 0,893 | 31,0 % | 56,0 % | 2 min |
| Random forest | depth/leaf/features, ver JSON | 0,0085 ± 0,0128 | 0,0020 / 0,867 | 0,0034 | 0,851 | 21,7 % | 50,5 % | 16 min |
| HGB (parada en 36 árboles) | los valores por defecto | 0,0270 ± 0,0279 | 0,0026 / 0,850 | 0,0042 | 0,840 | 31,0 % | 41,9 % | 9 min |

- El criterio pactado (PR-AUC en **validación**) elige la **logística**; en prueba obtiene PR-AUC 0,0079 (8 veces EPSS, 90 veces el azar) y
  ROC-AUC 0,889 frente a 0,678 de EPSS. Esa conclusión no se apoya en la CV: la CV puso primero al HGB (0,027) y último al RF.
- La PR-AUC media de la CV es muy inestable: la logística pasó de 0,0181 a 0,0017 solo cambiando cuántas pruebas iniciales usa el muestreador,
  mientras la prueba casi no se movió (0,0079 → 0,0080). Con pliegues de 10 a 30 eventos, **la media de PR-AUC de la CV no sirve para ordenar modelos**.
- El HGB eligió dos veces los hiperparámetros **por defecto**: con 10 pruebas y 4 parámetros, la búsqueda no encontró nada mejor.
- Muestreador: con 10 pruebas, TPE con su arranque por defecto (10 pruebas aleatorias) **es idéntico a la búsqueda aleatoria**
  (`emb_logreg` = `emb_logreg_aleatorio` al decimal); el control de la Fase 2 no informaba nada. Se corrigió (5 pruebas aleatorias + 5 guiadas)
  y `emb_logreg_tpe5` / `emb_hgb_tpe5` lo usan; los resultados con el arranque anterior se conservan marcados.
- Entre el 24 % y el 42 % de las pruebas de Optuna se podaron en las ejecuciones con embargo (12 a 21 de 50) (poda por mediana tras el primer pliegue interno).

## 4. Ablaciones del HGB (con embargo; prueba)

| Variante | Val. PR / ROC | Prueba PR | Prueba ROC | Cob. 1 % | Cob. 5 % |
|---|---|---|---|---|---|
| Sin versión de EPSS (base) | 0,0026 / 0,850 | 0,0042 | 0,840 | 31,0 % | 41,9 % |
| Con versión de EPSS | 0,0023 / 0,860 | 0,0035 | 0,856 | 31,0 % | 39,7 % |
| Sin EPSS (y sin versión) | 0,0017 / 0,808 | 0,0083 | 0,819 | 26,6 % | 38,0 % |
| Sin CVSS (y sin versión) | 0,0031 / 0,831 | 0,0022 | **0,786** | 25,5 % | 39,1 % |

Lectura honesta: quitar CVSS es lo que más baja el ROC-AUC en prueba (0,840 → 0,786); quitar EPSS baja el ROC (0,840 → 0,819) pero la PR-AUC
sube (0,0042 → 0,0083), lo que con 105 eventos es ruido. Dejar o quitar la versión de EPSS cambia el ROC en 0,016 con una semilla: **no hay
evidencia de que la decisión D4 ayude ni estorbe**.

## 5. Efecto del embargo (control sobre v3b, mismos hiperparámetros, 3 semillas, misma validación y prueba)

Se compara entrenar con el desarrollo completo (29 fotos) o purgado (27 fotos: se quitan 2 que cruzan hacia validación; la parada del HGB también con embargo).

| Modelo | Validación PR-AUC (sin → con) | Prueba PR-AUC (sin → con) | Prueba ROC (sin → con) |
|---|---|---|---|
| Logística | 0,0407 → 0,0416 | 0,0082 → 0,0126 | 0,889 → 0,890 |
| Random forest | 0,0031 → 0,0143 (rango 0,0102 a 0,0166) | 0,0029 → 0,0175 (rango 0,0106 a 0,0275) | 0,872 → 0,885 |
| HGB | 0,0047 → 0,0076 | 0,0313 → 0,0187 | 0,902 → 0,893 |

**El resultado de la Fase 1 no se reprodujo en este dataset.** En el dataset antiguo, la validación de RF y HGB bajaba 6 a 8 veces al aplicar el embargo;
aquí la dirección **no es consistente**: el RF mejora, la logística casi no cambia y el HGB empeora en prueba. Lo que sí se mantiene es la
existencia estructural de la fuga (ventanas que cruzan, 34 CVE positivos en dos particiones en el dataset viejo): se corrige por diseño, aunque su efecto
medido sobre las métricas es **indistinguible del ruido** con una sola partición y 80 a 105 eventos. La PR-AUC varía entre semillas hasta 2,6 veces
(RF), así que **no debe usarse como cifra única**; el ROC-AUC es estable (±0,01).
Además, la comparación `emb_*` frente a `leak_*` de §3 mezcla el embargo con otras diferencias (29 frente a 25 fotos de desarrollo, validación más reciente,
negativos distintos), por eso no se interpreta como efecto del embargo.

## 6. Qué cambia respecto a las conclusiones previas

1. «El HGB completo gana la CV pero cae en prueba»: se **mantiene** (CV 0,027 y prueba 0,0042), pero con el embargo ya no es el único que muestra esa inversión: la
   CV no ordena los modelos de forma fiable.
2. «El random forest rinde más en prueba» (0,0178): **no se sostiene** con el dataset nuevo (RF 0,0034); era un resultado del dataset y la partición anteriores.
3. La logística, el modelo más simple, queda primero en validación y con el mejor ROC-AUC y cobertura al 5 % en prueba: el protocolo no encuentra evidencia
   de que los modelos de árboles aporten algo más con ≈ 240 eventos de desarrollo.
4. Todos los modelos superan con claridad al azar y a EPSS/CVSS solos en ROC-AUC (0,84 a 0,89 frente a 0,68 y 0,71), pero la cobertura al 1 % se queda en
   22 a 31 %: se puede **ordenar mucho mejor que al azar, no anticipar con precisión**.

## 7. Limitaciones y pendiente

- Una semilla y una partición: no hay IC. La PR-AUC fluctúa 2 a 3 veces entre semillas, así que **ninguna diferencia entre modelos está respaldada**.
- No ejecutado: plan completo (más pruebas, 3 a 5 semillas), horizontes 30 y 180, ventana deslizante.
- Pendiente (Fase 5): IC por bootstrap por CVE y por bloques, Holm, McNemar, calibración Platt frente a isotónica y deriva, explicabilidad de los modelos nuevos, estabilidad por mes.
- Los resultados con el arranque de TPE antiguo (`emb_logreg`, `emb_random_forest`, `emb_hgb`, `leak_*`, ablaciones) se mantienen para trazabilidad; solo `*_tpe5` usa el corregido.
- Los datasets v3 y v3b están en la base (`ml_datasets`) y el volumen `ml_data`; los modelos de la Fase 4 se ejecutaron con el runner (no están en `ml_models`: la Fase 5 los necesita ahí para evaluar con la API o se evalúa desde los `.preds.csv.gz`).
