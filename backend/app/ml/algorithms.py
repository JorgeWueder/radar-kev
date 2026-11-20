"""Catálogo de algoritmos del laboratorio: preparación de variables, hiperparámetros por defecto y espacio de búsqueda
(Optuna). Todos son de scikit-learn; se ajustan con el peso de cada fila para respetar la proporción real de KEV."""

import os
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

NUM = ["epss", "percentile", "epss_delta", "cvss", "days_published", "edb_exploits", "cna_kev_prior"]
CAT = ["epss_model", "av", "ac", "pr", "ui", "cwe", "cna"]
LOG = {"epss": 1e-5, "days_published": 1.0, "edb_exploits": 1.0, "cna_kev_prior": 1.0}  # log(x + c): colas largas
MIN_FREQ = 20  # categorías con menos filas se agrupan en «otras» (CWE y CNA tienen cientos)

SPACES: dict[str, list[dict[str, Any]]] = {
    "logreg": [
        {"name": "C", "type": "float_log", "low": 1e-3, "high": 10.0, "default": 1.0,
         "description": "Inverso de la regularización L2: valores bajos simplifican el modelo y evitan el sobreajuste."},
        {"name": "class_weight", "type": "cat", "choices": ["balanced", "none"], "default": "balanced",
         "description": "«balanced» da más peso a la clase rara (entra a KEV) para que el modelo no la ignore."},
    ],
    "random_forest": [
        {"name": "n_estimators", "type": "int", "low": 100, "high": 300, "default": 200, "description": "Número de árboles."},
        {"name": "max_depth", "type": "int", "low": 4, "high": 16, "default": 10, "description": "Profundidad máxima de cada árbol."},
        {"name": "min_samples_leaf", "type": "int", "low": 1, "high": 50, "default": 10,
         "description": "Mínimo de filas en cada hoja: valores altos suavizan las predicciones."},
        {"name": "max_features", "type": "cat", "choices": ["sqrt", "0.3", "0.5"], "default": "sqrt",
         "description": "Variables que considera cada división (azar entre árboles)."},
        {"name": "class_weight", "type": "cat", "choices": ["balanced_subsample", "none"], "default": "balanced_subsample",
         "description": "Compensa el desbalance dentro de cada muestra bootstrap."},
    ],
    "hgb": [
        {"name": "learning_rate", "type": "float_log", "low": 0.02, "high": 0.3, "default": 0.08, "description": "Tamaño del paso de cada árbol nuevo."},
        {"name": "max_iter", "type": "int", "low": 100, "high": 400, "default": 200, "description": "Número de árboles (iteraciones de boosting)."},
        {"name": "max_leaf_nodes", "type": "int", "low": 15, "high": 63, "default": 31, "description": "Hojas por árbol (complejidad)."},
        {"name": "min_samples_leaf", "type": "int", "low": 20, "high": 200, "default": 50, "description": "Mínimo de filas por hoja."},
        {"name": "l2_regularization", "type": "float_log", "low": 1e-4, "high": 1.0, "default": 0.01, "description": "Penalización L2 de las hojas."},
        {"name": "class_weight", "type": "cat", "choices": ["balanced", "none"], "default": "balanced", "description": "Compensa el desbalance de clases."},
    ],
}  # fmt: skip

ALGORITHMS: dict[str, dict[str, str]] = {
    "logreg": {"label": "Regresión logística", "family": "Lineal",
               "description": "Modelo lineal e interpretable: cada variable suma o resta a la probabilidad. Es la línea base entrenada."},
    "random_forest": {"label": "Random forest", "family": "Árboles (bagging)",
                      "description": "Muchos árboles sobre muestras al azar; capta interacciones sin escalar las variables."},
    "hgb": {"label": "Gradient boosting (histogramas)", "family": "Árboles (boosting)",
            "description": "Árboles secuenciales que corrigen los errores del anterior; maneja vacíos y categorías de forma nativa."},
}  # fmt: skip


GROUPS: dict[str, dict[str, Any]] = {
    "cvss": {"label": "CVSS de la CNA", "columns": ["cvss", "av", "ac", "pr", "ui"]},
    "epss": {"label": "EPSS", "columns": ["epss", "percentile", "epss_delta", "epss_model"]},
}  # fmt: skip


def prepare(df: pd.DataFrame, drop: tuple[str, ...] | list[str] = ()) -> pd.DataFrame:
    """Variables de entrada: transformación monótona de las colas largas (no cambia a los árboles, ayuda a la lineal).
    `drop` (ablación) deja constantes grupos completos de variables: el modelo se entrena como si no existieran."""
    X = df[NUM + CAT].copy()
    for g in drop:
        for col in GROUPS[g]["columns"]:
            # Constante (no vacía): ningún modelo puede usarla y el binning del boosting no falla con columnas todo NaN.
            X[col] = 0.0 if col in NUM else "desconocido"
    for col, c in LOG.items():
        X[col] = np.log(X[col].clip(lower=0) + c)
    for col in CAT:
        X[col] = X[col].astype(str)
    return X


def defaults(algo: str) -> dict[str, Any]:
    return {p["name"]: p["default"] for p in SPACES[algo]}


def suggest(trial: Any, algo: str) -> dict[str, Any]:
    """Hiperparámetros propuestos por Optuna dentro del espacio del algoritmo."""
    out: dict[str, Any] = {}
    for p in SPACES[algo]:
        if p["type"] == "float_log":
            out[p["name"]] = trial.suggest_float(p["name"], p["low"], p["high"], log=True)
        elif p["type"] == "int":
            out[p["name"]] = trial.suggest_int(p["name"], p["low"], p["high"])
        else:
            out[p["name"]] = trial.suggest_categorical(p["name"], p["choices"])
    return out


def _cw(v: str) -> str | None:
    return None if v == "none" else v


def _onehot() -> ColumnTransformer:
    num = Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)), ("sc", StandardScaler())])
    cat = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=MIN_FREQ, sparse_output=True)
    return ColumnTransformer([("num", num, NUM), ("cat", cat, CAT)])


def build(algo: str, params: dict[str, Any], seed: int, n_jobs: int | None = None) -> Pipeline:
    n_jobs = n_jobs or max(1, (os.cpu_count() or 2) // 2)  # la mitad de los núcleos: deja aire a la API
    if algo == "logreg":
        clf: Any = LogisticRegression(C=params["C"], class_weight=_cw(params["class_weight"]), max_iter=3000)
        return Pipeline([("prep", _onehot()), ("clf", clf)])
    if algo == "random_forest":
        mf = params["max_features"]
        clf = RandomForestClassifier(n_estimators=params["n_estimators"], max_depth=params["max_depth"],
                                     min_samples_leaf=params["min_samples_leaf"], max_features=mf if mf == "sqrt" else float(mf),
                                     class_weight=_cw(params["class_weight"]), n_jobs=n_jobs, random_state=seed)  # fmt: skip
        return Pipeline([("prep", _onehot()), ("clf", clf)])
    if algo == "hgb":
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan, encoded_missing_value=np.nan,
                             min_frequency=MIN_FREQ, max_categories=60)  # fmt: skip
        prep = ColumnTransformer([("num", "passthrough", NUM), ("cat", enc, CAT)])
        clf = HistGradientBoostingClassifier(
            learning_rate=params["learning_rate"], max_iter=params["max_iter"], max_leaf_nodes=params["max_leaf_nodes"],
            min_samples_leaf=params["min_samples_leaf"], l2_regularization=params["l2_regularization"],
            class_weight=_cw(params["class_weight"]), early_stopping=False, random_state=seed,
            categorical_features=list(range(len(NUM), len(NUM) + len(CAT))),
        )  # fmt: skip
        return Pipeline([("prep", prep), ("clf", clf)])
    raise ValueError(f"Algoritmo desconocido: {algo}")


Baseline = Callable[[pd.DataFrame], np.ndarray]
BASELINES: dict[str, tuple[str, Baseline]] = {
    "epss": ("EPSS (sin entrenar)", lambda d: d["epss"].fillna(0).to_numpy(dtype=float)),
    "cvss": ("CVSS de la CNA (sin entrenar)", lambda d: d["cvss"].fillna(0).to_numpy(dtype=float)),
}


def catalog() -> list[dict[str, Any]]:
    return [{"key": k, **v, "space": SPACES[k], "defaults": defaults(k)} for k, v in ALGORITHMS.items()]
