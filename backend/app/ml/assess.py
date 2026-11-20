"""Fase 3: evaluación de los modelos entrenados de un dataset, sobre la partición de PRUEBA (15 %, nunca vista).

- Métricas por modelo (y por las líneas base EPSS y CVSS) en validación y prueba.
- Punto de operación: el umbral se fija en VALIDACIÓN para revisar el X % del universo y se aplica tal cual a prueba
  (fijarlo en prueba sería hacer trampa). Matriz de confusión con filas reales y estimadas (con el peso del muestreo).
- Curvas ROC y PR ponderadas (muestreadas a ~200 puntos).
- Pruebas estadísticas: Friedman sobre los 5 pliegues externos de la CV anidada; bootstrap pareado (por CVE) de la
  diferencia de PR-AUC y ROC-AUC en prueba frente a EPSS y frente al mejor; McNemar en el punto de operación.
- Estabilidad temporal: métricas por foto mensual de prueba junto a la versión del modelo EPSS de ese mes.
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve

from app.ml.metrics import evaluate
from app.services.descriptive import _num

BOOT = 300
POINTS = 200
HOW_TO_READ = {
    "metrics": ("PR-AUC (precisión media) es la métrica principal: con tan pocos positivos, mide si lo que el modelo pone arriba "
                "realmente entra a KEV. ROC-AUC mide el orden general. Cobertura 1 %: parte de las entradas a KEV que quedan "
                "en el 1 % de CVE con mayor puntaje."),
    "confusion": ("Umbral elegido en validación para revisar el {op} % del universo y aplicado tal cual a prueba. «Estimado» "
                  "multiplica cada fila por su peso (los negativos se muestrearon), es decir, el tamaño real del universo."),
    "curves": ("Curvas en la partición de prueba. En ROC la diagonal es el azar; en precisión-cobertura la línea base es la "
               "proporción de KEV, casi cero. Una curva más arriba y a la izquierda es mejor."),
    "friedman": ("Friedman compara todos los criterios a la vez usando los 5 pliegues externos como repeticiones: un valor p "
                 "< 0,05 indica que no rinden igual. Con solo 5 pliegues tiene poca potencia."),
    "bootstrap": ("Se remuestrean los CVE de prueba {b} veces y se recalcula la diferencia de métricas con el mismo remuestreo "
                  "para ambos criterios (pareado). Si el intervalo del 95 % no incluye el 0, la diferencia es robusta."),
    "mcnemar": ("Compara los aciertos de dos criterios en el punto de operación, CVE por CVE: solo cuentan los casos en que "
                "uno acierta y el otro no."),
    "stability": ("Métricas de cada mes de prueba por separado, con la versión de EPSS vigente. Si un modelo cae solo en los "
                  "meses con la versión nueva, depende de la escala de EPSS; si cae en todos, el problema es otro (generaliza "
                  "peor a meses nuevos). Con pocos positivos por mes las cifras fluctúan mucho."),
}  # fmt: skip


def _scores(preds: pd.DataFrame, key: str) -> np.ndarray:
    return preds["score" if key not in ("epss", "cvss") else f"baseline_{key}"].to_numpy(dtype=float)


def threshold_for(s: np.ndarray, w: np.ndarray, share: float) -> float:
    """Umbral tal que el `share` del universo (ponderado) queda por encima."""
    order = np.argsort(-s, kind="stable")
    cw = np.cumsum(w[order])
    k = int(np.searchsorted(cw, share * cw[-1]))
    return float(s[order][min(k, len(s) - 1)])


def confusion(y: np.ndarray, s: np.ndarray, w: np.ndarray, thr: float) -> dict[str, Any]:
    flag = s >= thr
    raw = {"tp": int((flag & (y == 1)).sum()), "fp": int((flag & (y == 0)).sum()), "fn": int((~flag & (y == 1)).sum()),
           "tn": int((~flag & (y == 0)).sum())}  # fmt: skip
    est = {
        k: float(w[m].sum())
        for k, m in (
            ("tp", flag & (y == 1)),
            ("fp", flag & (y == 0)),
            ("fn", ~flag & (y == 1)),
            ("tn", ~flag & (y == 0)),
        )
    }
    flagged = est["tp"] + est["fp"]
    return {"raw": raw, "estimated": {k: round(v) for k, v in est.items()},
            "recall": round(raw["tp"] / max(1, raw["tp"] + raw["fn"]), 4), "precision": round(est["tp"] / flagged, 6) if flagged else None,
            "effort_pct": round(100 * flagged / float(w.sum()), 3), "threshold": thr}  # fmt: skip


def curves(y: np.ndarray, s: np.ndarray, w: np.ndarray) -> dict[str, list[dict[str, float]]]:
    fpr, tpr, _ = roc_curve(y, s, sample_weight=w)
    prec, rec, _ = precision_recall_curve(y, s, sample_weight=w)
    i = np.unique(np.linspace(0, len(fpr) - 1, min(POINTS, len(fpr))).astype(int))
    j = np.unique(np.linspace(0, len(rec) - 1, min(POINTS, len(rec))).astype(int))
    return {"roc": [{"fpr": round(float(fpr[k]), 5), "tpr": round(float(tpr[k]), 4)} for k in i],
            "pr": [{"recall": round(float(rec[k]), 4), "precision": round(float(prec[k]), 6)} for k in j]}  # fmt: skip


def bootstrap_diff(
    y: np.ndarray, w: np.ndarray, a: np.ndarray, b: np.ndarray, seed: int = 7, n: int = BOOT
) -> dict[str, Any]:
    """Diferencia (a − b) de PR-AUC y ROC-AUC con bootstrap pareado de filas: IC 95 % y p bilateral."""
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    out: dict[str, Any] = {}
    diffs: dict[str, list[float]] = {"pr_auc": [], "roc_auc": []}
    for _ in range(n):  # estratificado: conserva el número de positivos en cada remuestreo
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        yy, ww = y[idx], w[idx]
        diffs["pr_auc"].append(
            average_precision_score(yy, a[idx], sample_weight=ww)
            - average_precision_score(yy, b[idx], sample_weight=ww)
        )
        diffs["roc_auc"].append(
            roc_auc_score(yy, a[idx], sample_weight=ww) - roc_auc_score(yy, b[idx], sample_weight=ww)
        )
    for k, d in diffs.items():
        arr = np.array(d)
        p = 2 * min(float((arr <= 0).mean()), float((arr >= 0).mean()))
        out[k] = {"diff": round(float(arr.mean()), 5), "ci": [round(float(np.quantile(arr, 0.025)), 5), round(float(np.quantile(arr, 0.975)), 5)],
                  "p": round(min(1.0, p), 4)}  # fmt: skip
    return out


def bootstrap_diff_cluster(y: np.ndarray, w: np.ndarray, a: np.ndarray, b: np.ndarray, groups: np.ndarray, seed: int = 7,
                           n: int = BOOT, stratify: bool = True) -> dict[str, Any]:  # fmt: skip
    """Como `bootstrap_diff` pero remuestrea CLÚSTERES (todas las filas de un mismo CVE, o de un mismo bloque de fotos),
    porque un CVE aparece en varias fotos y esas filas no son independientes. Con `stratify` conserva el número de clústeres
    con algún positivo; sin él (bloques de fotos) se descartan los remuestreos sin positivos. Cada remuestreo se aplica
    como multiplicidad del peso de cada fila (equivale a duplicarla)."""
    rng = np.random.default_rng(seed)
    codes, uniq = pd.factorize(groups)
    k = len(uniq)
    has_pos = np.zeros(k, dtype=bool)
    has_pos[codes[y == 1]] = True
    pos_c, neg_c = np.flatnonzero(has_pos), np.flatnonzero(~has_pos)
    diffs: dict[str, list[float]] = {"pr_auc": [], "roc_auc": []}
    for _ in range(n):
        if stratify:
            cnt = np.bincount(rng.choice(pos_c, len(pos_c)), minlength=k) + (
                np.bincount(rng.choice(neg_c, len(neg_c)), minlength=k) if len(neg_c) else 0
            )
        else:
            cnt = np.bincount(rng.choice(k, k), minlength=k)
        ww = w * cnt[codes]
        if ww[y == 1].sum() == 0 or ww[y == 0].sum() == 0:
            continue
        diffs["pr_auc"].append(
            average_precision_score(y, a, sample_weight=ww) - average_precision_score(y, b, sample_weight=ww)
        )
        diffs["roc_auc"].append(roc_auc_score(y, a, sample_weight=ww) - roc_auc_score(y, b, sample_weight=ww))
    out: dict[str, Any] = {"n_boot": len(diffs["pr_auc"]), "clusters": int(k)}
    for key, d in diffs.items():
        arr = np.array(d)
        p = 2 * min(float((arr <= 0).mean()), float((arr >= 0).mean()))
        out[key] = {"diff": round(float(arr.mean()), 5), "ci": [round(float(np.quantile(arr, 0.025)), 5), round(float(np.quantile(arr, 0.975)), 5)],
                    "p": round(min(1.0, p), 4)}  # fmt: skip
    return out


def holm(pvals: list[float]) -> list[float]:
    """Valores p ajustados por Holm-Bonferroni (en el orden de entrada)."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * pvals[i])
        adj[i] = min(1.0, run)
    return [round(float(x), 4) for x in adj]


def lift_at(y: np.ndarray, s: np.ndarray, w: np.ndarray, share: float) -> float | None:
    """Precisión (ponderada) del `share` superior dividida por la prevalencia: cuántas veces mejor que el azar."""
    if y.sum() == 0:
        return None
    order = np.argsort(-s, kind="stable")
    cw = np.cumsum(w[order])
    top = order[cw <= share * cw[-1]]
    if len(top) == 0:
        return None
    prec = float(w[top][y[top] == 1].sum() / w[top].sum())
    return round(prec / float(w[y == 1].sum() / w.sum()), 2)


def brier_relative(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> dict[str, float]:
    """Brier ponderado y su cociente con el de predecir siempre la tasa base (< 1 = mejor que la tasa base)."""
    base = float(w[y == 1].sum() / w.sum())
    brier = float(np.sum(w * (p - y) ** 2) / w.sum())
    ref = float(np.sum(w * (base - y) ** 2) / w.sum())
    return {
        "brier": round(brier, 8),
        "brier_base": round(ref, 8),
        "ratio": round(brier / ref, 3) if ref else float("nan"),
    }


def wilcoxon_paired(a: list[float], b: list[float]) -> dict[str, Any]:
    """Wilcoxon pareado sobre pliegues. Con n pares el menor valor p exacto bilateral es 2/2^n: con 4 pliegues es 0,125,
    así que NUNCA puede ser significativo al 5 %: se informa solo como descriptivo."""
    n = len(a)
    if n < 3:
        return {"n": n, "p": None, "min_possible_p": None}
    d = np.array(a) - np.array(b)
    p = 1.0 if not np.any(d) else float(stats.wilcoxon(d, method="exact").pvalue)
    return {"n": n, "p": round(p, 4), "min_possible_p": round(2 / 2**n, 4)}


def mcnemar(y: np.ndarray, fa: np.ndarray, fb: np.ndarray) -> dict[str, Any]:
    """McNemar exacto (binomial) sobre los aciertos de dos reglas de marcado."""
    ca, cb = fa == (y == 1), fb == (y == 1)
    b01, b10 = int((ca & ~cb).sum()), int((~ca & cb).sum())
    p = float(stats.binomtest(b01, b01 + b10, 0.5).pvalue) if b01 + b10 else 1.0
    return {"only_a": b01, "only_b": b10, "p": round(p, 4)}


def friedman(folds: dict[str, list[float]]) -> dict[str, Any]:
    keys = [
        k
        for k, v in folds.items()
        if len(v) == len(next(iter(folds.values()))) and all(x is not None for x in v)
    ]
    if len(keys) < 3:
        return {"stat": None, "p": None, "keys": keys}
    st, p = stats.friedmanchisquare(*[folds[k] for k in keys])
    ranks = np.mean(
        [stats.rankdata([-folds[k][i] for k in keys]) for i in range(len(folds[keys[0]]))], axis=0
    )
    return {"stat": round(float(st), 3), "p": round(float(p), 4), "keys": keys,
            "mean_rank": {k: round(float(r), 2) for k, r in zip(keys, ranks, strict=True)}}  # fmt: skip


def assess(models: list[dict[str, Any]], operating_pct: float = 1.0, report: Any = None) -> dict[str, Any]:
    """`models`: [{id, name, algorithm, drop, folds, preds(DataFrame)}]. Todos del mismo dataset (mismas filas).
    `report(pct, msg)` opcional para el monitoreo (el bootstrap es lo más lento)."""
    base = models[0]["preds"]
    test, val = base[base["split"] == "prueba"], base[base["split"] == "validacion"]
    y_t, w_t = test["label"].to_numpy(dtype=int), test["weight"].to_numpy(dtype=float)
    y_v, w_v = val["label"].to_numpy(dtype=int), val["weight"].to_numpy(dtype=float)
    entries: list[dict[str, Any]] = [
        {"key": m["id"], "label": m["name"], "kind": "modelo", "preds": m["preds"], "folds": m["folds"]}
        for m in models
    ]
    entries += [{"key": b, "label": "EPSS (sin entrenar)" if b == "epss" else "CVSS de la CNA (sin entrenar)", "kind": "base", "preds": base,
                 "folds": models[0]["folds"]} for b in ("epss", "cvss")]  # fmt: skip
    share = operating_pct / 100
    rows, conf, curv, flags = [], {}, {}, {}
    for e in entries:
        p = e["preds"]
        t, v = p[p["split"] == "prueba"], p[p["split"] == "validacion"]
        st, sv = _scores(t, e["key"]), _scores(v, e["key"])
        thr = threshold_for(sv, w_v, share)
        conf[e["key"]] = confusion(y_t, st, w_t, thr)
        flags[e["key"]] = st >= thr
        curv[e["key"]] = curves(y_t, st, w_t)
        tm = evaluate(y_t, st, w_t) | {"events": int(test.loc[test["label"] == 1, "cve"].nunique()), "lift_1pct": lift_at(y_t, st, w_t, 0.01),
                                       "lift_5pct": lift_at(y_t, st, w_t, 0.05)}  # fmt: skip
        rows.append(
            {
                "key": e["key"],
                "label": e["label"],
                "kind": e["kind"],
                "test": tm,
                "validation": evaluate(y_v, sv, w_v),
            }
        )

    # El modelo se ELIGE en validación (elegirlo mirando prueba sería sesgado) y luego se informa en prueba.
    best = max((r for r in rows if r["kind"] == "modelo"), key=lambda r: r["validation"]["pr_auc"] or 0)
    test_best = max((r for r in rows if r["kind"] == "modelo"), key=lambda r: r["test"]["pr_auc"] or 0)
    s_of = {e["key"]: _scores(e["preds"][e["preds"]["split"] == "prueba"], e["key"]) for e in entries}
    pairs = []
    others = [r for r in rows if r["key"] != best["key"]]
    kind_of = {e["key"]: e for e in entries}

    def fold_pr_of(key: str) -> list[float]:
        e = kind_of[key]
        ok = [f for f in e["folds"] if not f.get("skipped")]
        return (
            [f["metrics"]["pr_auc"] for f in ok]
            if e["kind"] == "modelo"
            else [f["baselines"][key]["pr_auc"] for f in ok]
        )

    for n, r in enumerate(others):
        if report:
            report(
                10 + int(85 * n / len(others)), f"Bootstrap pareado: {best['label']} frente a {r['label']}"
            )
        pairs.append({"a": best["key"], "b": r["key"], "b_label": r["label"],
                      **bootstrap_diff_cluster(y_t, w_t, s_of[best["key"]], s_of[r["key"]], test["cve"].to_numpy()),
                      "block_bootstrap": bootstrap_diff_cluster(y_t, w_t, s_of[best["key"]], s_of[r["key"]], pd.to_datetime(test["snapshot"]).map(lambda d: d.toordinal() // 60).to_numpy(), stratify=False, n=BOOT // 2),
                      "mcnemar": mcnemar(y_t, flags[best["key"]], flags[r["key"]]),
                      "wilcoxon_folds": wilcoxon_paired(fold_pr_of(best["key"]), fold_pr_of(r["key"]))})  # fmt: skip
    for key in ("pr_auc", "roc_auc"):  # Holm sobre todas las comparaciones del mismo conjunto
        for pr, adj in zip(pairs, holm([float(x[key]["p"]) for x in pairs]), strict=True):
            pr[key]["p_holm"] = adj
    fold_pr: dict[str, list[float]] = {e["key"]: fold_pr_of(e["key"]) for e in entries}
    stability = []
    for snap, g in test.groupby("snapshot"):
        row: dict[str, Any] = {"snapshot": str(snap), "positives": int(g["label"].sum())}
        idx = g.index
        for e in entries:
            p = e["preds"].loc[idx]
            row[e["key"]] = evaluate(p["label"].to_numpy(), _scores(p, e["key"]), p["weight"].to_numpy())[
                "pr_auc"
            ]
        stability.append(row)

    out = {"operating_pct": operating_pct, "rows": rows, "best": best["key"], "test_best": test_best["key"], "confusion": conf, "curves": curv,
           "pairs": pairs, "friedman": friedman(fold_pr), "stability": stability,
           "test_prevalence_pct": rows[0]["test"]["prevalence_pct"],
           "how_to_read": {k: v.format(op=_num(operating_pct, digits=0), b=BOOT) for k, v in HOW_TO_READ.items()}}  # fmt: skip
    out["interpretation"] = _notes(out)
    return out


def _notes(r: dict[str, Any]) -> list[str]:
    by = {x["key"]: x for x in r["rows"]}
    best, tb, e = by[r["best"]], by[r["test_best"]], by["epss"]
    out = [f"Modelo elegido en validación (sin mirar la prueba): {best['label']}, con PR-AUC {_num(best['validation']['pr_auc'], digits=4)} "
           f"en validación. En prueba (meses nunca vistos) obtiene PR-AUC {_num(best['test']['pr_auc'], digits=4)} y ROC-AUC "
           f"{_num(best['test']['roc_auc'], digits=3)}, frente a {_num(e['test']['pr_auc'], digits=4)} y {_num(e['test']['roc_auc'], digits=3)} de EPSS."]  # fmt: skip
    if tb["key"] != best["key"]:
        out.append(f"En prueba rinde mejor {tb['label']} (PR-AUC {_num(tb['test']['pr_auc'], digits=4)}, ROC-AUC {_num(tb['test']['roc_auc'], digits=3)}): "
                   "el elegido en validación no generalizó igual de bien a los meses siguientes. Elegir el modelo mirando la prueba sería "
                   "sesgado; para el siguiente ciclo conviene revalidar con los meses nuevos.")  # fmt: skip
    vs = next((p for p in r["pairs"] if p["b"] == "epss"), None)
    if vs:
        ci = vs["roc_auc"]["ci"]
        out.append(f"Frente a EPSS, el elegido mejora el ROC-AUC en {_num(vs['roc_auc']['diff'], digits=3)} (IC 95 % de {_num(ci[0], digits=3)} a "
                   f"{_num(ci[1], digits=3)}): " + ("robusto, no es azar." if ci[0] > 0 else "el intervalo incluye el 0, no es concluyente."))  # fmt: skip
    c = r["confusion"][r["best"]]
    out.append(f"Revisando el {_num(r['operating_pct'], digits=0)} % del universo (umbral fijado en validación), el elegido habría marcado "
               f"{c['raw']['tp']} de {c['raw']['tp'] + c['raw']['fn']} CVE que entraron a KEV en prueba ({_num(100 * c['recall'], digits=0)} %), "
               f"con un esfuerzo real del {_num(c['effort_pct'], digits=2)} % (el umbral de validación no marca exactamente el mismo "
               "porcentaje en meses nuevos).")  # fmt: skip
    f = r["friedman"]
    if f["p"] is not None:
        ptxt = "p < 0,001" if f["p"] < 0.001 else f"p = {_num(f['p'], digits=3)}"
        out.append(f"Friedman sobre los 5 pliegues de la CV anidada: {ptxt} "
                   + ("(los criterios no rinden igual)." if f["p"] < 0.05 else "(no concluyente con 5 pliegues)."))  # fmt: skip
    if r["stability"]:
        n = [s["positives"] for s in r["stability"]]
        out.append(f"Por mes de prueba hay entre {min(n)} y {max(n)} CVE que entraron a KEV: las cifras mensuales son orientativas y "
                   "fluctúan mucho; compare la tendencia, no un mes aislado.")  # fmt: skip
    return out
