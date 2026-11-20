"""Fase 7: estudios de Optuna configurables (la «Optuna UI» del Promptuario).

Un estudio busca hiperparámetros de UN algoritmo con validación cruzada temporal (ventana creciente) solo sobre la
partición de DESARROLLO: validación y prueba quedan intactas. Se puede elegir:
- el espacio de búsqueda (rangos y categorías, dentro de `algorithms.LIMITS`),
- el muestreador (TPE bayesiano o aleatorio, para comparar si TPE aporta),
- la poda por mediana (Optuna corta una prueba si tras un pliegue va peor que la mediana de las anteriores),
- el número de pruebas, un tiempo máximo y la semilla.
Cada prueba se publica al terminar (monitoreo en vivo) y el estudio se puede detener entre pruebas. Al final se calculan
la importancia de cada hiperparámetro (fANOVA de Optuna), los avisos de «mejor valor en el borde del rango» con un
rango sugerido, y una lectura en lenguaje llano."""

import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import optuna
import pandas as pd

from app.ml import algorithms as algs
from app.ml.metrics import evaluate
from app.ml.training import fit_predict, forward_folds
from app.services.descriptive import _num

SAMPLERS = {"tpe": "TPE (bayesiano)", "random": "Aleatorio"}
PRUNERS = {"median": "Poda por mediana", "none": "Sin poda"}
TPE_STARTUP = 10  # pruebas al azar con que TPE arranca antes de modelar
EDGE = 0.05  # a menos del 5 % del extremo (en escala log si el parámetro es logarítmico) = «en el borde»
HOW_TO_READ = {
    "history": ("Cada punto es una prueba (su PR-AUC media en los pliegues internos de desarrollo); la línea es la mejor hasta "
                "ese momento. Si la línea sigue subiendo al final, más pruebas podrían mejorar; si se aplanó pronto, el espacio "
                "está agotado o la métrica es ruidosa. Las podadas aparecen en gris con su valor parcial."),
    "importance": ("fANOVA: qué fracción de la variación de la PR-AUC entre pruebas explica cada hiperparámetro. Uno con importancia "
                   "baja casi no cambia el resultado dentro de su rango: se puede fijar y buscar en los demás."),
    "slice": ("PR-AUC de cada prueba según el valor de un hiperparámetro (el resto varía a la vez). Una nube plana indica poca "
              "influencia; una tendencia hacia un extremo del eje sugiere ampliar el rango por ese lado."),
    "contour": ("Las dos variables más importantes: cada punto es una prueba y su intensidad, la PR-AUC. Zonas intensas que tocan un "
                "borde indican que el óptimo podría estar fuera del rango."),
    "edges": ("Si el mejor valor queda pegado a un extremo del rango, el óptimo podría estar más allá: se sugiere un rango ampliado "
              "(dentro de los límites admitidos) para un estudio nuevo."),
}  # fmt: skip

OnTrial = Callable[[dict[str, Any]], bool]  # recibe la prueba terminada; devuelve True si hay que detener el estudio


def _sampler(name: str, seed: int) -> optuna.samplers.BaseSampler:
    if name == "random":
        return optuna.samplers.RandomSampler(seed=seed)
    return optuna.samplers.TPESampler(seed=seed, n_startup_trials=TPE_STARTUP)


def _pruner(name: str) -> optuna.pruners.BasePruner:
    if name == "median":
        # Nunca poda tras el primer pliegue (un solo mes es muy ruidoso) ni en las 5 primeras pruebas.
        return optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=1)
    return optuna.pruners.NopPruner()


def fold_frames(dev: pd.DataFrame, k_in: int) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Pliegues temporales de desarrollo con positivos a ambos lados (los demás no permiten medir la PR-AUC)."""
    out = []
    for tr, va in forward_folds(sorted(dev["snapshot"].unique()), k_in):
        a, b = dev[dev["snapshot"].isin(tr)], dev[dev["snapshot"].isin(va)]
        if a["label"].sum() > 0 and b["label"].sum() > 0:
            out.append((a, b))
    if not out:
        raise ValueError("Ningún pliegue interno tiene casos positivos para medir la PR-AUC")
    return out


def run(dev: pd.DataFrame, algo: str, space: list[dict[str, Any]], cfg: dict[str, Any], on_trial: OnTrial) -> dict[str, Any]:
    """Ejecuta el estudio. `cfg`: sampler, pruner, n_trials, timeout_minutes, seed, k_in, include_defaults, drop."""
    seed, drop = int(cfg["seed"]), tuple(cfg.get("drop") or ())
    folds = fold_frames(dev, int(cfg["k_in"]))
    study = optuna.create_study(direction="maximize", sampler=_sampler(cfg["sampler"], seed), pruner=_pruner(cfg["pruner"]))
    if cfg.get("include_defaults", True):
        study.enqueue_trial(algs.defaults(algo, space))
    recs: list[dict[str, Any]] = []

    def objective(trial: optuna.Trial) -> float:
        params = algs.suggest(trial, algo, space)
        vals: list[float] = []
        for step, (a, b) in enumerate(folds):
            _, s = fit_predict(algo, params, seed, a, b, drop)
            vals.append(float(evaluate(b["label"].to_numpy(), s, b["weight"].to_numpy())["pr_auc"] or 0.0))
            trial.set_user_attr("folds", vals)
            trial.report(float(np.mean(vals)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(vals))

    def callback(st: optuna.Study, ft: optuna.trial.FrozenTrial) -> None:
        state = {optuna.trial.TrialState.COMPLETE: "completa", optuna.trial.TrialState.PRUNED: "podada"}.get(ft.state, "falló")
        partial = ft.value if ft.value is not None else (ft.intermediate_values[max(ft.intermediate_values)] if ft.intermediate_values else None)
        done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
        rec = {"number": ft.number, "state": state, "value": None if partial is None else round(float(partial), 6),
               "params": ft.params, "folds": [round(v, 6) for v in ft.user_attrs.get("folds", [])],
               "seconds": round(ft.duration.total_seconds(), 2) if ft.duration else None,
               "best": round(float(st.best_value), 6) if done else None, "default": ft.number == 0 and bool(cfg.get("include_defaults", True))}  # fmt: skip
        recs.append(rec)
        if on_trial(rec):
            st.stop()

    t0 = time.perf_counter()
    study.optimize(objective, n_trials=int(cfg["n_trials"]), timeout=60 * float(cfg["timeout_minutes"]), callbacks=[callback],
                   catch=(ValueError,))  # fmt: skip
    seconds = round(time.perf_counter() - t0, 1)
    complete = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    best_params = dict(study.best_params) if complete else {}
    best_value = float(study.best_value) if complete else None
    importance = _importance(study, seed) if len(complete) >= 4 else []
    out = {"trials": recs, "best_params": best_params, "best_value": best_value, "seconds": seconds, "n_folds": len(folds)}
    out["summary"] = summarize(recs, space, algo, cfg, importance, len(folds))
    return out


def _importance(study: optuna.Study, seed: int) -> list[dict[str, Any]]:
    try:
        imp = optuna.importance.get_param_importances(study, evaluator=optuna.importance.FanovaImportanceEvaluator(seed=seed))
    except (RuntimeError, ValueError):  # p. ej. todos los parámetros fijos o una sola prueba distinta
        return []
    return [{"param": k, "value": round(float(v), 4)} for k, v in imp.items()]


def _position(p: dict[str, Any], v: float) -> float:
    lo, hi = float(p["low"]), float(p["high"])
    if p["type"] == "float_log":
        return (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return (v - lo) / (hi - lo)


def _widen(p: dict[str, Any], side: str, lim: tuple[float, float]) -> tuple[float, float]:
    """Rango ampliado por el lado del borde: ×10 en escala log; la mitad del ancho en escala lineal."""
    lo, hi = float(p["low"]), float(p["high"])
    if p["type"] == "float_log":
        lo, hi = (lo / 10, hi) if side == "inferior" else (lo, hi * 10)
    else:
        w = (hi - lo) / 2
        lo, hi = (lo - w, hi) if side == "inferior" else (lo, hi + w)
        if p["type"] == "int":
            lo, hi = math.floor(lo), math.ceil(hi)
    return max(lo, lim[0]), min(hi, lim[1])


def edges(best: dict[str, Any], space: list[dict[str, Any]], algo: str) -> list[dict[str, Any]]:
    out = []
    for p in space:
        if p["type"] == "cat" or p["name"] not in best:
            continue
        pos = _position(p, float(best[p["name"]]))
        side = "inferior" if pos <= EDGE else "superior" if pos >= 1 - EDGE else None
        if side is None:
            continue
        lim = algs.LIMITS[algo][p["name"]]
        lo, hi = _widen(p, side, lim)
        at_limit = (side == "inferior" and float(p["low"]) <= lim[0]) or (side == "superior" and float(p["high"]) >= lim[1])
        out.append({"param": p["name"], "side": side, "value": best[p["name"]], "low": p["low"], "high": p["high"],
                    "suggest": None if at_limit else {"low": lo, "high": hi}, "at_limit": at_limit})  # fmt: skip
    return out


def _v(x: float) -> str:
    """Valor de hiperparámetro legible: enteros sin decimales y el resto con 2 o 3 cifras significativas (0,0012 · 4,33)."""
    if float(x).is_integer():
        return _num(float(x), digits=0)
    return f"{x:.{2 if abs(x) < 0.1 else 3}g}".replace(".", ",")


def summarize(recs: list[dict[str, Any]], space: list[dict[str, Any]], algo: str, cfg: dict[str, Any],
              importance: list[dict[str, Any]], n_folds: int) -> dict[str, Any]:  # fmt: skip
    complete = [r for r in recs if r["state"] == "completa"]
    pruned = [r for r in recs if r["state"] == "podada"]
    failed = [r for r in recs if r["state"] == "falló"]
    base = {"n_trials": len(recs), "n_complete": len(complete), "n_pruned": len(pruned), "n_failed": len(failed),
            "importance": importance, "edges": [], "reading": [], "how_to_read": HOW_TO_READ}  # fmt: skip
    if not complete:
        base["reading"] = ["Ninguna prueba terminó: no hay un mejor valor que informar."]
        return base
    best = max(complete, key=lambda r: r["value"])
    default = next((r for r in recs if r["default"] and r["state"] == "completa"), None)
    reading = [f"Mejor PR-AUC interna {_num(best['value'], digits=4)} en la prueba {best['number']} ({len(complete)} completas"
               f"{f', {len(pruned)} podadas' if pruned else ''}{f', {len(failed)} fallidas' if failed else ''})."]  # fmt: skip
    improvement = None
    if default is not None and default["value"]:
        improvement = best["value"] / default["value"] - 1
        reading.append(f"Los valores por defecto (prueba 0) daban {_num(default['value'], digits=4)}: la búsqueda "
                       + (f"mejora un {_num(100 * improvement, digits=1)} %." if improvement > 0.005 else "no los mejora de forma apreciable."))  # fmt: skip
    order = [r["number"] for r in complete]
    rank = order.index(best["number"]) + 1
    if len(complete) >= 8 and rank > 0.8 * len(complete):
        reading.append("El mejor apareció en el último 20 % de las pruebas: la búsqueda aún mejoraba, conviene darle más pruebas.")
    elif len(complete) >= 8 and rank <= 0.3 * len(complete):
        reading.append(f"El mejor apareció pronto (prueba {rank} de {len(complete)} completas) y no se superó después: el espacio "
                       "parece agotado o las diferencias son ruido.")  # fmt: skip
    if cfg["sampler"] == "tpe" and len(recs) <= TPE_STARTUP + 1:
        reading.append(f"Con {len(recs)} pruebas TPE no salió de su fase inicial al azar (las primeras {TPE_STARTUP}): en la práctica fue "
                       "una búsqueda aleatoria.")  # fmt: skip
    if pruned:
        per_fold = np.mean([r["seconds"] / max(1, len(r["folds"])) for r in complete if r["seconds"]]) if complete else 0
        saved = sum(per_fold * (n_folds - len(r["folds"])) for r in pruned)
        reading.append(f"La poda por mediana cortó {len(pruned)} pruebas que iban peor que la mediana y ahorró unos "
                       f"{_num(saved / 60, digits=1)} minutos.")  # fmt: skip
    top = sorted(complete, key=lambda r: -r["value"])[:5]
    if len(top) == 5 and len(best["folds"]) > 1:
        sd = float(np.std(best["folds"], ddof=1))
        gap = best["value"] - top[-1]["value"]
        if gap < sd:
            reading.append(f"Entre la mejor y la quinta mejor hay {_num(gap, digits=4)} de PR-AUC, menos que la variación de la mejor "
                           f"entre pliegues (desv. {_num(sd, digits=4)}): esas configuraciones son prácticamente equivalentes.")  # fmt: skip
    if importance:
        reading.append("Lo que más influyó: " + ", ".join(f"{i['param']} ({_num(100 * i['value'], digits=0)} %)" for i in importance[:2]) + ".")
    ed = edges(best["params"], space, algo)
    for e in ed:
        msg = (f"El mejor {e['param']} ({_v(float(e['value']))}) quedó en el borde {e['side']} del rango "
               f"[{_v(float(e['low']))}, {_v(float(e['high']))}]: ")  # fmt: skip
        msg += ("ya es el límite admitido, así que el óptimo está en el extremo." if e["at_limit"]
                else f"conviene repetir con [{_v(e['suggest']['low'])}, {_v(e['suggest']['high'])}].")  # fmt: skip
        reading.append(msg)
    base |= {"best_trial": best["number"], "best_folds": best["folds"], "default_value": default["value"] if default else None,
             "improvement": improvement, "edges": ed, "reading": reading}  # fmt: skip
    return base
