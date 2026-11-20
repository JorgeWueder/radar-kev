"""Reportes del Laboratorio de modelos (Fase 5): dataset, entrenamiento, evaluación y explicabilidad, en PDF, Word
(figuras a 600 DPI) y Excel. Leen lo mismo que la app (base de datos y cachés del laboratorio); no recalculan nada
pesado dentro de una descarga: si falta la evaluación o la explicación, piden calcularla primero en el laboratorio."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml import algorithms as algs
from app.ml import cache as mlcache
from app.ml.dataset import EXCLUDED, FEATURES
from app.models.ml import MlDataset, MlModel
from app.services.reports.model import Chart, Report, ReportError, Table, fmt_num

STATUS = {"ok": "Correcto", "warn": "Aviso", "info": "Información"}


def _n(v: float | None, digits: int = 4) -> str:
    return fmt_num(v, digits)


def _pct(v: float | None, digits: int = 0) -> str:
    return "—" if v is None else fmt_num(100 * v, digits, " %")


def _short(label: str) -> str:
    """Nombre corto para leyendas y tablas: sin «(histogramas)» ni «· N pruebas»; conserva «· sin EPSS/CVSS»."""
    parts = [p for p in label.replace(" (histogramas)", "").split(" · ") if not p.endswith("pruebas")]
    return " · ".join(parts).replace("sin CVSS de la CNA", "sin CVSS")


def _p(v: float | None) -> str:
    return "—" if v is None else ("< 0,001" if v < 0.001 else fmt_num(v, 3))


def _int(v: int | float) -> str:
    return f"{int(v):,}".replace(",", " ")


def _dataset(db: Session, dataset_id: uuid.UUID | None) -> MlDataset:
    if dataset_id is None:
        raise ReportError("Elija un dataset del laboratorio")
    d = db.get(MlDataset, dataset_id)
    if d is None or d.status != "ready" or not d.file_path:
        raise ReportError("Ese dataset no existe o aún no está listo")
    return d


def _model(db: Session, model_id: uuid.UUID | None) -> MlModel:
    if model_id is None:
        raise ReportError("Elija un modelo del laboratorio")
    m = db.get(MlModel, model_id)
    if m is None or m.status != "ready":
        raise ReportError("Ese modelo no existe o aún no está listo")
    return m


def _profile(d: MlDataset) -> dict[str, Any]:
    from app.ml import dataset as ds
    from app.ml import profile

    cache = Path(str(d.file_path)).with_suffix("").with_suffix(".profile.json")
    if cache.exists():
        data: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return data
    return profile.profile(ds.load(str(d.file_path)), float(d.params.get("neg_rate", 0.05)))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- Fase 1
def ml_dataset(db: Session, dataset_id: uuid.UUID | None) -> Report:
    d = _dataset(db, dataset_id)
    p = _profile(d)
    o = p["overview"]
    srcs: Any = d.sources
    kpis = [("Filas", _int(o["rows"])), ("Entraron a KEV", str(o["positives"])), ("Fotos mensuales", str(o["snapshots"])),
            ("Proporción de KEV", fmt_num(o["prevalence_pct"], 3, " %"))]  # fmt: skip
    tables = [
        Table("Partición temporal 70/15/15", ["Partición", "Fotos", "Desde", "Hasta", "Filas", "Entraron a KEV", "Proporción"],
              [[s["label"], s["snapshots"], s["from"], s["to"], _int(s["rows"]), s["positives"], fmt_num(s["prevalence_pct"], 4, " %")]
               for s in p["splits"]], right={1, 4, 5, 6}, how_to_read=p["how_to_read"]["splits"]),
        Table("Validación del dataset", ["Control", "Estado", "Detalle"], [[c["label"], STATUS[c["status"]], c["detail"]] for c in p["checks"]],
              how_to_read=p["how_to_read"]["checks"]),
        Table("Variables numéricas: entraron a KEV frente al resto", ["Variable", "Sin dato", "Mediana KEV", "Mediana resto", "P75 KEV", "P75 resto", "Separa (AUC)"],
              [[r["name"], fmt_num(r["missing_pct"], 1, " %"), _n(r["median_pos"]), _n(r["median_neg"]), _n(r["p75_pos"]), _n(r["p75_neg"]), _n(r["auc"], 3)]
               for r in p["numeric"]], right={1, 2, 3, 4, 5, 6}, how_to_read=p["how_to_read"]["numeric"]),
    ]  # fmt: skip
    for c in p["categorical"]:
        if c["name"] in ("cna", "cwe", "av"):
            tables.append(Table(f"Categorías de {c['name']} con más entradas a KEV ({c['cardinality']} en total)", ["Categoría", "Filas", "Entraron a KEV", "Proporción"],
                                [[t["value"], _int(t["rows"]), t["positives"], fmt_num(t["prevalence_pct"], 3, " %")] for t in c["top"][:10]],
                                right={1, 2, 3}, how_to_read=p["how_to_read"]["categorical"]))  # fmt: skip
    tables += [
        Table("Variables descartadas por fuga de información", ["Variable", "Fuente", "Motivo"], [[e["name"], e["source"], e["reason"]] for e in EXCLUDED],
              how_to_read="Datos que existen hoy pero no estaban disponibles (o no con ese valor) en la fecha de cada foto: usarlos inflaría las métricas."),
        Table("Diccionario de variables", ["Variable", "Tipo", "Fuente", "Qué es"], [[f["name"], "Numérica" if f["type"] == "num" else "Categórica", f["source"], f["description"]] for f in FEATURES]),
        Table("Fuentes y licencias", ["Fuente", "Archivo", "Tamaño", "SHA-256", "Licencia"],
              [[s.get("name", ""), s.get("file") or s.get("url", ""), fmt_num((s.get("bytes") or 0) / 1_048_576, 1, " MB") if s.get("bytes") else "—",
                (str(s.get("sha256", ""))[:16] + "…") if s.get("sha256") else "—", s.get("license", "")] for s in srcs], right={2}),
    ]  # fmt: skip
    chart = Chart("Entradas a KEV por foto mensual", [s["snapshot"][:7] for s in p["snapshots"]], [("Entraron a KEV", [float(s["positives"]) for s in p["snapshots"]])],
                  kind="bar", x_label="CVE que entraron a KEV en la ventana",
                  how_to_read="Cada barra es una foto mensual; las últimas forman la partición de prueba.")  # fmt: skip
    return Report("ml_dataset", f"Laboratorio · Dataset «{d.name}»",
                  f"Fotos desde {d.params.get('start')} · horizonte de {d.params.get('horizon_days')} días · partición {d.params.get('split')}",
                  datetime.now(UTC), kpis=kpis, tables=tables, charts=[chart], findings=p["interpretation"])  # fmt: skip


# --------------------------------------------------------------------------- Fase 2
def ml_training(db: Session, model_id: uuid.UUID | None) -> Report:
    m = _model(db, model_id)
    a: Any = m.aggregate
    c: Any = m.config
    folds_l: Any = m.folds
    trials_l: Any = m.trials
    mod, epss = a.get("model", {}), a.get("epss", {})
    kpis = [("PR-AUC (5 pliegues)", f"{_n(mod['pr_auc']['mean'])} ± {_n(mod['pr_auc']['sd'])}"), ("ROC-AUC", _n(mod["roc_auc"]["mean"], 3)),
            ("Gana a EPSS", f"{a.get('wins_vs_epss')} de {c.get('k_out')}"), ("Minutos", fmt_num((m.seconds or 0) / 60, 1))]  # fmt: skip
    space = algs.SPACES.get(m.algorithm, [])
    agg_rows = []
    for label, s in (("Modelo entrenado", mod), ("EPSS (sin entrenar)", epss), ("CVSS de la CNA (sin entrenar)", a.get("cvss", {}))):
        if s:
            agg_rows.append([label, f"{_n(s['pr_auc']['mean'])} ± {_n(s['pr_auc']['sd'])}", f"{_n(s['roc_auc']['mean'], 3)} ± {_n(s['roc_auc']['sd'], 3)}",
                             _pct(s["recall_1pct"]["mean"]), _pct(s["recall_5pct"]["mean"])])  # fmt: skip
    tables = [
        Table("Configuración del entrenamiento", ["Parámetro", "Valor"], [
            ["Algoritmo", algs.ALGORITHMS[m.algorithm]["label"]], ["Clase objetivo", str(c.get("target"))], ["Validación cruzada", str(c.get("cv"))],
            ["Pliegues externos × internos", f"{c.get('k_out')} × {c.get('k_in')}"], ["Pruebas de Optuna por búsqueda", str(c.get("n_trials"))],
            ["Métrica optimizada", str(c.get("metric"))], ["Semilla", str(c.get("seed"))],
            ["Variables quitadas (ablación)", ", ".join(c.get("drop") or []) or "ninguna"],
        ]),  # fmt: skip
        Table("Espacio de búsqueda de hiperparámetros", ["Parámetro", "Por defecto", "Rango", "Qué controla"],
              [[p["name"], str(p["default"]), " · ".join(p["choices"]) if p["type"] == "cat" else f"{p['low']} a {p['high']}" + (" (log)" if p["type"] == "float_log" else ""),
                p["description"]] for p in space]),  # fmt: skip
        Table("Resultado por pliegue externo", ["Pliegue", "Entrena", "Valida", "KEV en val.", "PR-AUC", "ROC-AUC", "Cobertura 1 %", "PR-AUC EPSS"],
              [[f["fold"], f"{f['train'][0][:7]} a {f['train'][1][:7]}", f"{f['val'][0][:7]} a {f['val'][1][:7]}", f["metrics"]["positives"],
                _n(f["metrics"]["pr_auc"]), _n(f["metrics"]["roc_auc"], 3), _pct(f["metrics"]["recall_1pct"]), _n(f["baselines"]["epss"]["pr_auc"])]
               for f in folds_l], right={3, 4, 5, 6, 7},
              how_to_read="Cada pliegue entrena con el pasado y valida una vez con los meses siguientes, con los mejores hiperparámetros de su búsqueda interna."),
        Table("Agregado de los pliegues (media ± desviación)", ["Criterio", "PR-AUC", "ROC-AUC", "Cobertura 1 %", "Cobertura 5 %"], agg_rows, right={1, 2, 3, 4}),
        Table("Hiperparámetros del modelo final", ["Parámetro", "Valor"], [[k, str(round(v, 5) if isinstance(v, float) else v)] for k, v in m.best_params.items()]),
    ]  # fmt: skip
    folds = [f"Pliegue {f['fold']}" for f in folds_l]
    charts = [Chart("PR-AUC por pliegue: modelo frente a EPSS", folds,
                    [("Modelo", [float(f["metrics"]["pr_auc"] or 0) for f in folds_l]), ("EPSS", [float(f["baselines"]["epss"]["pr_auc"] or 0) for f in folds_l])],
                    how_to_read="Una evaluación por pliegue externo, en meses que el modelo no vio al entrenar.")]  # fmt: skip
    if trials_l:
        best, run = 0.0, []
        for t in trials_l:
            best = max(best, float(t["value"]))
            run.append(best)
        charts.append(Chart("Pruebas de Optuna (en orden)", [str(i + 1) for i in range(len(trials_l))],
                            [("PR-AUC interna", [float(t["value"]) for t in trials_l]), ("Mejor hasta ese momento", run)],
                            how_to_read="Cada punto es una prueba de hiperparámetros evaluada en los pliegues internos; la línea de «mejor» muestra cuándo dejó de mejorar."))  # fmt: skip
    return Report("ml_training", f"Laboratorio · Entrenamiento «{m.name}»", "Validación cruzada anidada temporal con búsqueda de hiperparámetros (Optuna)",
                  datetime.now(UTC), kpis=kpis, tables=tables, charts=charts, findings=m.reading)  # fmt: skip


# --------------------------------------------------------------------------- Fase 3
def ml_evaluation(db: Session, dataset_id: uuid.UUID | None, op: int) -> Report:
    d = _dataset(db, dataset_id)
    rows = db.execute(select(MlModel).where(MlModel.dataset_id == d.id, MlModel.status == "ready").order_by(MlModel.created_at)).scalars().all()
    rows = [m for m in rows if m.preds_path and Path(m.preds_path).exists()]
    path = mlcache.evaluation(d.id, [m.id for m in rows], op)
    if not rows or not path.exists():
        raise ReportError("Primero calcule la evaluación en Laboratorio → 3 · Evaluación (tarda unos minutos y queda guardada)")
    r = json.loads(path.read_text(encoding="utf-8"))
    by = {x["key"]: x for x in r["rows"]}
    best = by[r["best"]]
    e = by["epss"]
    kpis = [("PR-AUC en prueba (elegido)", _n(best["test"]["pr_auc"])), ("ROC-AUC en prueba (elegido)", _n(best["test"]["roc_auc"], 3)),
            ("ROC-AUC de EPSS", _n(e["test"]["roc_auc"], 3)), ("KEV en prueba", str(best["test"]["positives"]))]  # fmt: skip
    lab = {x["key"]: _short(x["label"]) for x in r["rows"]}
    tables = [
        Table("Métricas por modelo (partición de prueba)", ["Criterio", "PR-AUC prueba", "ROC-AUC prueba", "Cobertura 1 %", "Cobertura 5 %", "PR-AUC validación"],
              [[lab[x["key"]] + (" (elegido en validación)" if x["key"] == r["best"] else ""), _n(x["test"]["pr_auc"]), _n(x["test"]["roc_auc"], 3), _pct(x["test"]["recall_1pct"]),
                _pct(x["test"]["recall_5pct"]), _n(x["validation"]["pr_auc"])] for x in r["rows"]], right={1, 2, 3, 4, 5}, how_to_read=r["how_to_read"]["metrics"]),
        Table(f"Matrices de confusión (revisando el {op} %)", ["Criterio", "KEV marcados", "Otros marcados", "KEV sin marcar", "Otros sin marcar", "Cobertura", "Precisión", "Esfuerzo real"],
              [[lab[k], c["raw"]["tp"], _int(c["raw"]["fp"]), c["raw"]["fn"], _int(c["raw"]["tn"]), _pct(c["recall"]), _pct(c["precision"], 2), fmt_num(c["effort_pct"], 2, " %")]
               for k, c in r["confusion"].items()], right={1, 2, 3, 4, 5, 6, 7}, how_to_read=r["how_to_read"]["confusion"]),
        Table(f"Elegido en validación ({lab[r['best']]}) frente a cada criterio", ["Frente a", "Δ PR-AUC (IC 95 %)", "p", "Δ ROC-AUC (IC 95 %)", "p", "McNemar"],
              [[_short(p["b_label"]), f"{_n(p['pr_auc']['diff'])} ({_n(p['pr_auc']['ci'][0])} a {_n(p['pr_auc']['ci'][1])})", _p(p["pr_auc"]["p"]),
                f"{_n(p['roc_auc']['diff'], 3)} ({_n(p['roc_auc']['ci'][0], 3)} a {_n(p['roc_auc']['ci'][1], 3)})", _p(p["roc_auc"]["p"]),
                f"{p['mcnemar']['only_a']} / {p['mcnemar']['only_b']} (p {_p(p['mcnemar']['p'])})"] for p in r["pairs"]],
              right={2, 4}, how_to_read=f"{r['how_to_read']['bootstrap']} {r['how_to_read']['mcnemar']}"),
        Table("Friedman sobre los 5 pliegues: rango medio", ["Criterio", "Rango medio (1 = mejor)"],
              [[lab.get(k, k), fmt_num(v, 1)] for k, v in sorted((r["friedman"].get("mean_rank") or {}).items(), key=lambda kv: kv[1])], right={1},
              note=f"χ² = {fmt_num(r['friedman']['stat'], 1)} · p {'< 0,001' if (r['friedman']['p'] or 1) < 0.001 else '= ' + _p(r['friedman']['p'])}",
              how_to_read=r["how_to_read"]["friedman"]),
        Table("Estabilidad mes a mes (PR-AUC en prueba)", ["Mes", "Versión EPSS", "KEV", *[lab[x["key"]] for x in r["rows"]]],
              [[s["snapshot"][:7], s.get("epss_model") or "—", s["positives"], *[_n(s.get(x["key"])) for x in r["rows"]]] for s in r["stability"]],
              right=set(range(2, 3 + len(r["rows"]))), how_to_read=r["how_to_read"]["stability"]),
    ]  # fmt: skip
    keys = [x["key"] for x in r["rows"]]
    # La precisión ronda el 1 %: el eje se ajusta a los datos (sin el pico artificial de cobertura ~0, donde 1 acierto = 100 %).
    body = [p["precision"] for k in keys for p in r["curves"][k]["pr"] if p["recall"] >= 0.05]
    pr_top = min(1.0, max(body) * 1.25) if body else None
    charts = [
        Chart("Curvas ROC (prueba)", [], [], kind="xy", ref="diagonal", x_label="CVE sin KEV arrastrados", y_label="KEV capturados",
              xy=[(lab[k], [(p["fpr"], p["tpr"]) for p in r["curves"][k]["roc"]]) for k in keys], how_to_read=r["how_to_read"]["curves"]),
        Chart("Precisión frente a cobertura (prueba)", [], [], kind="xy", ref=f"h:{(r['test_prevalence_pct'] or 0) / 100:.6f}", y_max=pr_top,
              x_label="Cobertura de KEV", y_label="Precisión",
              xy=[(lab[k], [(p["recall"], p["precision"]) for p in r["curves"][k]["pr"]]) for k in keys], how_to_read=r["how_to_read"]["curves"]),
    ]  # fmt: skip
    return Report("ml_evaluation", f"Laboratorio · Evaluación del dataset «{d.name}»",
                  f"Partición de prueba (meses nunca vistos) · revisar el {op} % · modelo elegido en validación: {lab[r['best']]}",
                  datetime.now(UTC), kpis=kpis, tables=tables, charts=charts, findings=r["interpretation"])  # fmt: skip


# --------------------------------------------------------------------------- Fase 4
def ml_explain(db: Session, model_id: uuid.UUID | None) -> Report:
    m = _model(db, model_id)
    path = mlcache.explanation(m.id)
    if not path.exists():
        raise ReportError("Primero calcule las explicaciones en Laboratorio → 4 · Explicabilidad (queda guardado)")
    r = json.loads(path.read_text(encoding="utf-8"))
    groups = [x for x in r["importance"]["rows"] if x["kind"] == "grupo"]
    kpis = [("ROC-AUC base (prueba)", _n(r["importance"]["base_roc_auc"], 3)), ("Grupo más importante", groups[0]["name"] if groups else "—")]
    tables = [
        Table("Equivalencias con el Promptuario", ["Promptuario", "Aquí", "Por qué es equivalente"], [[e["promptuario"], e["aqui"], e["porque"]] for e in r["equivalences"]]),
        Table("Importancia por grupo de variables (permutación)", ["Grupo", "Caída del ROC-AUC", "Desviación"],
              [[x["name"], _n(x["mean"], 4), _n(x["sd"], 4)] for x in groups], right={1, 2}, how_to_read=r["how_to_read"]["importance"]),
        Table("Importancia por variable (permutación)", ["Variable", "Caída del ROC-AUC", "Desviación"],
              [[x["name"], _n(x["mean"], 4), _n(x["sd"], 4)] for x in r["importance"]["rows"] if x["kind"] == "variable"], right={1, 2}),
    ]  # fmt: skip
    m2 = r.get("pdp2d")
    if m2:
        grid = {(c["x"], c["y"]): c["p"] for c in m2["cells"]}
        tables.append(Table(f"Mapa de interacción: {m2['y']} (filas) × {m2['x']} (columnas), puntaje medio en %",
                            [m2["y"], *[fmt_num(x, 3 if x < 1 else 0) for x in m2["xs"]]],
                            [[fmt_num(y, 3 if y < 1 else 0), *[fmt_num(100 * grid[(x, y)], 3) for x in m2["xs"]]] for y in reversed(m2["ys"])],
                            right=set(range(1, len(m2["xs"]) + 1)), how_to_read=r["how_to_read"]["pdp2d"]))  # fmt: skip
    names = {"aciertos": "Acierto", "escapados": "KEV que se escapó", "falsas_alarmas": "Falsa alarma"}
    case_rows = []
    for kind, cases in r["local"].items():
        for c in cases:
            up = next((a for a in c["attributions"] if a["delta"] > 0), None)
            down = next((a for a in c["attributions"] if a["delta"] < 0), None)
            case_rows.append([names.get(kind, kind), c["cve"], c["snapshot"][:7], fmt_num(100 * c["prob"], 2, " %"),
                              f"{up['group']} (+{fmt_num(100 * up['delta'], 2)} pp)" if up else "—",
                              f"{down['group']} ({fmt_num(100 * down['delta'], 2)} pp)" if down else "—"])  # fmt: skip
    tables.append(Table("Explicaciones caso por caso (oclusión)", ["Tipo", "CVE", "Foto", "Puntaje", "Más empujó a favor", "Más empujó en contra"], case_rows,
                        right={3}, how_to_read=r["how_to_read"]["local"]))  # fmt: skip
    if r["coefficients"]:
        tables.append(Table("Coeficientes de la regresión logística", ["Variable o categoría", "Coeficiente"],
                            [[c["feature"], _n(c["coef"], 3)] for c in r["coefficients"]], right={1}, how_to_read=r["how_to_read"]["coef"]))
    def xl(v: float) -> str:  # 0 y enteros sin decimales; fracciones con 3
        return fmt_num(v, 0 if float(v).is_integer() or v >= 1 else 3)

    charts = [Chart(f"Dependencia parcial: {d['feature']}", [xl(p["x"]) for p in d["points"]],
                    [("Puntaje medio (%)", [100 * float(p["y"]) for p in d["points"]])], how_to_read=r["how_to_read"]["pdp"]) for d in r["pdp"][:3]]  # fmt: skip
    return Report("ml_explain", f"Laboratorio · Explicabilidad «{m.name}»", "Equivalentes tabulares de Grad-CAM++, mapas de atención y máscaras (partición de prueba)",
                  datetime.now(UTC), kpis=kpis, tables=tables, charts=charts, findings=r["interpretation"])  # fmt: skip


CATALOG: list[dict[str, Any]] = [
    {"key": "ml_dataset", "kind": "laboratorio", "title": "Laboratorio · Dataset", "description": "Partición, validación, variables, descartadas por fuga, fuentes y licencias.", "period": False, "needs": "dataset"},
    {"key": "ml_training", "kind": "laboratorio", "title": "Laboratorio · Entrenamiento", "description": "Configuración, hiperparámetros, CV anidada 5×3 y pruebas de Optuna.", "period": False, "needs": "model"},
    {"key": "ml_evaluation", "kind": "laboratorio", "title": "Laboratorio · Evaluación", "description": "Métricas en prueba, matrices, curvas ROC/PR, pruebas estadísticas y estabilidad.", "period": False, "needs": "dataset"},
    {"key": "ml_explain", "kind": "laboratorio", "title": "Laboratorio · Explicabilidad", "description": "Importancia, dependencia parcial, mapa de interacción y casos explicados.", "period": False, "needs": "model"},
]  # fmt: skip


def build(db: Session, key: str, dataset_id: uuid.UUID | None, model_id: uuid.UUID | None, op: int) -> Report:
    if key == "ml_dataset":
        return ml_dataset(db, dataset_id)
    if key == "ml_training":
        return ml_training(db, model_id)
    if key == "ml_evaluation":
        return ml_evaluation(db, dataset_id, op)
    if key == "ml_explain":
        return ml_explain(db, model_id)
    raise ReportError("Tipo de reporte desconocido")
