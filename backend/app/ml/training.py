"""Fase 2: validación cruzada anidada con orden temporal y búsqueda de hiperparámetros con Optuna.

Estructura (la que pide el Promptuario), dentro de la partición de DESARROLLO (70 %):
1. 5 pliegues externos y, dentro de cada uno, 3 pliegues internos.
2. En cada pliegue externo: Optuna busca hiperparámetros sobre los internos; se reentrena con los mejores sobre
   outer_train y se evalúa UNA vez sobre outer_val.
3. Se agregan los 5 resultados (una observación por pliegue externo).
Los pliegues son de «ventana creciente» por fotos mensuales: siempre se entrena con el pasado y se valida con el mes
siguiente, nunca al revés. Después se ajusta el modelo final sobre todo desarrollo y se predice validación y prueba
(15 % + 15 %), que la Fase 3 evalúa."""

import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import numpy as np
import optuna
import pandas as pd

from app.ml import algorithms as algs
from app.ml.metrics import evaluate

optuna.logging.set_verbosity(optuna.logging.WARNING)

Report = Callable[[str, dict[str, Any] | None], None]  # (mensaje, evento) para el monitoreo en vivo


def forward_folds(snaps: list[date], k: int) -> list[tuple[list[date], list[date]]]:
    """k pliegues de ventana creciente con bloque de validación de tamaño fijo v = n // (k+1): el pliegue i entrena con
    todas las fotos anteriores a su bloque y valida con las v fotos siguientes. La ventana inicial absorbe el resto
    (con 14 fotos y k=5: 4 iniciales y bloques de 2), así hasta el primer pliegue tiene historia suficiente."""
    snaps = sorted(snaps)
    n = len(snaps)
    if n < k + 1:
        raise ValueError(f"Hacen falta al menos {k + 1} fotos para {k} pliegues temporales (hay {n})")
    v = n // (k + 1)
    start = n - k * v
    return [(snaps[: start + i * v], snaps[start + i * v : start + (i + 1) * v]) for i in range(k)]


def feasible(n_snaps: int, k_out: int, k_in: int) -> str | None:
    """None si la CV anidada temporal cabe en n fotos; si no, el motivo."""
    try:
        folds = forward_folds([date(2000, 1, 1) + timedelta(days=31 * i) for i in range(n_snaps)], k_out)
    except ValueError as e:
        return str(e)
    short = min(len(tr) for tr, _ in folds)
    if short < k_in + 1:
        return (f"Con {n_snaps} fotos de desarrollo, el primer pliegue externo entrena con {short} fotos y hacen falta "
                f"{k_in + 1} para {k_in} pliegues internos: construya el dataset desde una fecha anterior")  # fmt: skip
    return None


def _xyw(df: pd.DataFrame, drop: tuple[str, ...] = ()) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    return algs.prepare(df, drop), df["label"].to_numpy(dtype=int), df["weight"].to_numpy(dtype=float)


def fit_predict(algo: str, params: dict[str, Any], seed: int, train: pd.DataFrame, test: pd.DataFrame,
                drop: tuple[str, ...] = ()) -> tuple[Any, np.ndarray]:  # fmt: skip
    X, y, w = _xyw(train, drop)
    model = algs.build(algo, params, seed)
    model.fit(X, y, clf__sample_weight=w)
    return model, model.predict_proba(algs.prepare(test, drop))[:, 1]


def inner_cv(algo: str, params: dict[str, Any], seed: int, df: pd.DataFrame, k_in: int, drop: tuple[str, ...] = ()) -> float:
    """PR-AUC media en los pliegues internos (los pliegues sin positivos en validación no cuentan)."""
    scores = []
    for tr, va in forward_folds(sorted(df["snapshot"].unique()), k_in):
        a, b = df[df["snapshot"].isin(tr)], df[df["snapshot"].isin(va)]
        if b["label"].sum() == 0 or a["label"].sum() == 0:
            continue
        _, s = fit_predict(algo, params, seed, a, b, drop)
        scores.append(evaluate(b["label"].to_numpy(), s, b["weight"].to_numpy())["pr_auc"])
    return float(np.mean(scores)) if scores else 0.0


def search(algo: str, df: pd.DataFrame, n_trials: int, k_in: int, seed: int, tag: str, report: Report,
           trials_log: list[dict[str, Any]], drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """Optuna (TPE con semilla) maximizando la PR-AUC interna; la prueba 0 son los hiperparámetros por defecto."""
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial(algs.defaults(algo, space))

    def objective(trial: optuna.Trial) -> float:
        t0 = time.perf_counter()
        params = algs.suggest(trial, algo, space)
        value = inner_cv(algo, params, seed, df, k_in, drop)
        rec = {"fold": tag, "trial": trial.number, "value": round(value, 5), "params": params, "seconds": round(time.perf_counter() - t0, 2)}
        trials_log.append(rec)
        report(f"{tag} · prueba {trial.number + 1}/{n_trials} · PR-AUC interna {value:.4f}".replace(".", ","), {"trial": rec})
        return value

    study.optimize(objective, n_trials=n_trials)
    return dict(study.best_params)


def _baselines(df: pd.DataFrame) -> dict[str, Any]:
    return {k: evaluate(df["label"].to_numpy(), fn(df), df["weight"].to_numpy()) for k, (_, fn) in algs.BASELINES.items()}


def nested(algo: str, dev: pd.DataFrame, n_trials: int, k_out: int, k_in: int, seed: int, report: Report,
           trials_log: list[dict[str, Any]], drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    folds = []
    for i, (tr, va) in enumerate(forward_folds(sorted(dev["snapshot"].unique()), k_out), start=1):
        outer_train, outer_val = dev[dev["snapshot"].isin(tr)], dev[dev["snapshot"].isin(va)]
        tag = f"Pliegue {i}/{k_out}"
        best = search(algo, outer_train, n_trials, k_in, seed + i, tag, report, trials_log, drop, space)
        _, s = fit_predict(algo, best, seed, outer_train, outer_val, drop)  # reentrena con los mejores y evalúa UNA vez
        metrics = evaluate(outer_val["label"].to_numpy(), s, outer_val["weight"].to_numpy())
        res: dict[str, Any] = {
            "fold": i, "train": [str(min(tr)), str(max(tr))], "val": [str(min(va)), str(max(va))],
            "train_rows": int(len(outer_train)), "train_positives": int(outer_train["label"].sum()),
            "best_params": best, "metrics": metrics,
            "baselines": _baselines(outer_val),
        }  # fmt: skip
        folds.append(res)
        report(f"{tag} terminado · PR-AUC en outer_val {metrics['pr_auc']}".replace(".", ","), {"fold": res})
    return folds


def aggregate(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Media y desviación de las métricas de los pliegues externos, del modelo y de las líneas base."""

    def stat(vals: list[float | None]) -> dict[str, float | None]:
        v = [x for x in vals if x is not None]
        return {"mean": round(float(np.mean(v)), 5) if v else None, "sd": round(float(np.std(v, ddof=1)), 5) if len(v) > 1 else None, "n": len(v)}

    keys = ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")
    out: dict[str, Any] = {"model": {k: stat([f["metrics"][k] for f in folds]) for k in keys}}
    for b in algs.BASELINES:
        out[b] = {k: stat([f["baselines"][b][k] for f in folds]) for k in keys}
    out["wins_vs_epss"] = sum(1 for f in folds if (f["metrics"]["pr_auc"] or 0) > (f["baselines"]["epss"]["pr_auc"] or 0))
    return out


def train(df: pd.DataFrame, algo: str, n_trials: int, k_out: int, k_in: int, seed: int, report: Report,
          drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """Todo el entrenamiento: CV anidada en desarrollo + modelo final (búsqueda en todo desarrollo) + predicciones."""
    if algo not in algs.ALGORITHMS:
        raise ValueError(f"Algoritmo desconocido: {algo}")
    dev = df[df["split"] == "desarrollo"]
    trials_log: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    folds = nested(algo, dev, n_trials, k_out, k_in, seed, report, trials_log, drop, space)
    report("Modelo final: búsqueda en todo desarrollo", None)
    best = search(algo, dev, n_trials, k_in, seed, "Modelo final", report, trials_log, drop, space)
    rest = df[df["split"].isin(["validacion", "prueba"])]
    model, s = fit_predict(algo, best, seed, dev, rest, drop)
    preds = rest[["snapshot", "cve", "split", "label", "weight"]].copy()
    preds["score"] = s
    for b, (_, fn) in algs.BASELINES.items():
        preds[f"baseline_{b}"] = fn(rest)
    quick = {sp: evaluate(g["label"].to_numpy(), g["score"].to_numpy(), g["weight"].to_numpy()) for sp, g in preds.groupby("split")}
    return {"model": model, "preds": preds, "folds": folds, "aggregate": aggregate(folds), "best_params": best,
            "trials": trials_log, "final_metrics": quick, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


def notes(algo: str, agg: dict[str, Any], final: dict[str, Any], k_out: int) -> list[str]:
    """Lectura del entrenamiento en lenguaje llano."""
    from app.services.descriptive import _num

    m, e = agg["model"]["pr_auc"], agg["epss"]["pr_auc"]
    out = [f"{algs.ALGORITHMS[algo]['label']}: PR-AUC media de {_num(m['mean'], digits=4)} (desv. {_num(m['sd'], digits=4)}) en los "
           f"{k_out} pliegues externos, frente a {_num(e['mean'], digits=4)} de EPSS sin entrenar en los mismos meses."]  # fmt: skip
    out.append(f"Supera a EPSS en {agg['wins_vs_epss']} de {k_out} pliegues. Con tan pocos casos positivos por mes, la variación "
               "entre pliegues es grande: la Fase 3 compara con pruebas estadísticas.")  # fmt: skip
    r1 = agg["model"]["recall_1pct"]["mean"]
    if r1 is not None:
        out.append(f"Revisando el 1 % de CVE con mayor probabilidad se habría cubierto, en promedio, el {_num(100 * r1, digits=0)} % "
                   "de los que entraron a KEV en el mes validado.")  # fmt: skip
    val = final.get("validacion", {})
    if val.get("pr_auc") is not None:
        out.append(f"Modelo final en validación (15 %): PR-AUC {_num(val['pr_auc'], digits=4)}, ROC-AUC {_num(val['roc_auc'], digits=3)}. "
                   "La prueba (15 %) se reserva para la evaluación final de la Fase 3.")  # fmt: skip
    return out
