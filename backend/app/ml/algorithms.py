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
LOG = {
    "epss": 1e-5,
    "days_published": 1.0,
    "edb_exploits": 1.0,
    "cna_kev_prior": 1.0,
}  # log(x + c): colas largas
MIN_FREQ = 20  # categorías con menos filas se agrupan en «otras» (CWE y CNA tienen cientos)

SPACES: dict[str, list[dict[str, Any]]] = {
    # Protocolo de la Fase 2 (F2_protocolo.md §5): pocos hiperparámetros (≈ 400 eventos en desarrollo) y SIN class_weight
    # (los negativos ya llevan el peso 1/tasa del muestreo; «balanced» corregiría el desbalance dos veces).
    "logreg": [
        {"name": "C", "type": "float_log", "low": 1e-4, "high": 1.0, "default": 0.01,
         "description": "Inverso de la regularización L2: valores bajos simplifican el modelo y evitan el sobreajuste."},
    ],
    "random_forest": [
        {"name": "max_depth", "type": "int", "low": 3, "high": 16, "default": 8, "description": "Profundidad máxima de cada árbol."},
        {"name": "min_samples_leaf", "type": "int", "log": True, "low": 5, "high": 200, "default": 30,
         "description": "Mínimo de filas en cada hoja: valores altos suavizan las predicciones."},
        {"name": "max_features", "type": "cat", "choices": ["sqrt", "0.3"], "default": "sqrt",
         "description": "Variables que considera cada división (azar entre árboles)."},
    ],
    "hgb": [
        {"name": "learning_rate", "type": "float_log", "low": 0.01, "high": 0.2, "default": 0.05, "description": "Tamaño del paso de cada árbol nuevo."},
        {"name": "max_leaf_nodes", "type": "int", "low": 4, "high": 31, "default": 15, "description": "Hojas por árbol (complejidad)."},
        {"name": "min_samples_leaf", "type": "int", "log": True, "low": 20, "high": 500, "default": 100, "description": "Mínimo de filas por hoja."},
        {"name": "l2_regularization", "type": "float_log", "low": 1e-3, "high": 10.0, "default": 0.1, "description": "Penalización L2 de las hojas."},
    ],
}  # fmt: skip

# Hiperparámetros fijos (no se optimizan): valor por defecto de cada algoritmo cuando `params` no los trae.
FIXED: dict[str, dict[str, Any]] = {
    "logreg": {"class_weight": "none", "max_iter": 3000, "tol": 1e-4},
    "random_forest": {"class_weight": "none", "n_estimators": 300},
    "hgb": {"class_weight": "none", "max_iter": None, "n_iter_no_change": 20, "tol": 1e-4, "max_iter_cap": 500, "es_fraction": 0.2},
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
    "epss_version": {"label": "versión de EPSS", "columns": ["epss_model", "epss_delta"]},
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


# Límites absolutos que acepta el editor del espacio de búsqueda (Fase 7): más amplios que el espacio por defecto,
# pero dentro de lo que el algoritmo admite y de un tiempo de ajuste razonable.
LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "logreg": {"C": (1e-5, 100.0)},
    "random_forest": {"max_depth": (2, 30), "min_samples_leaf": (1, 500)},
    "hgb": {"learning_rate": (0.005, 1.0), "max_leaf_nodes": (4, 255), "min_samples_leaf": (1, 1000),
            "l2_regularization": (1e-6, 10.0)},
}  # fmt: skip


def custom_space(algo: str, overrides: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Espacio de búsqueda con rangos o categorías propios. Valida contra LIMITS y deja el valor por defecto dentro
    del rango (es la prueba 0). Sin cambios devuelve el espacio de siempre."""
    if algo not in SPACES:
        raise ValueError(f"Algoritmo desconocido: {algo}")
    overrides = overrides or {}
    unknown = set(overrides) - {p["name"] for p in SPACES[algo]}
    if unknown:
        raise ValueError(f"Hiperparámetros desconocidos para {algo}: {', '.join(sorted(unknown))}")
    out = []
    for p in SPACES[algo]:
        q = dict(p)
        o = overrides.get(p["name"]) or {}
        if p["type"] == "cat":
            if "choices" in o:
                choices = [c for c in p["choices"] if c in set(o["choices"])]
                if not choices or len(choices) != len(set(o["choices"])):
                    raise ValueError(
                        f"{p['name']}: elija una o más opciones válidas ({', '.join(p['choices'])})"
                    )
                q["choices"] = choices
            if q["default"] not in q["choices"]:
                q["default"] = q["choices"][0]
        else:
            lo_lim, hi_lim = LIMITS[algo][p["name"]]
            lo, hi = float(o.get("low", p["low"])), float(o.get("high", p["high"]))
            if p["type"] == "int":
                lo, hi = float(round(lo)), float(round(hi))
            if not (lo_lim <= lo < hi <= hi_lim):
                raise ValueError(
                    f"{p['name']}: el rango debe cumplir {_lim(lo_lim)} ≤ mínimo < máximo ≤ {_lim(hi_lim)}"
                )
            q["low"], q["high"] = (int(lo), int(hi)) if p["type"] == "int" else (lo, hi)
            q["default"] = min(max(p["default"], q["low"]), q["high"])
        out.append(q)
    return out


def _lim(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def defaults(algo: str, space: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {p["name"]: p["default"] for p in (space or SPACES[algo])}


def suggest(trial: Any, algo: str, space: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Hiperparámetros propuestos por Optuna dentro del espacio del algoritmo (o del espacio propio de la Fase 7)."""
    out: dict[str, Any] = {}
    for p in space or SPACES[algo]:
        if p["type"] == "float_log":
            out[p["name"]] = trial.suggest_float(p["name"], p["low"], p["high"], log=True)
        elif p["type"] == "int":
            out[p["name"]] = trial.suggest_int(p["name"], p["low"], p["high"], log=bool(p.get("log", False)))
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
        clf: Any = LogisticRegression(
            C=params["C"],
            class_weight=_cw(params.get("class_weight", "none")),
            max_iter=FIXED["logreg"]["max_iter"],
            tol=FIXED["logreg"]["tol"],
        )
        return Pipeline([("prep", _onehot()), ("clf", clf)])
    if algo == "random_forest":
        mf = params["max_features"]
        clf = RandomForestClassifier(n_estimators=params.get("n_estimators", FIXED["random_forest"]["n_estimators"]), max_depth=params["max_depth"],
                                     min_samples_leaf=params["min_samples_leaf"], max_features=mf if mf == "sqrt" else float(mf),
                                     class_weight=_cw(params.get("class_weight", "none")), n_jobs=n_jobs, random_state=seed)  # fmt: skip
        return Pipeline([("prep", _onehot()), ("clf", clf)])
    if algo == "hgb":
        enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan, encoded_missing_value=np.nan,
                             min_frequency=MIN_FREQ, max_categories=60)  # fmt: skip
        prep = ColumnTransformer([("num", "passthrough", NUM), ("cat", enc, CAT)])
        clf = HistGradientBoostingClassifier(
            learning_rate=params["learning_rate"], max_iter=int(params.get("max_iter") or FIXED["hgb"]["max_iter_cap"]), max_leaf_nodes=params["max_leaf_nodes"],
            min_samples_leaf=params["min_samples_leaf"], l2_regularization=params["l2_regularization"],
            class_weight=_cw(params.get("class_weight", "none")), early_stopping=False, random_state=seed,
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
    limits = {k: {n: {"low": lo, "high": hi} for n, (lo, hi) in v.items()} for k, v in LIMITS.items()}
    return [
        {"key": k, **v, "space": SPACES[k], "defaults": defaults(k), "limits": limits[k]}
        for k, v in ALGORITHMS.items()
    ]
