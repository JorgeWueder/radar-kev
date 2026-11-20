# Fase 5 · Evaluación estadística, calibración y explicabilidad (Entregable 9, parte 2)

Fecha: 2026-11-20. Base: las predicciones de la Fase 4 (`resultados/f4/emb_*.preds.csv.gz`), semilla 7, prueba de 6 meses
(2026-03 a 08) con **105 eventos únicos** y 88 783 CVE distintos. El modelo se eligió en validación (logística) antes de mirar la prueba.
Archivos: `resultados/f5/{stats,mcnemar_events,calibration,stability,seeds,explain}.json`; scripts `scripts/f5_*.py`.
Reproducción: el reajuste de la logística y del HGB reproduce las predicciones guardadas con diferencia máxima de 1e-16.

## 1. Incertidumbre y comparaciones (bootstrap por CVE, 500 remuestreos, estratificado por CVE con evento)

| | PR-AUC [IC 95 %] | ROC-AUC [IC 95 %] | Cobertura 1 % [IC] | Cobertura 5 % [IC] |
|---|---|---|---|---|
| **Logística** | 0,0079 [0,0037; 0,0429] | 0,889 [0,859; 0,918] | 30,4 % [22,3; 40,0] | 54,4 % [44,7; 64,8] |
| Random forest | 0,0034 [0,0015; 0,0278] | 0,851 [0,803; 0,894] | 21,7 % [15,0; 30,0] | 50,5 % [41,0; 60,5] |
| HGB | 0,0042 [0,0022; 0,0089] | 0,840 [0,794; 0,885] | 31,0 % [22,1; 40,6] | 41,9 % [33,5; 51,4] |
| EPSS | 0,0010 [0,0005; 0,0021] | 0,678 [0,607; 0,748] | 17,4 % [9,9; 25,8] | 36,4 % [27,7; 46,7] |
| CVSS de la CNA | 0,0006 [0,0004; 0,0010] | 0,705 [0,648; 0,771] | 11,4 % [6,6; 18,3] | 36,4 % [25,9; 45,5] |

El IC de la PR-AUC es muy asimétrico (la logística llega a 0,043 en los meses 2026-07 y 08): **la PR-AUC puntual subestima la
incertidumbre**; el ROC-AUC y la cobertura son más estables.

### Diferencias pareadas (mismo remuestreo), p con corrección de Holm

| Comparación | ΔPR-AUC [IC] (p Holm) | ΔROC-AUC [IC] (p Holm) | Δ cobertura 1 % [IC] |
|---|---|---|---|
| Logística − EPSS | +0,0069 [0,0025; 0,0419] (0,012) | +0,212 [0,143; 0,275] (0,012) | +13,0 pp [0,5; 25,3] |
| Logística − CVSS | +0,0073 [0,0032; 0,0422] (0,012) | +0,184 [0,132; 0,235] (0,012) | +19,0 pp [10,9; 26,9] |
| RF − EPSS | +0,0025 [0,0003; 0,0264] (0,032) | +0,174 [0,096; 0,254] (0,012) | +4,3 pp [−7,3; 15,5] |
| HGB − EPSS | +0,0032 [0,0008; 0,0080] (0,016) | +0,162 [0,077; 0,251] (0,012) | +13,6 pp [−0,5; 26,9] |
| Logística − RF | +0,0045 [−0,0143; 0,0354] (0,216) | +0,038 [0,002; 0,073] (0,056) | +8,7 pp [3,3; 15,1] |
| Logística − HGB | +0,0038 [0,0002; 0,0387] (0,080) | +0,050 [0,005; 0,092] (0,056) | −0,6 pp [−5,8; 5,8] |

Familias de Holm: 6 comparaciones con las líneas base; 2 entre modelos. Valor p mínimo alcanzable con 500 remuestreos: 0,002.

- **Los tres modelos mejoran de forma estadísticamente significativa a EPSS y a CVSS en ROC-AUC y PR-AUC** (todos p Holm < 0,05).
- **Entre modelos no hay diferencia significativa tras Holm** (p 0,056 a 0,216): la logística no se distingue del RF ni del HGB. Se prefiere por
  parsimonia, no por superioridad demostrada.
- Sensibilidad con bootstrap por **bloques de 2 meses** (300 remuestreos): la logística mantiene ΔPR-AUC frente a EPSS con IC [0,0020; 0,0357]; RF y HGB
  ya no (IC incluyen 0: [−0,012; 0,011] y [−0,013; 0,007]); el ROC-AUC sigue significativo para los tres. Con la dependencia entre meses, solo la
  logística conserva su ventaja en PR-AUC.

### Utilidad práctica (criterio D5 fijado antes: +5 pp de cobertura al 1 % frente a EPSS y PR-AUC ≥ 2× la de EPSS)

| Modelo | Ganancia de cobertura | PR-AUC / EPSS | Cumple (punto) | El IC de la ganancia excluye 0 |
|---|---|---|---|---|
| Logística | +13,0 pp | 8,0× | **Sí** | Sí, por poco ([0,5; 25,3]) |
| HGB | +13,6 pp | 4,2× | Sí | **No** ([−0,5; 26,9]) |
| RF | +4,3 pp | 3,5× | No | No |

Solo la logística cumple el criterio con IC que excluye cero, y con margen pequeño: la significancia estadística es sólida en ROC-AUC, la utilidad
práctica es **moderada y frágil**.

### McNemar en el punto de operación (umbral fijado en validación)

Por **filas** el McNemar salió con p = 0 en todas las comparaciones porque cuenta falsos positivos de un universo de ≈ 100 000 filas; **se descarta**.
A nivel de **evento** (un CVE positivo cuenta una vez; «detectado» = alguna fila sobre el umbral):

| Punto | Detectados de 105 | Logística frente a EPSS (solo log. / solo EPSS, p) | frente a CVSS | frente a RF | frente a HGB |
|---|---|---|---|---|---|
| 1 % | log. 42, RF 47, HGB 43, EPSS 16, CVSS 29 | 38 / 12, p = 0,0003 | 16 / 3, p = 0,0044 | 4 / 9, p = 0,27 | 7 / 8, p = 1,0 |
| 5 % | log. 65, RF 73, HGB 58, EPSS 36, CVSS 45 | 41 / 12, p = 0,0001 | 20 / 0, p < 0,0001 | 5 / 13, p = 0,096 | 13 / 6, p = 0,17 |

Sin ajustar por Holm (6 pruebas por punto); los resultados frente a EPSS y CVSS resisten el ajuste, los demás no son significativos.

### Pliegues externos de la CV (4 pliegues; Friedman con modelos y EPSS)

Friedman: PR-AUC p = 0,026, ROC-AUC p = 0,044 (EPSS siempre último). Wilcoxon de la logística frente a RF, HGB y EPSS: p = 0,625 / 0,625 / 0,125; con 4 pliegues el
menor p posible es 0,125, así que **no puede ser significativo**; se reporta solo como descriptivo. Los modelos superan a EPSS en 4 de 4 pliegues en ROC-AUC.

## 2. Calibración (en validación; verificación en prueba)

| Modelo | Calibrador elegido (log-loss CV temporal en validación) | O/E en prueba [IC 95 %] | Pendiente [IC] | Brier relativo a la tasa base (habilidad) |
|---|---|---|---|---|
| Logística | Platt (isotónica solo con ≥ 50 eventos: 80, pero peor en CV) | **0,81** [0,66; 0,93] (sin calibrar: 1,36) | 1,07 [0,94; 1,22] | +0,0029 |
| Random forest | Platt | **0,55** [0,46; 0,64] (sin calibrar: 0,19) | 0,92 [0,81; 1,06] | +0,0003 |
| HGB | Isotónica (O/E 0,79) | 0,85 [0,70; 0,97] con Platt | 0,99 [0,89; 1,10] | −0,0005 (peor que la tasa base) |

- Todos los modelos **sobrestiman** en prueba: la logística espera 227 entradas y hubo 184 (O/E 0,81); el RF espera 332 (O/E 0,55). La tasa base de validación (0,00915 %) y la de prueba
  (0,00919 %) es casi igual: la deriva no es de prevalencia sino de la **relación entre el puntaje y el evento**.
- Recalibrar con la mitad reciente de validación acerca la logística a O/E 0,92 (y el RF a 0,63; el HGB a 0,87): ayuda pero no elimina el desajuste.
- Hosmer-Lemeshow rechaza la calibración perfecta en los tres (p ≈ 0): hay desajuste por tramos, sobre todo en la cola alta.
- La habilidad de Brier es casi nula (≤ 0,3 %): con una prevalencia de 0,009 %, **las probabilidades absolutas no aportan frente a predecir la tasa base**; el valor del modelo es el
  **orden** (ROC-AUC y cobertura), no la probabilidad individual. Esto debe decirse en el artículo.

## 3. Estabilidad por mes (prueba)

| Mes | Versión EPSS | Eventos | Logística PR / ROC | HGB PR / ROC | EPSS PR / ROC |
|---|---|---|---|---|---|
| 2026-03 | v2025.03.14 | 46 | 0,0465 / 0,839 | 0,0044 / 0,834 | 0,0258 / 0,673 |
| 2026-04 | v2025.03.14 | 31 | 0,0015 / 0,875 | 0,0011 / 0,815 | 0,0014 / 0,714 |
| 2026-05 | v2025.03.14 | 14 | 0,0047 / 0,885 | 0,0026 / 0,667 | 0,0015 / 0,789 |
| 2026-06 | v2025.03.14 | 24 | 0,0042 / 0,919 | 0,0037 / 0,835 | 0,0003 / 0,528 |
| 2026-07 | v2026.06.15 | 32 | 0,0618 / 0,944 | 0,0181 / 0,880 | 0,0005 / 0,634 |
| 2026-08 | v2026.06.15 | 37 | 0,0514 / 0,925 | 0,0096 / 0,907 | 0,0020 / 0,668 |

La PR-AUC mensual varía 40 veces (0,0015 a 0,0618) y es ruido de pocos eventos; el ROC-AUC de la logística se mantiene entre 0,84 y 0,94 y **supera a EPSS los 6 meses**. No hay deterioro con
la nueva versión de EPSS (los meses de v2026.06.15 son los mejores de la logística). El HGB tiene un mes con 14 eventos y ROC de 0,667: variabilidad de mes único.

## 4. Sensibilidad por semilla (hiperparámetros fijos de la Fase 4, 5 semillas; logística es determinista)

| Modelo | PR-AUC prueba (mediana; mín.–máx.) | ROC-AUC prueba (mediana; mín.–máx.) | Cobertura 1 % (mediana; rango) |
|---|---|---|---|
| Logística | 0,0079 (única) | 0,889 | 30,4 % |
| Random forest | 0,0108 (0,0032–0,0179) | 0,849 (0,828–0,859) | 18,5 % (17,4–22,8) |
| HGB | 0,0040 (0,0033–0,0051) | 0,854 (0,844–0,856) | 31,5 % (28,3–33,2) |

La PR-AUC del RF cambia 5,6 veces solo con la semilla: su cifra de la Fase 4 (0,0034) era el extremo inferior. Un modelo de árboles **no puede reportarse con una sola semilla**.
El ROC-AUC es estable (± 0,02) y mantiene a la logística por encima.

## 5. Explicabilidad (prueba; escala original; reajuste verificado)

Importancia por permutación (caída de ROC-AUC al desordenar el grupo):

| Grupo | Logística (ROC base 0,888) | HGB (ROC base 0,838) |
|---|---|---|
| EPSS | **0,101** | 0,048 |
| Antigüedad del CVE | 0,092 | **0,150** |
| CVSS de la CNA | 0,066 | 0,017 |
| CNA (quién publicó) | ≈ 0 | **0,063** |
| Exploits públicos | 0,014 | 0,023 |
| Historial KEV de la CNA | 0,009 | −0,011 (negativo: desordenarlo mejora un poco, es ruido) |

Coeficientes de la logística: `days_published` −0,59 (los CVE más antiguos tienen menos probabilidad de entrar), `cvss` +0,54, `epss` +0,48. La probabilidad media baja de 0,029 % a 0,002 % al pasar de
33 a 8 195 días de antigüedad, y sube de 0,002 % a 0,019 % al pasar de EPSS 0 a 0,37. **Los dos modelos se apoyan sobre todo en lo reciente que es el CVE, y el HGB además en la CNA** (que la logística casi no usa).
Límite: la importancia mide la influencia en el modelo, no que la antigüedad, la CNA o EPSS causen la explotación; la antigüedad puede ser un sustituto de «aún sin catalogar».

## 6. Veredicto de la fase (qué se puede y qué no afirmar)

1. **Afirmable:** con datos hasta cada foto, un modelo logístico simple ordena los CVE que entrarán a KEV en 90 días mejor que EPSS y CVSS solos (ROC-AUC 0,89 frente a 0,68 y 0,71; detecta 42 de 105
   eventos revisando el 1 % frente a 16 de EPSS). La mejora es significativa tras Holm y resiste el bootstrap por clúster de CVE y por bloques de meses.
2. **No afirmable:** que la logística supere al random forest o al HGB (p Holm ≥ 0,056; las cifras de árboles dependen de la semilla); que las probabilidades estén bien calibradas (O/E 0,55 a 0,85, HL rechaza);
   que el modelo anticipe con precisión (cobertura al 1 % de 22 a 31 %, con IC de ±9 pp); que la PR-AUC mensual sea estable.
3. **Utilidad práctica:** moderada (+13 pp de cobertura al 1 % frente a EPSS con IC [0,5; 25]); solo la logística cumple el criterio D5 con IC que excluye cero.
4. Resultado negativo a conservar: el HGB, con búsqueda de hiperparámetros, eligió los valores por defecto y no mejoró; el RF depende de la semilla; la probabilidad calibrada no mejora al Brier de la tasa base.

## 7. Pendiente

- Plan completo: más pruebas de Optuna y 3 a 5 semillas **dentro** de la búsqueda (aquí las semillas solo varían el reajuste final), horizontes 30 y 180, ventana deslizante, estudio con el TPE corregido para RF.
- Calibración recurrente (reentrenamiento mensual) no evaluada; solo recalibración con la mitad reciente de validación.
- Estos resultados dependen de una sola partición temporal de 6 meses; no hay validación externa.
- La explicabilidad es de un ajuste (semilla 7); no se estudió su estabilidad.
