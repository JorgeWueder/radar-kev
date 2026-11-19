"""Evaluación de los criterios de priorización frente a la explotación confirmada (KEV), sin entrenar nada.

Pregunta: si NO supiéramos qué CVE están en KEV, ¿qué criterio los habría puesto primero? Se evalúan CVSS, EPSS y el
score sin KEV (el que tendría el hallazgo si no estuviera en KEV). El score completo no se evalúa: incluye KEV y daría un resultado
perfecto por construcción.

Unidad: CVE único entre los hallazgos abiertos (KEV es propiedad del CVE; contar hallazgos duplicaría los CVE repetidos).
Los datos ausentes cuentan 0, igual que en el score. Funciones puras sobre DataFrame y listas; sin SciPy ni sklearn.
"""

import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.services.descriptive import _num, load_frame
from app.services.scoring import ScoringParams, base_score

MIN_CLASS = 5  # positivos o negativos por debajo: resultado orientativo

PREDICTORS: list[tuple[str, str]] = [("cvss", "CVSS"), ("epss", "EPSS"), ("base", "Score sin KEV")]

HOW_TO_READ = {
    "roc": (
        "La curva ROC muestra, al bajar el umbral, cuántos CVE en KEV se capturan (eje vertical) frente a cuántos de los "
        "demás se arrastran (eje horizontal). El AUC es la probabilidad de que un CVE en KEV quede por encima de uno que no "
        "lo está: 0,5 es azar y 1 es perfecto."
    ),
    "pr": (
        "La curva precisión-cobertura responde: si parcheo los primeros N según este criterio, ¿qué parte son KEV "
        "(precisión) y qué parte de los KEV cubro (cobertura)? La línea base es la proporción de KEV: un criterio útil "
        "queda por encima. Depende de esa proporción; el AUC no."
    ),
    "rules": (
        "Cada regla es un umbral fijo. Cobertura: parte de los KEV que la regla marca. Precisión (eficiencia): parte de lo "
        "marcado que está en KEV. Esfuerzo: parte de los CVE que habría que parchear. Buena regla: alta cobertura con poco esfuerzo."
    ),
}


def auc(scores: list[float], labels: list[bool]) -> float | None:
    """AUC de la ROC por Mann-Whitney (empates cuentan medio)."""
    pos = [s for s, y in zip(scores, labels, strict=True) if y]
    neg = [s for s, y in zip(scores, labels, strict=True) if not y]
    if not pos or not neg:
        return None
    ranks = pd.Series(scores).rank(method="average").tolist()
    r_pos = sum(r for r, y in zip(ranks, labels, strict=True) if y)
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def auc_ci(a: float, n_pos: int, n_neg: int) -> tuple[float, float]:
    """Intervalo del 95 % de Hanley y McNeil (1982). Con AUC de 0 o 1 la fórmula da varianza 0 y un intervalo sin
    ancho que aparenta certeza; para el error estándar se acerca el AUC medio par de casos hacia dentro."""
    eps = 0.5 / (n_pos * n_neg)
    a_se = min(max(a, eps), 1 - eps)
    q1, q2 = a_se / (2 - a_se), 2 * a_se * a_se / (1 + a_se)
    var = (a_se * (1 - a_se) + (n_pos - 1) * (q1 - a_se * a_se) + (n_neg - 1) * (q2 - a_se * a_se)) / (n_pos * n_neg)
    se = math.sqrt(max(var, 0.0))
    return max(0.0, a - 1.96 * se), min(1.0, a + 1.96 * se)


def curves(scores: list[float], labels: list[bool]) -> tuple[list[dict[str, float]], list[dict[str, float]], float | None]:
    """Puntos ROC y PR en cada umbral distinto (de mayor a menor) y la precisión media (AP)."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    pairs = sorted(zip(scores, labels, strict=True), key=lambda t: -t[0])
    roc: list[dict[str, float]] = [{"fpr": 0.0, "tpr": 0.0}]  # umbral por encima de todo: nada marcado
    pr: list[dict[str, float]] = []
    tp = fp = 0
    ap = 0.0
    prev_recall = 0.0
    i = 0
    while i < len(pairs):
        thr = pairs[i][0]
        while i < len(pairs) and pairs[i][0] == thr:  # un umbral incluye todos los empatados
            tp += pairs[i][1]
            fp += not pairs[i][1]
            i += 1
        tpr = tp / n_pos if n_pos else 0.0
        fpr = fp / n_neg if n_neg else 0.0
        prec = tp / (tp + fp)
        roc.append({"fpr": round(fpr, 4), "tpr": round(tpr, 4), "threshold": thr})
        pr.append({"recall": round(tpr, 4), "precision": round(prec, 4), "threshold": thr})
        ap += (tpr - prev_recall) * prec
        prev_recall = tpr
    return roc, pr, (round(ap, 4) if n_pos else None)


def confusion(scores: list[float], labels: list[bool], threshold: float) -> dict[str, Any]:
    tp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= threshold and y)
    fp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= threshold and not y)
    fn = sum(1 for s, y in zip(scores, labels, strict=True) if s < threshold and y)
    tn = len(labels) - tp - fp - fn
    n = len(labels)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "coverage": round(100 * tp / (tp + fn), 1) if tp + fn else None,
        "efficiency": round(100 * tp / (tp + fp), 1) if tp + fp else None,
        "effort": round(100 * (tp + fp) / n, 1) if n else None,
    }  # fmt: skip


def cve_frame(df: pd.DataFrame, p: ScoringParams) -> pd.DataFrame:
    """Un renglón por CVE: CVSS y EPSS son del CVE; el score sin KEV toma el activo más crítico donde aparece."""
    d = df.copy()
    for col in ("cvss", "epss", "percentile"):
        d[col] = d[col].fillna(0.0)
    d["base"] = [
        round((p.kev_floor - 1) * base_score(p, e / 100, pc, c, int(k)), 2)  # = risk_score con in_kev=False
        for e, pc, c, k in zip(d["epss"], d["percentile"], d["cvss"], d["criticality"], strict=True)
    ]
    return d.groupby("cve_id", as_index=False).agg(cvss=("cvss", "max"), epss=("epss", "max"), base=("base", "max"), in_kev=("in_kev", "max"))


def _rules(p: ScoringParams) -> list[tuple[str, str, str, float]]:
    """(clave, predictor, etiqueta, umbral). CVSS ≥ 7 es la práctica habitual de parchear 'alto y crítico'."""
    return [
        ("cvss_7", "cvss", "CVSS ≥ 7 (alto y crítico)", 7.0),
        ("cvss_9", "cvss", "CVSS ≥ 9 (solo crítico)", 9.0),
        ("epss_10", "epss", "EPSS ≥ 10 %", 10.0),
        ("base_medium", "base", f"Score sin KEV ≥ {_num(p.band_medium)} (banda media)", p.band_medium),
    ]


def evaluate(df: pd.DataFrame, p: ScoringParams) -> dict[str, Any]:
    out: dict[str, Any] = {"how_to_read": HOW_TO_READ}
    if df.empty:
        return out | {"n": 0, "positives": 0, "predictors": [], "rules": [], "reliable": False,
                      "interpretation": ["No hay hallazgos abiertos: no hay nada que evaluar."]}  # fmt: skip
    cves = cve_frame(df, p)
    labels = [bool(x) for x in cves["in_kev"]]
    n, n_pos = len(labels), sum(labels)
    n_neg = n - n_pos
    prevalence = 100 * n_pos / n
    reliable = min(n_pos, n_neg) >= MIN_CLASS
    out |= {"n": n, "positives": n_pos, "negatives": n_neg, "prevalence": round(prevalence, 1), "reliable": reliable}
    if not n_pos or not n_neg:
        out |= {"predictors": [], "rules": [], "interpretation": [
            f"Los {n} CVE abiertos están {'todos' if n_pos else 'ninguno'} en KEV: sin ambos grupos no hay nada que separar."]}
        return out

    preds = []
    for key, label in PREDICTORS:
        s = [float(x) for x in cves[key]]
        a = auc(s, labels)
        roc, pr, ap = curves(s, labels)
        lo, hi = auc_ci(a, n_pos, n_neg) if a is not None else (None, None)
        preds.append({"key": key, "label": label, "auc": round(a, 3) if a is not None else None,
                      "auc_ci": [round(lo, 3), round(hi, 3)] if lo is not None and hi is not None else None,
                      "ap": ap, "roc": roc, "pr": pr})  # fmt: skip
    out["predictors"] = preds
    out["rules"] = [
        {"key": k, "predictor": pk, "label": lbl, "threshold": t, **confusion([float(x) for x in cves[pk]], labels, t)}
        for k, pk, lbl, t in _rules(p)
    ]
    out["interpretation"] = _notes(out, preds, reliable)
    return out


def _quality_of(a: float) -> str:
    return "excelente" if a >= 0.9 else "buena" if a >= 0.8 else "aceptable" if a >= 0.7 else "pobre" if a >= 0.6 else "casi como el azar"


def _notes(out: dict[str, Any], preds: list[dict[str, Any]], reliable: bool) -> list[str]:
    notes = [f"{out['n']} CVE distintos entre los hallazgos abiertos; {out['positives']} en KEV ({_num(out['prevalence'], digits=0)} %)."]
    by = {p["key"]: p for p in preds}
    ranked = sorted((p for p in preds if p["auc"] is not None), key=lambda p: -p["auc"])
    if ranked:
        best = ranked[0]
        ci = best["auc_ci"]
        notes.append(f"El criterio que mejor separa lo explotado es {best['label']}: AUC {_num(best['auc'], digits=2)} "
                     f"({_quality_of(best['auc'])}; IC 95 % de {_num(ci[0], digits=2)} a {_num(ci[1], digits=2)}).")  # fmt: skip
    c, e = by["cvss"], by["epss"]
    if c["auc"] is not None and e["auc"] is not None:
        if c["auc_ci"][1] < e["auc_ci"][0]:
            notes.append(f"EPSS (AUC {_num(e['auc'], digits=2)}) supera a CVSS ({_num(c['auc'], digits=2)}) y sus intervalos no se solapan: "
                         "priorizar solo por CVSS deja pasar explotación real.")  # fmt: skip
        elif e["auc"] > c["auc"]:
            notes.append(f"EPSS (AUC {_num(e['auc'], digits=2)}) queda por encima de CVSS ({_num(c['auc'], digits=2)}), "
                         "pero los intervalos se solapan: con estos casos la diferencia no es concluyente.")  # fmt: skip
        else:
            notes.append(f"Aquí CVSS (AUC {_num(c['auc'], digits=2)}) no queda por debajo de EPSS ({_num(e['auc'], digits=2)}).")
    rules = {r["key"]: r for r in out["rules"]}
    r7, r10 = rules["cvss_7"], rules["epss_10"]
    if r7["coverage"] is not None and r10["coverage"] is not None:
        notes.append(f"Parchear todo CVSS ≥ 7 cubre el {_num(r7['coverage'], digits=0)} % de los KEV con un esfuerzo del "
                     f"{_num(r7['effort'], digits=0)} % de los CVE; EPSS ≥ 10 % cubre el {_num(r10['coverage'], digits=0)} % "
                     f"con un esfuerzo del {_num(r10['effort'], digits=0)} %.")  # fmt: skip
    if out["prevalence"] > 20:
        notes.append(f"Aquí el {_num(out['prevalence'], digits=0)} % de los CVE está en KEV, muy por encima del ~5 % del universo de "
                     "CVE: la precisión saldría menor en un inventario típico; el AUC no depende de esa proporción.")  # fmt: skip
    notes.append("EPSS se calcula en parte con evidencia de explotación, así que su acuerdo con KEV no es del todo "
                 "independiente; CVSS sí lo es.")  # fmt: skip
    if not reliable:
        notes.append(f"Hay menos de {MIN_CLASS} CVE en uno de los dos grupos: resultados orientativos.")
    return notes


def evaluation(db: Session) -> dict[str, Any]:
    from app.services.intel import get_active_config

    _, params = get_active_config(db)
    return evaluate(load_frame(db), params)
