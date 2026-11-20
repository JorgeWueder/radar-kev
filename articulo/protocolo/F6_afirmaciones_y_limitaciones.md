# Fase 6 · Entregable 11: afirmaciones del artículo previo que cambian, y limitaciones que subsisten

Base: `artículo mejorado v2.docx` (versión 2d21b73 del repositorio) y la sección nueva `F6_Laboratorio_metodos_resultados.docx`.
El artículo previo **no menciona el Laboratorio ni ningún modelo entrenado**: la sección nueva no corrige resultados anteriores, los **amplía** con una pregunta nueva (P5).
Por eso la mayoría de los cambios son de integración y de coherencia; solo tres afirmaciones se matizan por el contenido.

## A. Afirmaciones a modificar o completar

| # | Dónde (cita del artículo) | Qué dice hoy | Qué hacer y por qué |
|---|---|---|---|
| 1 | Resumen y Abstract: «el artefacto se verificó con 245 pruebas automatizadas» | 245 = 197 backend + 48 frontend (versión 2d21b73) | Actualizar al recuento de la versión final: la suite del backend tiene ahora 282 pruebas y la del frontend 64. **Fijar primero el commit** (hoy los cambios no están versionados). |
| 2 | Resumen: «Se concluyó que separar la decisión determinista de la explicación generativa mejoró la priorización a costa de una menor detección temprana» | Conclusión sin el laboratorio | Añadir una oración: un modelo logístico entrenado con datos hasta cada fecha ordenó mejor que EPSS y CVSS los CVE que ingresarían a KEV en 90 d (ROC-AUC 0,889 frente a 0,678 y 0,705; 42 de 105 eventos detectados al revisar el 1 % frente a 16 de EPSS), sin diferencia demostrada frente al bosque ni al boosting y con probabilidades sobrestimadas. |
| 3 | Introducción: «Se plantean cuatro preguntas: P1 … P4» y las contribuciones | Cuatro preguntas | Añadir **P5** («¿qué tan bien puede un modelo entrenado con datos disponibles a cada fecha anticipar el ingreso a KEV en 90 d, frente a EPSS y CVSS solos?») y una contribución: un protocolo de evaluación temporal con embargo, bootstrap por CVE y corrección por comparaciones múltiples. |
| 4 | Tipo y diseño: «un experimento de ordenamiento…, un diseño preexperimental…, pruebas técnicas dirigidas» | Tres componentes de evaluación | Añadir un cuarto: experimento predictivo temporal sobre fuentes públicas, aislado de la detección. |
| 5 | Espacio controlado: «GPU NVIDIA de 4 GB, procesador de seis núcleos y 16 GB de RAM» | Hardware declarado | Los archivos de resultados del laboratorio registran **16 hilos** (WSL 2). Confirmar el hardware real o aclarar que el laboratorio corrió en otra configuración. No se corrigió: es un dato que solo los autores conocen. |
| 6 | Pruebas técnicas y versiones: «190 pruebas de backend… versión 51836de» / «197… versión 2d21b73» | Recuentos y hashes de versiones previas | Añadir la versión final (con embargo, runner reproducible y suite actual) y dejar claro qué mediciones corresponden a cada versión. |
| 7 | Tabla 1 (matriz comparativa) | Sin fila del laboratorio | Añadir una fila: «Este estudio (laboratorio)»: predicción de ingreso a KEV a 90 d con validación temporal con embargo y calibración; brecha: validación en una sola partición. |
| 8 | **Resultados, «Cobertura prospectiva»**: «No se halló una mejora prospectiva frente a EPSS.» | Resultado negativo del puntaje determinista | **Se mantiene** para el puntaje con piso KEV sobre el inventario. Añadir que, en el universo completo de CVE y con un objetivo distinto, un modelo entrenado sí superó a EPSS en ROC-AUC y en cobertura al 1 % (+13 pp, IC [0,5; 25,3]). No debe presentarse como mejora de esa comparación: la población, la etiqueta y el horizonte son otros. |
| 9 | **Discusión**: «una cuota reservada de la capacidad para los CVE de mayor EPSS fuera de KEV es una alternativa que debe evaluarse» | Propuesta sin evidencia | Matizar: el laboratorio aporta evidencia exploratoria de que un modelo entrenado ordena mejor que EPSS solo; seguiría sin validarse en el inventario de la organización, y su cobertura al 1 % (22 a 31 %) indica que anticipa con poca precisión. |
| 10 | **Implicaciones**: «tratar la prioridad como una decisión de dos niveles» | Respaldo teórico | Puede citarse el laboratorio como apoyo, con la cautela anterior. |
| 11 | Validez, conclusión estadística: «el bootstrap de hallazgos trata como independientes observaciones que comparten CVE; un remuestreo por conglomerados ampliaría los intervalos» | Limitación del análisis original | Sigue siendo cierta para el corpus original (no se rehízo). Aclarar que el laboratorio sí usa remuestreo por conglomerados de CVE y que allí el IC de la PR-AUC fue muy asimétrico: no se midió cuánto lo amplía respecto del remuestreo por filas, por lo que no debe afirmarse una cifra. |
| 12 | Conclusiones: «Se recomienda… calibre los pesos optimizando la cobertura prospectiva» y el resto de trabajos futuros | Lista de trabajo futuro | Añadir: ampliar el laboratorio (horizontes 30 y 180 d, ventana deslizante, más semillas dentro de la búsqueda, validación externa) y recalibrar periódicamente. |
| 13 | Disponibilidad de datos | Datos del inventario confidenciales; repo 2d21b73 | El laboratorio usa solo fuentes públicas (KEV, EPSS, NVD, Exploit-DB): pueden publicarse la configuración, los SHA-256 y los archivos de resultados. Revisar la licencia de Exploit-DB (GPLv2; solo se usan metadatos) antes de redistribuir. Actualizar la versión del repositorio. |
| 13b | Palabras clave y abstract en inglés | Sin términos del laboratorio | Opcional: añadir «embargo temporal»/«temporal embargo», «calibración». |
| 14 | Referencias | 41 referencias previas | Añadir las 21 de `F6_Laboratorio_metodos_resultados.docx`. **Verificar cada DOI y página antes de enviar**: las incluí de memoria y no se consultaron en línea. |

## B. Afirmaciones que la sección nueva NO respalda (no deben escribirse)

1. Que el modelo entrenado supere al puntaje de la plataforma o lo sustituya: no se comparó con él (distinto universo y etiqueta).
2. Que la logística sea mejor que el bosque o el boosting: p de Holm 0,056 a 0,216; las cifras de árboles dependen de la semilla.
3. Que las probabilidades estén calibradas o sean utilizables en términos absolutos: O/E de 0,55 a 0,85 y habilidad de Brier casi nula.
4. Que el embargo «mejore» las métricas: el control sobre un dataset sin embargo no mostró un efecto consistente.
5. Que los hiperparámetros se optimizaron a fondo: 10 pruebas por búsqueda; el boosting conservó los valores por defecto.
6. Cualquier cifra de PR-AUC puntual como estable (varía 40 veces entre meses y 5,6 veces entre semillas en el bosque).
7. Que la importancia de variables indique causalidad.

## C. Limitaciones que subsisten (para «Validez y limitaciones»)

- **Una sola partición temporal** de 6 meses de prueba (105 eventos) y sin validación externa.
- **Deriva de EPSS:** el desarrollo es casi todo EPSS v2023.03.01 y la prueba usa v2025.03.14 y v2026.06.15; el modelo se evaluó en una escala distinta de la entrenada. La exclusión de la versión se decidió de antemano y no se demostró útil.
- **Etiqueta basada en KEV:** subestima la explotación no catalogada y depende del ritmo de CISA al catalogar.
- **Variables de un feed actual:** CVSS, CWE y CNA vienen de un estado reciente; una CNA pudo editarlos después de la fecha de la foto, y no se puede descartar. La validez de la ausencia de fuga se apoya en las exclusiones documentadas, no en versiones históricas de los feeds.
- **Pocos eventos y dependencia entre filas** (424 eventos únicos en 901 filas positivas): los IC son amplios y la PR-AUC es inestable.
- **Plan reducido:** una semilla en la búsqueda, 10 pruebas por búsqueda (TPE equivalente a búsqueda aleatoria), sin horizontes 30 y 180 d, sin ventana deslizante y sin reentrenamiento periódico.
- **Calibración:** todos los modelos sobrestiman en prueba; la recalibración con datos recientes solo mejora parcialmente.
- **Intervalos con modelo fijo:** los IC remuestrean la prueba pero no reentrenan el modelo, de modo que no incluyen la variabilidad del ajuste.
- **McNemar por evento** supone que «alguna fila sobre el umbral» define la detección; es una definición operativa.
- **El efecto del embargo** sobre las métricas no pudo aislarse: la fuga existe estructuralmente (ventanas que cruzan, CVE positivos en dos particiones en el dataset sin embargo), pero su magnitud medida es indistinguible del ruido.
- **Reproducibilidad condicionada:** las cifras dependen de las versiones de las bibliotecas registradas y de la semilla; el entorno es un contenedor en WSL 2.

## D. Antes de integrar

1. Crear el commit y fijar la versión del repositorio que se cite (hoy hay cambios sin versionar).
2. Verificar las referencias nuevas contra su fuente (DOI, páginas, años).
3. Confirmar el hardware (punto 5 de la tabla A).
4. Decidir si el laboratorio entra como P5 en el cuerpo o como apéndice (la sección está escrita para el cuerpo).
5. Si se repite alguna ejecución, regenerar el documento con `scripts/f6_build_doc.py`: todas las cifras de tablas y figuras salen de `resultados/f4` y `resultados/f5`.
