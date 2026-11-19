"""Métricas del laboratorio, ponderadas con el peso de cada fila (los negativos están muestreados): así reflejan la
proporción real de KEV. Las comparten el entrenamiento (Fase 2) y la evaluación (Fase 3)."""

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def recall_at(y: np.ndarray, s: np.ndarray, w: np.ndarray, share: float) -> float | None:
    """Parte de los positivos que quedan en el primer `share` del universo (ponderado) al ordenar por puntaje."""
    if y.sum() == 0:
        return None
    order = np.argsort(-s, kind="stable")
    cw = np.cumsum(w[order])
    top = cw <= share * cw[-1]
    return float(y[order][top].sum() / y.sum())


def evaluate(y: np.ndarray, s: np.ndarray, w: np.ndarray) -> dict[str, Any]:
    """PR-AUC (precisión media), ROC-AUC y cobertura en el 1 % y el 5 % superior. None si falta una de las clases."""
    y = np.asarray(y, dtype=int)
    s = np.nan_to_num(np.asarray(s, dtype=float), nan=0.0)
    w = np.asarray(w, dtype=float)
    pos = int(y.sum())
    out: dict[str, Any] = {"rows": int(len(y)), "positives": pos, "prevalence_pct": round(100 * float(w[y == 1].sum() / w.sum()), 5) if len(y) else None}
    if pos == 0 or pos == len(y):
        return out | {"pr_auc": None, "roc_auc": None, "recall_1pct": None, "recall_5pct": None}
    return out | {
        "pr_auc": round(float(average_precision_score(y, s, sample_weight=w)), 5),
        "roc_auc": round(float(roc_auc_score(y, s, sample_weight=w)), 4),
        "recall_1pct": round(recall_at(y, s, w, 0.01) or 0.0, 4),
        "recall_5pct": round(recall_at(y, s, w, 0.05) or 0.0, 4),
    }  # fmt: skip
