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
from app.ml.dataset import purge
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


MIN_INNER_TRAIN = 3  # fotos mínimas de entrenamiento en un pliegue interno


def embargo_folds(snaps: list[date], k: int, v: int, horizon: int) -> list[tuple[list[date], list[date]]]:
    """k pliegues de ventana expansiva con bloques de validación de `v` fotos (los últimos de la lista). El entrenamiento
    de cada pliegue excluye las fotos cuya ventana de etiqueta (S, S+N] llega al bloque de validación (embargo)."""
    snaps = sorted(snaps)
    first = len(snaps) - k * v
    if first < 1:
        raise ValueError(f"Con {len(snaps)} fotos no caben {k} pliegues de {v} fotos de validación")
    out = []
    for i in range(k):
        a = first + i * v
        va = snaps[a : a + v]
        out.append((purge(snaps[:a], va[0], horizon), va))
    return out


def feasible_embargo(
    dev_snaps: list[date], k_out: int, k_in: int, v_out: int, v_in: int, horizon: int
) -> str | None:
    """None si cada pliegue externo, tras el embargo, deja historia para los k_in pliegues internos; si no, el motivo."""
    try:
        outer = embargo_folds(dev_snaps, k_out, v_out, horizon)
    except ValueError as e:
        return str(e)
    for i, (tr, _) in enumerate(outer, start=1):
        try:
            inner = embargo_folds(tr, k_in, v_in, horizon)
        except ValueError:
            return f"El pliegue externo {i} deja {len(tr)} fotos tras el embargo: no caben {k_in} pliegues internos de {v_in} fotos"
        short = min(len(t) for t, _ in inner)
        if short < MIN_INNER_TRAIN:
            return (f"Pliegue externo {i}: el primer pliegue interno entrena con {short} fotos tras el embargo "
                    f"(mínimo {MIN_INNER_TRAIN}); construya el dataset desde una fecha anterior")  # fmt: skip
    return None


def _fold_pairs(
    snaps: list[date], k: int, v: int | None, horizon: int
) -> list[tuple[list[date], list[date]]]:
    """Pliegues heredados (v=None, sin embargo) o con embargo (v = fotos por bloque de validación)."""
    return forward_folds(snaps, k) if v is None else embargo_folds(snaps, k, v, horizon)


def hgb_best_iter(
    model: Any, X_hold: pd.DataFrame, y: np.ndarray, w: np.ndarray, patience: int, tol: float
) -> int:
    """Iteración que minimiza la log-loss ponderada en el bloque temporal de parada; para tras `patience` etapas sin
    mejorar al menos `tol` (relativo)."""
    Z = model.named_steps["prep"].transform(X_hold)
    best, best_i, since = np.inf, 1, 0
    for i, p in enumerate(model.named_steps["clf"].staged_predict_proba(Z), start=1):
        p1 = np.clip(p[:, 1], 1e-12, 1 - 1e-12)
        loss = float(-np.sum(w * (y * np.log(p1) + (1 - y) * np.log(1 - p1))) / np.sum(w))
        if loss < best * (1 - tol):
            best, best_i, since = loss, i, 0
        else:
            since += 1
            if since >= patience:
                break
    return best_i


def _xyw(df: pd.DataFrame, drop: tuple[str, ...] = ()) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    return algs.prepare(df, drop), df["label"].to_numpy(dtype=int), df["weight"].to_numpy(dtype=float)


def fit_predict(algo: str, params: dict[str, Any], seed: int, train: pd.DataFrame, test: pd.DataFrame,
                drop: tuple[str, ...] = (), horizon: int = 0) -> tuple[Any, np.ndarray]:  # fmt: skip
    """Ajusta y predice. En el boosting sin `max_iter` fijo, el número de árboles sale de una parada anticipada TEMPORAL:
    se ajusta con tope 500 en las fotos más antiguas y se mide la log-loss en el último 20 % de las fotos (tras el
    embargo `horizon`), luego se reajusta con el mejor número de iteraciones sobre todo el entrenamiento."""
    X, y, w = _xyw(train, drop)
    p = dict(params)
    if algo == "hgb" and not p.get("max_iter"):
        fx = algs.FIXED["hgb"]
        snaps = sorted(train["snapshot"].unique())
        n_hold = max(1, round(fx["es_fraction"] * len(snaps)))
        fit_snaps = purge(snaps[:-n_hold], snaps[-n_hold], horizon) if len(snaps) > n_hold else []
        if fit_snaps and train.loc[train["snapshot"].isin(fit_snaps), "label"].sum() > 0:
            a, b = train[train["snapshot"].isin(fit_snaps)], train[train["snapshot"].isin(snaps[-n_hold:])]
            first = algs.build(algo, {**p, "max_iter": fx["max_iter_cap"]}, seed)
            first.fit(
                algs.prepare(a, drop),
                a["label"].to_numpy(dtype=int),
                clf__sample_weight=a["weight"].to_numpy(dtype=float),
            )
            p["max_iter"] = hgb_best_iter(first, algs.prepare(b, drop), b["label"].to_numpy(dtype=int), b["weight"].to_numpy(dtype=float),
                                          fx["n_iter_no_change"], fx["tol"])  # fmt: skip
        else:
            p["max_iter"] = 100  # sin historia suficiente para parar: valor modesto fijo
    model = algs.build(algo, p, seed)
    model.fit(X, y, clf__sample_weight=w)
    model.best_iter_ = p.get("max_iter") if algo == "hgb" else None
    return model, model.predict_proba(algs.prepare(test, drop))[:, 1]


def inner_cv(algo: str, params: dict[str, Any], seed: int, df: pd.DataFrame, k_in: int, drop: tuple[str, ...] = (),
             v_in: int | None = None, horizon: int = 0, trial: Any = None) -> float:  # fmt: skip
    """PR-AUC media en los pliegues internos (los pliegues sin positivos no cuentan). Con `trial`, reporta cada pliegue
    y permite la poda por mediana (optuna.TrialPruned)."""
    scores: list[float] = []
    for step, (tr, va) in enumerate(_fold_pairs(sorted(df["snapshot"].unique()), k_in, v_in, horizon)):
        a, b = df[df["snapshot"].isin(tr)], df[df["snapshot"].isin(va)]
        if b["label"].sum() == 0 or a["label"].sum() == 0:
            continue
        _, s = fit_predict(algo, params, seed, a, b, drop, horizon)
        scores.append(evaluate(b["label"].to_numpy(), s, b["weight"].to_numpy())["pr_auc"])
        if trial is not None:
            trial.report(float(np.mean(scores)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
    return float(np.mean(scores)) if scores else 0.0


def search(algo: str, df: pd.DataFrame, n_trials: int, k_in: int, seed: int, tag: str, report: Report,
           trials_log: list[dict[str, Any]], drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None,
           v_in: int | None = None, horizon: int = 0, sampler: str = "tpe") -> dict[str, Any]:  # fmt: skip
    """Optuna (TPE o aleatorio, con semilla) maximizando la PR-AUC interna; la prueba 0 son los hiperparámetros por defecto.
    Con embargo (v_in) se poda por mediana tras cada pliegue interno."""
    smp: optuna.samplers.BaseSampler = (optuna.samplers.RandomSampler(seed=seed) if sampler == "random"
                                        else optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(10, max(3, n_trials // 2))))  # con 10 pruebas, 5 al azar y 5 guiadas (el valor por defecto, 10, volvía a TPE un muestreo aleatorio)  # fmt: skip
    pruner: optuna.pruners.BasePruner = (optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=0) if v_in is not None
                                         else optuna.pruners.NopPruner())  # fmt: skip
    study = optuna.create_study(direction="maximize", sampler=smp, pruner=pruner)
    study.enqueue_trial(algs.defaults(algo, space))

    def objective(trial: optuna.Trial) -> float:
        t0 = time.perf_counter()
        params = algs.suggest(trial, algo, space)
        try:
            value = inner_cv(algo, params, seed, df, k_in, drop, v_in, horizon, trial)
        except optuna.TrialPruned:
            pr = {"fold": tag, "trial": trial.number, "value": None, "pruned": True, "params": params,
                  "seconds": round(time.perf_counter() - t0, 2)}  # fmt: skip
            trials_log.append(pr)
            report(f"{tag} · prueba {trial.number + 1}/{n_trials} · podada", {"trial": pr})
            raise
        rec = {
            "fold": tag,
            "trial": trial.number,
            "value": round(value, 5),
            "params": params,
            "seconds": round(time.perf_counter() - t0, 2),
        }
        trials_log.append(rec)
        report(
            f"{tag} · prueba {trial.number + 1}/{n_trials} · PR-AUC interna {value:.4f}".replace(".", ","),
            {"trial": rec},
        )
        return value

    study.optimize(objective, n_trials=n_trials)
    return dict(study.best_params)


def _baselines(df: pd.DataFrame) -> dict[str, Any]:
    return {
        k: evaluate(df["label"].to_numpy(), fn(df), df["weight"].to_numpy())
        for k, (_, fn) in algs.BASELINES.items()
    }


def nested(algo: str, dev: pd.DataFrame, n_trials: int, k_out: int, k_in: int, seed: int, report: Report,
           trials_log: list[dict[str, Any]], drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None,
           v_out: int | None = None, v_in: int | None = None, horizon: int = 0, sampler: str = "tpe") -> list[dict[str, Any]]:  # fmt: skip
    folds = []
    for i, (tr, va) in enumerate(
        _fold_pairs(sorted(dev["snapshot"].unique()), k_out, v_out, horizon), start=1
    ):
        outer_train, outer_val = dev[dev["snapshot"].isin(tr)], dev[dev["snapshot"].isin(va)]
        tag = f"Pliegue {i}/{k_out}"
        if outer_val["label"].sum() == 0 or outer_train["label"].sum() == 0:
            why = "validación" if outer_val["label"].sum() == 0 else "entrenamiento"
            report(f"{tag} omitido: sin positivos en {why}", None)
            folds.append({"fold": i, "skipped": True, "reason": f"sin positivos en {why}",
                          "val": [str(min(va)), str(max(va))]})  # fmt: skip
            continue
        best = search(
            algo,
            outer_train,
            n_trials,
            k_in,
            seed + i,
            tag,
            report,
            trials_log,
            drop,
            space,
            v_in,
            horizon,
            sampler,
        )
        model, s = fit_predict(
            algo, best, seed, outer_train, outer_val, drop, horizon
        )  # reentrena con los mejores y evalúa UNA vez
        metrics = evaluate(outer_val["label"].to_numpy(), s, outer_val["weight"].to_numpy())
        res: dict[str, Any] = {
            "fold": i, "train": [str(min(tr)), str(max(tr))], "val": [str(min(va)), str(max(va))],
            "train_rows": int(len(outer_train)), "train_positives": int(outer_train["label"].sum()),
            "best_params": best, "metrics": metrics, "best_iter": getattr(model, "best_iter_", None),
            "val_events": int(outer_val.loc[outer_val["label"] == 1, "cve"].nunique()), "train_snapshots": len(tr),
            "baselines": _baselines(outer_val),
        }  # fmt: skip
        folds.append(res)
        report(f"{tag} terminado · PR-AUC en outer_val {metrics['pr_auc']}".replace(".", ","), {"fold": res})
    return folds


def aggregate(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Media y desviación de las métricas de los pliegues externos, del modelo y de las líneas base."""

    def stat(vals: list[float | None]) -> dict[str, float | None]:
        v = [x for x in vals if x is not None]
        return {
            "mean": round(float(np.mean(v)), 5) if v else None,
            "sd": round(float(np.std(v, ddof=1)), 5) if len(v) > 1 else None,
            "n": len(v),
        }

    skipped = [f["fold"] for f in folds if f.get("skipped")]
    folds = [f for f in folds if not f.get("skipped")]
    keys = ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")
    out: dict[str, Any] = {"model": {k: stat([f["metrics"][k] for f in folds]) for k in keys}}
    for b in algs.BASELINES:
        out[b] = {k: stat([f["baselines"][b][k] for f in folds]) for k in keys}
    out["skipped_folds"] = skipped
    out["wins_vs_epss"] = sum(
        1 for f in folds if (f["metrics"]["pr_auc"] or 0) > (f["baselines"]["epss"]["pr_auc"] or 0)
    )
    return out


def train(df: pd.DataFrame, algo: str, n_trials: int, k_out: int, k_in: int, seed: int, report: Report,
          drop: tuple[str, ...] = (), space: list[dict[str, Any]] | None = None, v_out: int | None = None,
          v_in: int | None = None, horizon: int = 0, sampler: str = "tpe") -> dict[str, Any]:  # fmt: skip
    """Todo el entrenamiento: CV anidada en desarrollo + modelo final (búsqueda en todo desarrollo) + predicciones."""
    if algo not in algs.ALGORITHMS:
        raise ValueError(f"Algoritmo desconocido: {algo}")
    dev = df[df["split"] == "desarrollo"]
    trials_log: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    folds = nested(
        algo, dev, n_trials, k_out, k_in, seed, report, trials_log, drop, space, v_out, v_in, horizon, sampler
    )
    report("Modelo final: búsqueda en todo desarrollo", None)
    best = search(
        algo,
        dev,
        n_trials,
        k_in,
        seed,
        "Modelo final",
        report,
        trials_log,
        drop,
        space,
        v_in,
        horizon,
        sampler,
    )
    rest = df[df["split"].isin(["validacion", "prueba"])]
    model, s = fit_predict(algo, best, seed, dev, rest, drop, horizon)
    preds = rest[["snapshot", "cve", "split", "label", "weight"]].copy()
    preds["score"] = s
    for b, (_, fn) in algs.BASELINES.items():
        preds[f"baseline_{b}"] = fn(rest)
    quick = {
        sp: evaluate(g["label"].to_numpy(), g["score"].to_numpy(), g["weight"].to_numpy())
        for sp, g in preds.groupby("split")
    }
    return {"model": model, "preds": preds, "folds": folds, "aggregate": aggregate(folds), "best_params": best,
            "trials": trials_log, "final_metrics": quick, "seconds": round(time.perf_counter() - t0, 1),
            "best_iter": getattr(model, "best_iter_", None)}  # fmt: skip


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
