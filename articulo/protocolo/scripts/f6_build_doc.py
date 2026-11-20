"""Fase 6 · genera la sección del Laboratorio (Materiales y métodos + Resultados y discusión) como .docx con figuras y tablas.
Todas las cifras de tablas y figuras salen de resultados/f4 y resultados/f5. Uso (contenedor, con python-docx y matplotlib):
  docker compose run --rm -T -e PYTHONPATH=/srv -v <repo>/backend/app:/srv/app -v <repo>/articulo/protocolo:/proto backend python /proto/scripts/f6_build_doc.py"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from sklearn.metrics import roc_curve

from app.ml.metrics import recall_at

P = Path("/proto")
R4, R5 = P / "resultados/f4", P / "resultados/f5"
OUT = P / "F6_Laboratorio_metodos_resultados.docx"
FIG = P / "figuras"
FIG.mkdir(exist_ok=True)


def J(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


E = {n: J(R4 / f"{n}.json") for n in ("emb_logreg", "emb_random_forest", "emb_hgb", "emb_hgb_con_version", "emb_hgb_sin_epss", "emb_hgb_sin_cvss",
                                       "emb_logreg_tpe5", "emb_hgb_tpe5")}
CT, S, MC, CAL, STAB, SEED, EXP = (J(R4 / "controls.json"), J(R5 / "stats.json"), J(R5 / "mcnemar_events.json"), J(R5 / "calibration.json"),
                                    J(R5 / "stability.json"), J(R5 / "seeds.json"), J(R5 / "explain.json"))
SPL = E["emb_logreg"]["dataset"]["splits"]
NAMES = {"logreg": "Regresión logística", "random_forest": "Bosque aleatorio", "hgb": "Gradient boosting (histogramas)", "epss": "EPSS", "cvss": "CVSS de la CNA"}
COL = {"logreg": "#0b5cad", "random_forest": "#b64400", "hgb": "#2e7d32", "epss": "#6e6e73", "cvss": "#9e9e9e"}


def f(x: float | None, d: int = 2) -> str:
    x = x if x is None else x + (1e-9 if x >= 0 else -1e-9)  # redondeo «mitad hacia fuera» (0,6775 → 0,678), no el binario
    return "—" if x is None else f"{x:,.{d}f}".replace(",", " ").replace(".", ",") if abs(x) >= 1000 else f"{x:.{d}f}".replace(".", ",")


def pct(x: float, d: int = 1) -> str:
    return f(100 * x, d) + " %"


def ci(lo: float, hi: float, d: int = 3) -> str:
    return f"[{f(lo, d)}; {f(hi, d)}]"


# ------------------------------------------------------------------ figuras
def fig_partition() -> Path:
    shots = pd.date_range("2023-04-01", "2026-08-01", freq="MS")
    kind = {}
    for sp, k in (("desarrollo", "Desarrollo"), ("validacion", "Validación"), ("prueba", "Prueba")):
        for d in pd.date_range(SPL[sp]["first"], SPL[sp]["last"], freq="MS"):
            kind[d] = k
    fig, ax = plt.subplots(figsize=(8.2, 2.1))
    colors = {"Desarrollo": "#0b5cad", "Validación": "#2e7d32", "Prueba": "#b64400"}
    for i, d in enumerate(shots):
        k = kind.get(d, "Excluida")
        ax.bar(i, 1, width=0.82, color=colors.get(k, "white"), edgecolor="#555555" if k == "Excluida" else colors[k], hatch="////" if k == "Excluida" else None, linewidth=0.6)
    ax.set_xticks([i for i, d in enumerate(shots) if d.month in (1, 7) or i == 0])
    ax.set_xticklabels([f"{d:%Y-%m}" for i, d in enumerate(shots) if d.month in (1, 7) or i == 0], fontsize=7)
    ax.set_yticks([])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors.values()] + [plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="#555555", hatch="////")]
    ax.legend(handles, [f"{k} ({SPL[s]['snapshots']} fotos)" for k, s in zip(colors, ("desarrollo", "validacion", "prueba"), strict=True)] + ["Excluidas por embargo (4)"],
              ncol=4, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, 1.38), frameon=False)
    ax.set_xlabel("Foto mensual (fecha S; etiqueta = ingreso a KEV en (S, S+90 d])", fontsize=8)
    fig.tight_layout()
    p = FIG / "fig7_particion_embargo.png"
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_curves() -> Path:
    preds = {k: pd.read_csv(R4 / f"{n}.preds.csv.gz") for k, n in (("logreg", "emb_logreg"), ("random_forest", "emb_random_forest"), ("hgb", "emb_hgb"))}
    t = {k: p[p["split"] == "prueba"].reset_index(drop=True) for k, p in preds.items()}
    ref = t["logreg"]
    y, w = ref["label"].to_numpy(), ref["weight"].to_numpy()
    sc = {k: v["score"].to_numpy() for k, v in t.items()} | {"epss": ref["baseline_epss"].to_numpy(), "cvss": ref["baseline_cvss"].to_numpy()}
    fig, (a, b) = plt.subplots(1, 2, figsize=(8.2, 3.3))
    grid = np.geomspace(0.001, 0.3, 40)
    for k, s in sc.items():
        a.plot(100 * grid, [100 * (recall_at(y, s, w, g) or 0) for g in grid], label=NAMES[k], color=COL[k], lw=1.8 if k == "logreg" else 1.2)
        fpr, tpr, _ = roc_curve(y, s, sample_weight=w)
        b.plot(fpr, tpr, color=COL[k], lw=1.8 if k == "logreg" else 1.2)
    a.plot(100 * grid, 100 * grid, "k:", lw=0.8, label="Azar")
    b.plot([0, 1], [0, 1], "k:", lw=0.8)
    a.set_xscale("log")
    a.set_xlabel("Hallazgos revisados (% del universo, escala log.)", fontsize=8)
    a.set_ylabel("Cobertura de filas positivas (%)", fontsize=8)
    a.set_title("(a) Cobertura frente a esfuerzo", fontsize=9)
    b.set_xlabel("Tasa de falsos positivos", fontsize=8)
    b.set_ylabel("Tasa de verdaderos positivos", fontsize=8)
    b.set_title("(b) Curva ROC", fontsize=9)
    for ax in (a, b):
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25)
    a.legend(fontsize=6.5, frameon=False)
    fig.tight_layout()
    p = FIG / "fig8_cobertura_roc_prueba.png"
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_monthly() -> Path:
    fig, ax = plt.subplots(figsize=(8.2, 3.0))
    x = np.arange(len(STAB))
    for k, off in (("logreg", -0.27), ("hgb", 0.0), ("epss", 0.27)):
        ax.bar(x + off, [r[k]["roc_auc"] for r in STAB], width=0.26, color=COL[k], label=NAMES[k])
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['snapshot'][:7]}\n{r['events']} eventos" for r in STAB], fontsize=7)
    ax.axvline(3.5, color="#b64400", lw=0.9, ls="--")
    ax.text(3.55, 1.0, "EPSS v2026.06.15 →", fontsize=7, color="#b64400", va="top")
    ax.set_ylim(0.4, 1.0)
    ax.set_ylabel("ROC-AUC", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0.0, 1.0))
    fig.tight_layout()
    p = FIG / "fig9_estabilidad_mensual.png"
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


def fig_importance() -> Path:
    groups = ["EPSS", "Antigüedad del CVE", "CVSS de la CNA", "CNA (quién publicó)", "Exploits públicos", "Historial KEV de la CNA", "Tipo de debilidad (CWE)"]
    vals = {m: {r["name"]: r["mean"] for r in EXP[m]["importance"]["rows"] if r["kind"] == "grupo"} for m in ("logreg", "hgb")}
    fig, ax = plt.subplots(figsize=(8.2, 3.2))
    y = np.arange(len(groups))
    for m, off in (("logreg", -0.19), ("hgb", 0.19)):
        ax.barh(y + off, [vals[m].get(g, 0.0) for g in groups], height=0.36, color=COL[m], label=NAMES[m])
    ax.set_yticks(y)
    ax.set_yticklabels(groups, fontsize=7.5)
    ax.invert_yaxis()
    ax.axvline(0, color="black", lw=0.6)
    ax.set_xlabel("Caída del ROC-AUC en prueba al desordenar el grupo (importancia por permutación)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    fig.tight_layout()
    p = FIG / "fig10_importancia_grupos.png"
    fig.savefig(p, dpi=300)
    plt.close(fig)
    return p


# ------------------------------------------------------------------ documento
doc = Document()
st = doc.styles["Normal"]
st.font.name, st.font.size = "Times New Roman", Pt(11)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
for sec in doc.sections:
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin = sec.bottom_margin = Cm(2.5)


def head(text: str, level: int = 1) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.italic = level == 3
    r.font.size = Pt(13 if level == 1 else 11.5 if level == 2 else 11)
    p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(10), Pt(4)
    p.paragraph_format.keep_with_next = True


def para(text: str) -> None:
    p = doc.add_paragraph(text)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.first_line_indent = Cm(0.6)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def note(text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run("Nota. ")
    r.italic = True
    r.font.size = Pt(9)
    r2 = p.add_run(text)
    r2.font.size = Pt(9)
    p.paragraph_format.space_after = Pt(10)


def caption(text: str) -> None:
    p = doc.add_paragraph(text)
    p.runs[0].font.size = Pt(10)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True


def table(rows: list[list[str]], widths: list[float] | None = None) -> None:
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.text = ""
            r = c.paragraphs[0].add_run(val)
            r.font.size = Pt(8.5)
            r.bold = i == 0
            c.paragraphs[0].paragraph_format.space_after = Pt(0)
            if j > 0:
                c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            tcPr = c._tc.get_or_add_tcPr()
            b = OxmlElement("w:tcBorders")
            for edge in ("top", "bottom") if i not in (0,) else ("top", "bottom"):
                e = OxmlElement(f"w:{edge}")
                e.set(qn("w:val"), "single" if i in (0, len(rows) - 1) or edge == "bottom" and i == 0 else "nil")
                e.set(qn("w:sz"), "6")
                b.append(e)
            tcPr.append(b)
    if widths:
        for row in t.rows:
            for c, wd in zip(row.cells, widths, strict=False):
                c.width = Cm(wd)


def figure(path: Path, cap: str, width: float = 15.5) -> None:
    doc.add_picture(str(path), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(cap)


ab = S["absolute_with_ci"]
va = S["vs_baselines"] + S["vs_selected"]
VP = {(r["a"], r["b"]): r for r in va}
lr_params = E["emb_logreg"]["best_params"]
rf_params = E["emb_random_forest"]["best_params"]
nrows = sum(SPL[k]["rows"] for k in SPL)
npos = sum(SPL[k]["positive_rows"] for k in SPL)
nev = sum(SPL[k]["events"] for k in SPL)
env = E["emb_logreg"]["environment"]
sha = E["emb_logreg"]["dataset"]["sha256"]
test_ev = S["events_test"]
b1, b5 = MC["1pct"]["detected"], MC["5pct"]["detected"]
tp5 = E["emb_logreg_tpe5"]["best_params"]["C"]

# ======================= MATERIALES Y MÉTODOS =======================
head("Materiales y métodos (adición): laboratorio de modelos predictivos", 1)
head("Pregunta, alcance y principio de aislamiento", 2)
para("Además de la priorización determinista, se evaluó de forma separada si un modelo entrenado con datos públicos disponibles hasta cada fecha puede anticipar qué CVE que "
     "aún no están en KEV ingresarán al catálogo en los 90 días siguientes (clasificación binaria, P5). El módulo no alimenta el cruce, el puntaje de riesgo ni las alertas de "
     "la plataforma: opera sobre el universo completo de CVE publicados, no sobre el inventario de la organización, y su único producto es una evaluación. Se eligió un horizonte "
     "principal de 90 d y se reservó un análisis de sensibilidad a 30 y 180 d, que no se ejecutó (véase Validez y limitaciones).")
head("Fuentes de datos y unidad de análisis", 2)
para(f"Se emplearon cuatro fuentes públicas: el catálogo KEV (CISA, s. f.), los archivos diarios completos de EPSS (FIRST, s. f.), los feeds anuales del NVD en formato CVE 2.0 "
     f"(NIST, s. f.) y los metadatos de Exploit-DB (OffSec, s. f.). La unidad de análisis fue el par CVE × foto mensual: en la fecha S (primer día de cada mes, de abril de 2023 a agosto de 2026, "
     f"41 fotos) se consideraron los CVE aún ausentes de KEV, y la etiqueta fue 1 si ingresaban a KEV en el intervalo (S, S + 90 d]. De cada fuente se registraron la URL, la fecha de descarga, "
     f"el SHA-256 y la licencia. Los negativos se muestrearon al azar con una tasa de 5 % y semilla fija, y cada uno recibió el peso 20 (el inverso de la tasa) para recuperar la prevalencia real "
     f"(0,0092 %). El dataset resultante tuvo {f(nrows, 0)} filas, {npos} filas positivas y {nev} eventos únicos (CVE distintos que ingresaron a KEV), porque un mismo CVE queda etiquetado "
     f"positivo en todas las fotos cuya ventana lo contiene. Esta diferencia importa: el tamaño muestral efectivo es el de eventos, no el de filas.")
head("Variables y control de fuga de información", 2)
para("Se usaron 14 variables calculables en la fecha S: probabilidad y percentil de EPSS, su cambio frente a la foto anterior y la versión del modelo EPSS; el CVSS base y sus componentes de vector "
     "(vector de ataque, complejidad, privilegios e interacción), solo si los publicó la propia CNA; el tipo de debilidad (CWE) declarado por la CNA, la CNA, los días desde la publicación, "
     "los exploits de Exploit-DB con fecha de alta anterior a S y el número de CVE de la misma CNA ya presentes en KEV en S. En el conjunto principal se excluyó el grupo «versión de EPSS» "
     "(versión y cambio frente a la foto previa), porque la escala de EPSS cambia entre versiones. Se descartaron por fuga las evaluaciones SSVC de CISA (el feed solo conserva la última y "
     "su ausencia delataba la etiqueta: el 99,5 % de los positivos aparecía «sin evaluar» frente al 62 % del resto), el CVSS y el CWE asignados por el NVD o por CISA ADP con posterioridad a la "
     "publicación, el número de referencias del NVD (estado actual) y los módulos de Metasploit (solo traen la fecha de modificación).")
head("Partición temporal con embargo", 2)
para(f"La partición se hizo por fotos en orden cronológico, nunca por filas, con un embargo igual al horizonte (López de Prado, 2018): una foto pertenece a un bloque solo si su ventana de etiqueta "
     f"termina antes del inicio del bloque siguiente (S + 90 d ≤ inicio). Las fotos que no cumplen se excluyeron de todos los conjuntos. Con 41 fotos quedaron "
     f"{SPL['desarrollo']['snapshots']} de desarrollo ({SPL['desarrollo']['first'][:7]} a {SPL['desarrollo']['last'][:7]}), {SPL['validacion']['snapshots']} de validación "
     f"({SPL['validacion']['first'][:7]} a {SPL['validacion']['last'][:7]}), {SPL['prueba']['snapshots']} de prueba ({SPL['prueba']['first'][:7]} a {SPL['prueba']['last'][:7]}) y 4 excluidas "
     f"(Figura 7; Tabla 7), es decir, 67,6 %, 16,2 % y 16,2 %, no el 70/15/15 nominal, porque el embargo consume fotos. El conjunto de prueba se usó una sola vez, sin intervenir en la elección del "
     f"modelo, del umbral, de la calibración ni de los hiperparámetros. El umbral de operación (revisar el 1 % o el 5 % del universo) se fijó en validación y se aplicó en prueba. "
     f"La auditoría previa del procedimiento había detectado que, sin embargo, las etiquetas de entrenamiento incluían eventos posteriores al inicio de la validación.")
head("Modelos, preparación y optimización de hiperparámetros", 2)
para("Se compararon tres algoritmos de scikit-learn 1.9.1 (Pedregosa et al., 2011): regresión logística con penalización L2, bosque aleatorio y gradient boosting con histogramas. Las variables numéricas de cola larga "
     "se transformaron con logaritmo, las categorías con menos de 20 filas se agruparon en «otras» y los datos ausentes se imputaron con la mediana más un indicador (logística) o se trataron de forma "
     "nativa (boosting). Los pesos de muestreo se pasaron como pesos de fila y se descartó el balanceo adicional de clases, porque corregiría dos veces el desbalance. Cada algoritmo tuvo su propio espacio "
     "de búsqueda con a lo sumo cuatro hiperparámetros, dado el número de eventos (Tabla 8). El número de árboles del bosque se fijó en 300; en el boosting, el número de iteraciones lo decidió una "
     "parada anticipada propia que mide la log-loss ponderada en el último 20 % de las fotos de entrenamiento (con embargo), con paciencia de 20 iteraciones y tolerancia relativa de 10⁻⁴, porque la parada "
     "interna de la biblioteca usa una fracción aleatoria que mezclaría fotos de distintas fechas. No se aplicaron épocas, calendarios de tasa de aprendizaje, transferencia de aprendizaje ni "
     "sobremuestreo sintético, por no corresponder a estos modelos y a variables categóricas de alta cardinalidad.")
para("La búsqueda se hizo con Optuna (Akiba et al., 2019) con muestreador TPE (Bergstra et al., 2011) con semilla, poda por mediana tras cada pliegue interno y 10 pruebas por búsqueda; la prueba 0 fue "
     "la configuración por defecto. Con 10 pruebas y 10 iniciales aleatorias, el TPE del plan principal equivale en la práctica a una búsqueda aleatoria; una repetición de la logística y del boosting "
     f"con 5 pruebas iniciales dio un resultado equivalente (C = {f(tp5, 4)}; mismos hiperparámetros del boosting).")
head("Validación cruzada temporal anidada", 2)
para("Dentro de desarrollo se aplicó una validación cruzada anidada de ventana expansiva con 4 pliegues externos (bloques de validación de 3 fotos) y, dentro de cada uno, 2 pliegues internos (bloques de 2 fotos), "
     "con el mismo embargo de 90 d entre el entrenamiento y el bloque de evaluación de cada pliegue (Bergmeir y Benítez, 2012). El diseño habitual de 5 × 3 no cabía con embargo. Cada pliegue externo "
     "reentrenó con los mejores hiperparámetros de la búsqueda interna y se evaluó una sola vez; los pliegues sin positivos se habrían excluido y registrado (no hubo ninguno). Esta validación cruzada, "
     "que vive dentro de desarrollo, no equivale a la partición de validación (15 %), que sirvió para elegir el modelo, el umbral y la calibración.")
head("Métricas, líneas base y criterio de elección", 2)
para("Se usaron como líneas base EPSS solo, CVSS de la CNA solo y el orden aleatorio. Las métricas fueron el área bajo la curva de precisión-exhaustividad (PR-AUC; Davis y Goadrich, 2006; Saito y Rehmsmeier, 2015) y "
     "el área bajo la curva ROC (ROC-AUC; Hanley y McNeil, 1982), ambas ponderadas por el peso de cada fila; la cobertura (exhaustividad) de las filas positivas al revisar el 1 % y el 5 % del universo ponderado; "
     "la razón de mejora (lift) frente a la prevalencia; el número de eventos detectados con el umbral fijado en validación; y el índice de Brier frente al de predecir la tasa base (Brier, 1950). "
     "El modelo se eligió por la PR-AUC en validación.")
head("Análisis estadístico", 2)
para(f"La incertidumbre se estimó con bootstrap por conglomerados de CVE (Efron y Tibshirani, 1993), con {S['n_boot']} remuestreos estratificados por CVE con evento, porque las filas de un mismo CVE no son "
     "independientes; las comparaciones entre métodos usaron el mismo remuestreo (diferencias pareadas) y valores p bilaterales corregidos con el método de Holm (1979) en dos familias: las seis comparaciones de "
     "cada modelo con las líneas base y las dos comparaciones de la logística con los otros modelos. Como análisis de sensibilidad se remuestrearon bloques de dos meses (300 remuestreos). En el punto de "
     "operación se aplicó la prueba de McNemar (1947) a nivel de evento: un CVE positivo contó como detectado si alguna de sus filas de prueba superaba el umbral. Sobre los 4 pliegues externos se aplicaron "
     "la prueba de Friedman (Demšar, 2006) y la de Wilcoxon (1945), cuya potencia es mínima: con 4 pares el menor valor p exacto bilateral es 0,125, de modo que solo se interpretaron de forma descriptiva. "
     "Se fijó antes de ver la prueba un criterio de utilidad práctica: una cobertura al 1 % al menos 5 puntos porcentuales mayor que la de EPSS y una PR-AUC al menos el doble. "
     "La sensibilidad a la semilla se midió reajustando cinco veces el modelo final con los hiperparámetros elegidos.")
head("Calibración y explicabilidad", 2)
para("Las probabilidades se calibraron en validación con el método de Platt (1999) y con regresión isotónica (Zadrozny y Elkan, 2002); la elección se hizo por la log-loss de dos pliegues temporales dentro de "
     "la validación, y la isotónica solo se admitió con al menos 50 eventos. En prueba se verificaron la razón observado/esperado (O/E), la pendiente de calibración con intervalos bootstrap, el estadístico "
     "de Hosmer y Lemeshow (1980) y el índice de Brier. La explicabilidad se calculó solo en prueba y en la escala original de las variables, con importancia por permutación (caída del ROC-AUC al desordenar un grupo "
     "de variables), coeficientes de la regresión logística y atribución por oclusión.")
head("Reproducibilidad", 2)
para(f"Cada experimento se ejecutó con un comando a partir de un archivo de configuración y escribió un archivo de resultados con la configuración, la semilla (7), las versiones de las bibliotecas "
     f"(Python {env['python']}, scikit-learn {env['sklearn']}, Optuna {env['optuna']}, NumPy {env['numpy']}, pandas {env['pandas']}), el hardware visible ({env['cpu_count']} hilos en WSL 2), los tiempos, los pliegues, "
     f"las pruebas de Optuna, las métricas y el SHA-256 del dataset ({sha[:16]}…) y de las predicciones. Las cifras de las tablas y figuras de este apartado se generaron directamente de esos archivos. "
     f"Las pruebas automatizadas se ejecutaron sin fallos (282 en el backend y 64 en el frontend).")

# ---- Tabla 7 y 8
head("Resultados y discusión (adición): anticipación del ingreso a KEV con modelos entrenados (P5)", 1)
head("Datos y partición", 2)
para(f"La Tabla 7 resume el dataset. Los {nev} eventos se repartieron en {SPL['desarrollo']['events']} para desarrollo, {SPL['validacion']['events']} para validación y {SPL['prueba']['events']} para prueba; "
     f"las filas positivas ({npos}) sobreestiman esa cifra porque un evento aparece en hasta tres fotos. La versión de EPSS cambió durante el periodo: 24 de las 25 fotos de desarrollo usaron la versión "
     f"v2023.03.01, mientras la validación y 4 fotos de prueba usaron la v2025.03.14 y 2 de prueba la v2026.06.15, de modo que el modelo se entrenó con una escala de EPSS distinta de la que enfrentó en la prueba.")
caption("Tabla 7. Dataset del laboratorio y partición temporal con embargo de 90 d.")
rows = [["Partición", "Fotos", "Periodo (primera–última)", "Filas", "Filas positivas", "Eventos únicos"]]
for sp, lab in (("desarrollo", "Desarrollo"), ("validacion", "Validación"), ("prueba", "Prueba")):
    s_ = SPL[sp]
    rows.append([lab, str(s_["snapshots"]), f"{s_['first'][:7]} – {s_['last'][:7]}", f(s_["rows"], 0), str(s_["positive_rows"]), str(s_["events"])])
rows.append(["Excluidas por embargo", "4", "2025-05, 2025-06, 2026-01, 2026-02", "—", "—", "—"])
rows.append(["Total", "41", "2023-04 – 2026-08", f(nrows, 0), str(npos), f"{nev}"])
table(rows, [3.4, 1.4, 4.6, 2.0, 2.4, 2.4])
note("Los negativos se muestrearon al 5 % y pesan 20; los eventos únicos son CVE distintos con etiqueta positiva. Los 424 eventos son CVE distintos: ninguno es positivo en dos particiones (la suma por partición coincide con el total de CVE positivos únicos). "
     "Elaboración propia a partir de los archivos de resultados del laboratorio.")
figure(fig_partition(), "Figura 7. Partición temporal con embargo. Las fotos rayadas se excluyeron porque su ventana de etiqueta de 90 d llega al bloque siguiente.")

caption("Tabla 8. Espacios de búsqueda e hiperparámetros elegidos.")
rows = [["Algoritmo", "Hiperparámetro", "Rango (escala)", "Elegido"],
        ["Regresión logística", "C (inverso de la regularización L2)", "10⁻⁴ a 1 (log.)", f(lr_params["C"], 4)],
        ["Bosque aleatorio", "Profundidad máxima", "3 a 16", str(rf_params["max_depth"])],
        ["", "Hoja mínima", "5 a 200 (log.)", str(rf_params["min_samples_leaf"])],
        ["", "Variables por división", "{√p; 0,3}", str(rf_params["max_features"]).replace(".", ",")],
        ["Gradient boosting", "Tasa de aprendizaje", "0,01 a 0,2 (log.)", f(E["emb_hgb"]["best_params"]["learning_rate"], 2)],
        ["", "Hojas máximas", "4 a 31", str(E["emb_hgb"]["best_params"]["max_leaf_nodes"])],
        ["", "Hoja mínima", "20 a 500 (log.)", str(E["emb_hgb"]["best_params"]["min_samples_leaf"])],
        ["", "Regularización L2", "10⁻³ a 10 (log.)", f(E["emb_hgb"]["best_params"]["l2_regularization"], 1)],
        ["", "Iteraciones (parada anticipada)", "tope 500", str(E["emb_hgb"]["best_iter"])]]
table(rows, [3.4, 5.6, 3.4, 2.4])
note(f"Los árboles del bosque se fijaron en 300. El boosting eligió los valores por defecto (prueba 0). El bosque terminó cerca del borde del rango (profundidad 15 de 16; hoja 7 de 5 a 200); no se "
     f"amplió el rango. De 50 pruebas por modelo se podaron entre {min(E[k]['trials_pruned'] for k in ('emb_logreg', 'emb_random_forest', 'emb_hgb'))} y "
     f"{max(E[k]['trials_pruned'] for k in ('emb_logreg', 'emb_random_forest', 'emb_hgb'))}.")

# ---- resultados principales
head("Desempeño en el conjunto de prueba", 2)
lp, ro = ab["logreg"], ab["epss"]
para(f"El criterio pactado (PR-AUC en validación) eligió la regresión logística. En prueba, con {test_ev} eventos, obtuvo un ROC-AUC de {f(lp['roc_auc']['point'], 3)} {ci(*lp['roc_auc']['ci'])}, frente a "
     f"{f(ro['roc_auc']['point'], 3)} {ci(*ro['roc_auc']['ci'])} de EPSS y {f(ab['cvss']['roc_auc']['point'], 3)} {ci(*ab['cvss']['roc_auc']['ci'])} de CVSS (Tabla 9; Figura 8). Al revisar el 1 % del universo, el umbral "
     f"fijado en validación detectó {b1['logreg']} de los {test_ev} eventos con la logística y {b1['epss']} con EPSS; al 5 %, {b5['logreg']} frente a {b5['epss']}. La PR-AUC fue de {f(lp['pr_auc']['point'], 4)}, "
     f"{f(lp['pr_auc']['point'] / ro['pr_auc']['point'], 0)} veces la de EPSS y unas 90 veces la del azar (0,00009), pero su intervalo es muy amplio {ci(*lp['pr_auc']['ci'], 4)} y asimétrico, por lo que "
     f"no debe leerse como una cifra puntual. Los tres modelos entrenados superaron a EPSS y a CVSS; la cobertura al 1 % (de 22 % a 31 %) muestra que el orden mejora mucho, pero que la anticipación sigue "
     f"siendo imprecisa.")
caption("Tabla 9. Desempeño en el conjunto de prueba (2026-03 a 2026-08; 105 eventos).")
rows = [["Método", "PR-AUC [IC 95 %]", "ROC-AUC [IC 95 %]", "Cobertura 1 % [IC]", "Cobertura 5 % [IC]", "Eventos detectados 1 % / 5 %"]]
for k in ("logreg", "random_forest", "hgb", "epss", "cvss"):
    a = ab[k]
    rows.append([NAMES[k], f"{f(a['pr_auc']['point'], 4)} {ci(*a['pr_auc']['ci'], 4)}", f"{f(a['roc_auc']['point'], 3)} {ci(*a['roc_auc']['ci'], 3)}",
                 f"{pct(a['recall_1pct']['point'])} {ci(100 * a['recall_1pct']['ci'][0], 100 * a['recall_1pct']['ci'][1], 1)}",
                 f"{pct(a['recall_5pct']['point'])} {ci(100 * a['recall_5pct']['ci'][0], 100 * a['recall_5pct']['ci'][1], 1)}", f"{b1[k]} / {b5[k]}"])
table(rows, [3.0, 3.2, 3.2, 3.0, 3.0, 2.2])
note(f"IC: intervalo percentil de {S['n_boot']} remuestreos por conglomerados de CVE. Cobertura: fracción de filas positivas en el 1 % o 5 % superior del universo ponderado. Eventos detectados: CVE positivos con alguna "
     "fila sobre el umbral fijado en validación. PR-AUC del azar: 0,00009. Modelo elegido en validación: regresión logística; un solo ajuste con la semilla 7.")
figure(fig_curves(), "Figura 8. (a) Cobertura frente a esfuerzo y (b) curva ROC en prueba. La línea punteada es el orden aleatorio.")

head("Comparaciones estadísticas", 2)
lr_e, lr_c = VP[("logreg", "epss")], VP[("logreg", "cvss")]
lr_rf, lr_hg = VP[("logreg", "random_forest")], VP[("logreg", "hgb")]
para(f"Las diferencias pareadas confirmaron que los tres modelos superaron a EPSS y a CVSS en ROC-AUC y PR-AUC con valores p corregidos por Holm menores que 0,05 (Tabla 10); frente a EPSS, la logística ganó "
     f"{f(lr_e['roc_auc']['diff'], 3)} {ci(*lr_e['roc_auc']['ci'])} de ROC-AUC y {f(100 * lr_e['recall_1pct']['diff'], 1)} puntos porcentuales {ci(100 * lr_e['recall_1pct']['ci'][0], 100 * lr_e['recall_1pct']['ci'][1], 1)} "
     f"de cobertura al 1 %. En cambio, entre los propios modelos no hubo diferencia significativa tras la corrección (p de Holm de {f(lr_rf['roc_auc']['p_holm'], 3)} a {f(lr_rf['pr_auc']['p_holm'], 3)}), por lo que la elección de la "
     f"logística descansa en la parsimonia y en el criterio de validación, no en una superioridad demostrada. En el análisis por bloques de dos meses, solo la logística conservó una ventaja de PR-AUC sobre EPSS con "
     f"intervalo que excluye 0 {ci(*S['block_bootstrap_vs_epss']['logreg']['pr_auc']['ci'], 4)}. A nivel de evento, la prueba de McNemar mostró que la logística detectó más eventos que EPSS al 1 % ({MC['1pct']['pairs']['logreg_vs_epss']['only_a']} "
     f"frente a {MC['1pct']['pairs']['logreg_vs_epss']['only_b']} detectados solo por uno de los dos, p = {f(MC['1pct']['pairs']['logreg_vs_epss']['p'], 4)}) y al 5 % (p < 0,001), sin diferencia con el bosque ni con el boosting. "
     f"La prueba de McNemar por filas dio p = 0 en todos los casos porque cuenta falsos positivos de decenas de miles de filas, y se descartó. Con 4 pliegues externos, la prueba de Friedman rechazó la igualdad "
     f"(PR-AUC, p = {f(S['outer_folds']['pr_auc']['friedman']['p'], 3)}; ROC-AUC, p = {f(S['outer_folds']['roc_auc']['friedman']['p'], 3)}) con EPSS siempre en último lugar, pero la de Wilcoxon no puede ser significativa con 4 pares.")
u = S["practical_utility"]
para(f"Respecto del criterio de utilidad práctica fijado de antemano, solo la logística lo cumplió con un intervalo de la ganancia que excluye 0 ({f(u['logreg']['recall_1pct_gain_pp'], 1)} puntos porcentuales "
     f"{ci(*u['logreg']['ci_gain_pp'], 1)} y PR-AUC {f(u['logreg']['pr_auc_ratio_vs_epss'], 1)} veces la de EPSS); el boosting lo cumplió en el valor puntual, pero su intervalo incluye 0, y el bosque no lo cumplió. "
     "La significancia estadística es sólida en ROC-AUC y la utilidad práctica es moderada y frágil.")
caption("Tabla 10. Diferencias pareadas en prueba con corrección de Holm.")
rows = [["Comparación", "Δ ROC-AUC [IC 95 %]", "p (Holm)", "Δ PR-AUC [IC 95 %]", "p (Holm)", "Δ cobertura 1 % (pp) [IC]"]]
for a, b in (("logreg", "epss"), ("logreg", "cvss"), ("random_forest", "epss"), ("hgb", "epss"), ("logreg", "random_forest"), ("logreg", "hgb")):
    r = VP[(a, b)]
    rows.append([f"{NAMES[a].split(' (')[0]} − {NAMES[b].split(' (')[0]}", f"{f(r['roc_auc']['diff'], 3)} {ci(*r['roc_auc']['ci'])}", f(r["roc_auc"]["p_holm"], 3),
                 f"{f(r['pr_auc']['diff'], 4)} {ci(*r['pr_auc']['ci'], 4)}", f(r["pr_auc"]["p_holm"], 3),
                 f"{f(100 * r['recall_1pct']['diff'], 1)} {ci(100 * r['recall_1pct']['ci'][0], 100 * r['recall_1pct']['ci'][1], 1)}"])
table(rows, [3.4, 3.4, 1.4, 3.6, 1.4, 3.4])
note("Diferencias con el mismo remuestreo por conglomerados de CVE (500). Holm se aplicó en dos familias: seis comparaciones con líneas base y dos entre modelos. El valor p mínimo alcanzable con 500 remuestreos es 0,002.")

head("Estabilidad temporal y sensibilidad a la semilla", 2)
lr_m = [r["logreg"]["roc_auc"] for r in STAB]
sd = SEED
para(f"El ROC-AUC mensual de la logística se mantuvo entre {f(min(lr_m), 2)} y {f(max(lr_m), 2)} y superó al de EPSS en los seis meses, incluidos los dos meses con la versión v2026.06.15 de EPSS (Figura 9); "
     f"la PR-AUC mensual, en cambio, varió 40 veces (de {f(min(r['logreg']['pr_auc'] for r in STAB), 4)} a {f(max(r['logreg']['pr_auc'] for r in STAB), 4)}), lo que refleja el número reducido de eventos por mes "
     f"(de {min(r['events'] for r in STAB)} a {max(r['events'] for r in STAB)}). El bosque aleatorio, reajustado con cinco semillas, tuvo una PR-AUC en prueba con mediana {f(sd['random_forest']['summary_test']['pr_auc']['median'], 4)} "
     f"y rango {f(sd['random_forest']['summary_test']['pr_auc']['min'], 4)} a {f(sd['random_forest']['summary_test']['pr_auc']['max'], 4)}, es decir, una variación de 5,6 veces atribuible solo a la semilla, por lo que "
     f"no puede reportarse con una sola; el ROC-AUC fue más estable ({f(sd['random_forest']['summary_test']['roc_auc']['min'], 3)} a {f(sd['random_forest']['summary_test']['roc_auc']['max'], 3)}). "
     "La regresión logística es determinista.")
figure(fig_monthly(), "Figura 9. ROC-AUC por mes de prueba. La línea discontinua marca el cambio a la versión v2026.06.15 de EPSS.")

head("Calibración", 2)
cl, cr, ch = CAL["logreg"], CAL["random_forest"], CAL["hgb"]
para(f"Los modelos sobrestimaron la probabilidad en prueba (Tabla 11). La logística calibrada con Platt esperaba {f(cl['platt_test']['expected'], 0)} ingresos a KEV y se observaron {f(cl['platt_test']['observed'], 0)} "
     f"(O/E = {f(cl['platt_test']['oe'], 2)} {ci(cl['platt_test']['oe_lo'], cl['platt_test']['oe_hi'], 2)}); el bosque esperaba {f(cr['platt_test']['expected'], 0)} (O/E = {f(cr['platt_test']['oe'], 2)}). "
     f"La prevalencia de validación (0,00915 %) y de prueba (0,00919 %) fue casi idéntica, de modo que la deriva no es de prevalencia sino de la relación entre el puntaje y el evento. El estadístico de Hosmer y "
     f"Lemeshow rechazó el ajuste perfecto en los tres modelos. Recalibrar con la mitad reciente de la validación acercó la logística a O/E = {f(cl['comparison']['drift']['recalibrated_with_recent']['oe'], 2)}, sin eliminar el desajuste. "
     f"La habilidad de Brier frente a predecir la tasa base fue prácticamente nula (de {f(ch['platt_test']['brier_skill'], 4)} a {f(cl['platt_test']['brier_skill'], 4)}), lo esperable con una prevalencia de 0,009 %: el valor del modelo "
     "está en el orden de los CVE y no en la probabilidad individual.")
caption("Tabla 11. Calibración en prueba.")
rows = [["Modelo", "Calibrador elegido", "O/E con Platt [IC 95 %]", "Pendiente [IC 95 %]", "O/E con isotónica", "Habilidad de Brier"]]
for k, c in (("logreg", cl), ("random_forest", cr), ("hgb", ch)):
    t_ = c["platt_test"]
    rows.append([NAMES[k].split(" (")[0], "Platt" if c["comparison"]["choice"] == "platt" else "Isotónica", f"{f(t_['oe'], 2)} {ci(t_['oe_lo'], t_['oe_hi'], 2)}",
                 f"{f(t_['slope'], 2)} {ci(t_['slope_lo'], t_['slope_hi'], 2)}", f(c["comparison"]["test"]["isotonic"]["oe"], 2), f(t_["brier_skill"], 4)])
table(rows, [3.2, 2.4, 3.6, 3.6, 2.4, 2.4])
note("O/E: eventos observados entre esperados (1 = calibración perfecta; < 1 = sobrestimación). El calibrador se eligió por log-loss con dos pliegues temporales dentro de validación (80 eventos). "
     "Habilidad de Brier: 1 − Brier / Brier de predecir la tasa base.")

head("Ablación de grupos de variables", 2)
ab_rows = [["Variante del boosting", "ROC-AUC prueba", "PR-AUC prueba", "Cobertura 1 %"]]
for n, lab in (("emb_hgb", "Sin versión de EPSS (principal)"), ("emb_hgb_con_version", "Con versión de EPSS"), ("emb_hgb_sin_epss", "Sin EPSS"), ("emb_hgb_sin_cvss", "Sin CVSS de la CNA")):
    m = E[n]["final_metrics"]["prueba"]
    ab_rows.append([lab, f(m["roc_auc"], 3), f(m["pr_auc"], 4), pct(m["recall_1pct"])])
para("Con el boosting, quitar el CVSS de la CNA fue lo que más redujo el ROC-AUC (de 0,840 a 0,786); quitar EPSS lo redujo menos (0,819) y la PR-AUC incluso subió, una variación que con 105 eventos y una sola semilla "
     "es compatible con el ruido. Conservar o quitar la versión de EPSS cambió el ROC-AUC en 0,016; no hubo evidencia de que la decisión de excluirla ayude ni estorbe (Tabla 12).")
caption("Tabla 12. Ablación de grupos de variables con gradient boosting (una semilla).")
table(ab_rows, [6.0, 3.0, 3.0, 3.0])
note("Todas las variantes se ejecutaron con el mismo protocolo (CV 4 × 2 con embargo) y los mismos datos; las diferencias no se sometieron a prueba estadística.")

head("Explicabilidad", 2)
lg = EXP["logreg"]["importance"]
para("Los dos modelos se apoyaron sobre todo en la antigüedad del CVE (Figura 10). En la regresión logística, el grupo EPSS (caída del ROC-AUC de 0,101), la antigüedad (0,092) y el CVSS de la CNA (0,066) fueron los más influyentes, "
     "con coeficientes negativos para los días desde la publicación (−0,59) y positivos para el CVSS (0,54) y EPSS (0,48): los CVE más recientes, con mayor severidad y mayor probabilidad EPSS tuvieron más probabilidad de "
     "ingresar a KEV. El boosting dio más peso a la antigüedad (0,150) y a la CNA que publicó el CVE (0,063), que la logística casi no usa. Estas importancias miden la influencia en el modelo, no que la antigüedad, la CNA "
     "o EPSS causen la explotación; la antigüedad puede estar sustituyendo «aún no catalogado».")
figure(fig_importance(), "Figura 10. Importancia por permutación de grupos de variables en prueba (caída del ROC-AUC) para la regresión logística y el boosting.")

head("Resultados negativos y contraste con el análisis previo", 2)
para("Cuatro resultados negativos se conservaron. Primero, el efecto del embargo no fue consistente: con un control sobre un dataset sin embargo (mismos hiperparámetros, tres semillas), la logística casi no cambió, el bosque "
     "mejoró y el boosting empeoró en prueba, de modo que el efecto sobre las métricas es indistinguible del ruido aunque la fuga exista por construcción y se corrija por diseño. Segundo, la PR-AUC media de la validación "
     "cruzada no ordenó los modelos: puso primero al boosting (0,027), que quedó último en prueba por ROC-AUC. Tercero, la búsqueda de hiperparámetros del boosting no mejoró los valores por defecto. Cuarto, con una "
     "prevalencia tan baja, las probabilidades calibradas no mejoran al Brier de la tasa base. Frente a la evidencia citada en la Introducción, el resultado es coherente con la fiabilidad limitada de la predicción "
     "temprana (Iannone et al., 2024): el modelo ordena mejor que EPSS y CVSS, pero detecta el 40 % de los eventos al revisar el 1 % del universo y el 62 % al revisar el 5 %.")

# ======================= Referencias nuevas =======================
head("Referencias bibliográficas (adiciones)", 1)
refs = [
    "Akiba, T., Sano, S., Yanase, T., Ohta, T., y Koyama, M. (2019). Optuna: A next-generation hyperparameter optimization framework. En Proceedings of the 25th ACM SIGKDD International Conference on Knowledge Discovery & Data Mining (pp. 2623–2631). ACM. https://doi.org/10.1145/3292500.3330701",
    "Bergmeir, C., y Benítez, J. M. (2012). On the use of cross-validation for time series predictor evaluation. Information Sciences, 191, 192–213. https://doi.org/10.1016/j.ins.2011.12.028",
    "Bergstra, J., Bardenet, R., Bengio, Y., y Kégl, B. (2011). Algorithms for hyper-parameter optimization. En Advances in Neural Information Processing Systems 24 (pp. 2546–2554). Curran Associates.",
    "Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. Monthly Weather Review, 78(1), 1–3. https://doi.org/10.1175/1520-0493(1950)078<0001:VOFEIT>2.0.CO;2",
    "Cybersecurity and Infrastructure Security Agency. (s. f.). Known Exploited Vulnerabilities Catalog. https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    "Davis, J., y Goadrich, M. (2006). The relationship between precision-recall and ROC curves. En Proceedings of the 23rd International Conference on Machine Learning (pp. 233–240). ACM. https://doi.org/10.1145/1143844.1143874",
    "Demšar, J. (2006). Statistical comparisons of classifiers over multiple data sets. Journal of Machine Learning Research, 7, 1–30.",
    "Efron, B., y Tibshirani, R. J. (1993). An introduction to the bootstrap. Chapman & Hall.",
    "Forum of Incident Response and Security Teams. (s. f.). EPSS data and statistics. https://www.first.org/epss/data_stats",
    "Hanley, J. A., y McNeil, B. J. (1982). The meaning and use of the area under a receiver operating characteristic (ROC) curve. Radiology, 143(1), 29–36. https://doi.org/10.1148/radiology.143.1.7063747",
    "Holm, S. (1979). A simple sequentially rejective multiple test procedure. Scandinavian Journal of Statistics, 6(2), 65–70.",
    "Hosmer, D. W., y Lemeshow, S. (1980). Goodness of fit tests for the multiple logistic regression model. Communications in Statistics – Theory and Methods, 9(10), 1043–1069. https://doi.org/10.1080/03610928008827941",
    "López de Prado, M. (2018). Advances in financial machine learning. Wiley.",
    "McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. Psychometrika, 12(2), 153–157. https://doi.org/10.1007/BF02295996",
    "National Institute of Standards and Technology. (s. f.). National Vulnerability Database: Data feeds. https://nvd.nist.gov/vuln/data-feeds",
    "OffSec. (s. f.). Exploit Database. https://www.exploit-db.com",
    "Pedregosa, F., Varoquaux, G., Gramfort, A., Michel, V., Thirion, B., Grisel, O., Blondel, M., Prettenhofer, P., Weiss, R., Dubourg, V., Vanderplas, J., Passos, A., Cournapeau, D., Brucher, M., Perrot, M., y Duchesnay, É. (2011). Scikit-learn: Machine learning in Python. Journal of Machine Learning Research, 12, 2825–2830.",
    "Platt, J. C. (1999). Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods. En A. J. Smola, P. Bartlett, B. Schölkopf, y D. Schuurmans (Eds.), Advances in large margin classifiers (pp. 61–74). MIT Press.",
    "Saito, T., y Rehmsmeier, M. (2015). The precision-recall plot is more informative than the ROC plot when evaluating binary classifiers on imbalanced datasets. PLOS ONE, 10(3), e0118432. https://doi.org/10.1371/journal.pone.0118432",
    "Wilcoxon, F. (1945). Individual comparisons by ranking methods. Biometrics Bulletin, 1(6), 80–83. https://doi.org/10.2307/3001968",
    "Zadrozny, B., y Elkan, C. (2002). Transforming classifier scores into accurate multiclass probability estimates. En Proceedings of the 8th ACM SIGKDD International Conference on Knowledge Discovery and Data Mining (pp. 694–699). ACM. https://doi.org/10.1145/775047.775151",
]
for r in refs:
    p = doc.add_paragraph(r)
    p.paragraph_format.left_indent, p.paragraph_format.first_line_indent = Cm(1.0), Cm(-1.0)
    p.paragraph_format.space_after = Pt(4)
    for run in p.runs:
        run.font.size = Pt(10)
doc.save(OUT)
print("ok", OUT)
