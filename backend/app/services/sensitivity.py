"""Análisis de sensibilidad de los pesos del score (adaptación de la «Optuna UI» del Promptuario, sin entrenar nada).

Pregunta: si los pesos fueran otros, ¿cambiaría la lista de qué remediar primero? Se prueban N combinaciones de pesos al
azar (reproducibles, suman 1, dentro de los rangos pedidos) y, para cada una, se recalcula el score de todos los
hallazgos abiertos con la MISMA fórmula de scoring.risk_score (vectorizada) y se compara con la configuración vigente.
Es solo consulta: no cambia la configuración ni el inventario.
"""

import time
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.services.descriptive import _num, load_frame
from app.services.evaluation import _quality_of, auc
from app.services.scoring import ScoringParams

WEIGHTS = ("w_epss", "w_percentile", "w_cvss", "w_asset")
LABELS = {"w_epss": "EPSS", "w_percentile": "Percentil EPSS", "w_cvss": "CVSS", "w_asset": "Criticidad del activo"}
TOP_K = 10
MAX_TRIALS = 1000

HOW_TO_READ = {
    "trials": (
        "Cada punto es una combinación de pesos. Eje horizontal: cuánto se parece su orden de prioridad al vigente (Spearman: "
        "1 es idéntico). Eje vertical: qué tan bien su score sin KEV separa los CVE en KEV (AUC). Lo ideal es arriba; la "
        "configuración vigente está marcada."
    ),
    "importance": (
        "Cuánto se asocia cada peso con el cambio del orden de prioridad entre las pruebas (correlación de rangos en valor "
        "absoluto, normalizada a 100 %). Un peso con importancia alta es el que más conviene ajustar con cuidado."
    ),
    "best": "Las combinaciones con mejor AUC entre las que mantienen al menos 8 de los 10 primeros hallazgos vigentes.",
}


def scores(df: pd.DataFrame, w: dict[str, float], p: ScoringParams) -> tuple[np.ndarray, np.ndarray]:
    """Score completo y score sin KEV de cada hallazgo, idénticos a scoring.risk_score (los ausentes cuentan 0)."""
    e = df["epss"].fillna(0).to_numpy() / 100  # el frame trae EPSS en %
    base = (w["w_epss"] * e + w["w_percentile"] * df["percentile"].fillna(0).to_numpy()
            + w["w_cvss"] * df["cvss"].fillna(0).to_numpy() / 10 + w["w_asset"] * df["criticality"].to_numpy() / 4)  # fmt: skip
    kev = df["in_kev"].to_numpy(dtype=bool)
    bonus = np.where(df["ransomware"].to_numpy(dtype=bool), p.ransomware_bonus, 0.0)
    full = np.where(kev, np.minimum(100.0, p.kev_floor + (100 - p.kev_floor) * base + bonus), (p.kev_floor - 1) * base)
    return np.round(full, 2), np.round((p.kev_floor - 1) * base, 2)


def _band(s: np.ndarray, p: ScoringParams) -> np.ndarray:
    return np.select([s >= p.band_critical, s >= p.band_high, s >= p.band_medium], [3, 2, 1], 0)


def _sample(n: int, seed: int, bounds: dict[str, tuple[float, float]]) -> list[dict[str, float]]:
    """Combinaciones al azar sobre el simplex (Dirichlet), dentro de los rangos pedidos; reproducibles por semilla."""
    rng = np.random.default_rng(seed)
    lo = np.array([bounds[k][0] for k in WEIGHTS])
    hi = np.array([bounds[k][1] for k in WEIGHTS])
    if lo.sum() > 1 + 1e-9 or hi.sum() < 1 - 1e-9:
        raise ValueError("Con esos rangos ninguna combinación suma 1")
    out: list[dict[str, float]] = []
    for _ in range(200):  # muestreo con rechazo, por lotes
        cand = rng.dirichlet(np.full(len(WEIGHTS), 1.5), size=n * 4)
        ok = cand[np.all((cand >= lo - 1e-9) & (cand <= hi + 1e-9), axis=1)]
        for row in ok[: n - len(out)]:
            first = [round(float(x), 3) for x in row[:-1]]
            last = round(1 - sum(first), 3)
            if last < 0:  # el redondeo dejó el último en negativo (valores ínfimos): se descuenta del mayor
                first[first.index(max(first))] = round(max(first) + last, 3)
                last = 0.0
            out.append(dict(zip(WEIGHTS, [*first, last], strict=True)))  # suma exacta 1
        if len(out) >= n:
            return out
    raise ValueError("Los rangos son demasiado estrechos: no se encontraron combinaciones suficientes")


def run(df: pd.DataFrame, p: ScoringParams, n_trials: int = 200, seed: int = 7,
        bounds: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:  # fmt: skip
    t0 = time.perf_counter()
    bounds = {k: (bounds or {}).get(k, (0.0, 1.0)) for k in WEIGHTS}
    out: dict[str, Any] = {"n_findings": int(len(df)), "how_to_read": HOW_TO_READ, "config": {"n_trials": n_trials, "seed": seed,
                           "bounds": {k: list(v) for k, v in bounds.items()}}}  # fmt: skip
    if len(df) < 3:
        return out | {"trials": [], "importance": [], "best": [], "current": None,
                      "interpretation": ["Hacen falta al menos 3 hallazgos abiertos para comparar órdenes de prioridad."]}  # fmt: skip
    current_w = {k: float(getattr(p, k)) for k in WEIGHTS}
    ref, _ = scores(df, current_w, p)
    ref_rank = pd.Series(ref).rank(method="average")
    k = min(TOP_K, len(df))
    ref_top = set(np.argsort(-ref, kind="stable")[:k])
    ref_band = _band(ref, p)
    cve = df["cve_id"].to_numpy()
    kev_cve = df.groupby("cve_id")["in_kev"].max()
    two_classes = 0 < int(kev_cve.sum()) < len(kev_cve)

    def evaluate(w: dict[str, float], trial: int) -> dict[str, Any]:
        full, nokev = scores(df, w, p)
        rho = float(ref_rank.corr(pd.Series(full).rank(method="average"))) if len(df) > 2 else 1.0
        top = set(np.argsort(-full, kind="stable")[:k])
        per_cve = pd.Series(nokev).groupby(cve).max()
        a = auc(per_cve.tolist(), [bool(kev_cve[c]) for c in per_cve.index]) if two_classes else None
        return {"trial": trial, **w, "spearman": round(rho if not np.isnan(rho) else 1.0, 4), "top_overlap": len(top & ref_top),
                "band_changes": int((_band(full, p) != ref_band).sum()), "auc": round(a, 4) if a is not None else None}  # fmt: skip

    trials = [evaluate(current_w, 0) | {"current": True}]
    trials += [evaluate(w, i) | {"current": False} for i, w in enumerate(_sample(n_trials, seed, bounds), start=1)]
    t = pd.DataFrame(trials)
    out["trials"] = trials
    out["current"] = trials[0]
    out["elapsed_ms"] = round(1000 * (time.perf_counter() - t0), 1)
    out["top_k"] = k

    # Importancia: |correlación de rangos| entre cada peso y el parecido con el orden vigente, normalizada.
    rest = t.iloc[1:]
    raw = {w: abs(float(rest[w].rank().corr(rest["spearman"].rank()))) for w in WEIGHTS}  # Spearman = Pearson de rangos (sin SciPy)
    raw = {w: (0.0 if np.isnan(v) else v) for w, v in raw.items()}
    total = sum(raw.values()) or 1.0
    out["importance"] = sorted(({"weight": w, "label": LABELS[w], "pct": round(100 * v / total, 1)} for w, v in raw.items()),
                               key=lambda x: -x["pct"])  # fmt: skip
    stable = rest[rest["top_overlap"] >= max(1, round(0.8 * k))]
    best = stable.sort_values(["auc", "spearman"], ascending=False).head(5) if two_classes else stable.head(0)
    out["best"] = best.to_dict("records")
    out["interpretation"] = _notes(out, rest, two_classes)
    return out


def _notes(out: dict[str, Any], rest: pd.DataFrame, two_classes: bool) -> list[str]:
    k, cur = out["top_k"], out["current"]
    notes = [
        f"Se probaron {len(rest)} combinaciones de pesos sobre {out['n_findings']} hallazgos abiertos en {_num(out['elapsed_ms'], digits=0)} ms.",
        f"En promedio, {_num(float(rest['top_overlap'].mean()), digits=1)} de los {k} primeros hallazgos vigentes siguen entre los {k} primeros, "
        f"y el orden se parece al vigente con un Spearman mediano de {_num(float(rest['spearman'].median()), digits=2)}.",
    ]  # fmt: skip
    low = float(rest["spearman"].quantile(0.05))
    notes.append(
        "La prioridad casi no depende de los pesos: KEV (el piso del score) ordena lo urgente."
        if low >= 0.9 else
        f"Los pesos sí importan: en el 5 % de combinaciones más distintas, el parecido baja a {_num(low, digits=2)}."
    )  # fmt: skip
    if out["importance"]:
        top = out["importance"][0]
        notes.append(f"El peso que más mueve el orden es {top['label']} ({_num(top['pct'], digits=0)} % de la importancia).")
    notes.append(f"En la mediana, {_num(float(rest['band_changes'].median()), digits=0)} hallazgos cambiarían de banda (y con ello de SLA).")
    if two_classes and cur["auc"] is not None:
        better = int((rest["auc"] > cur["auc"] + 0.01).sum())
        notes.append(f"La configuración vigente tiene un AUC de {_num(cur['auc'], digits=2)} ({_quality_of(cur['auc'])}) con el score sin KEV; "
                     f"{better} de {len(rest)} combinaciones lo superan por más de 0,01.")  # fmt: skip
        notes.append("El AUC se mide sobre este inventario: con pocos CVE y muchos en KEV es orientativo; no elija pesos solo por él.")
    else:
        notes.append("No se calcula el AUC: hacen falta CVE dentro y fuera de KEV.")
    return notes


def analyze(db: Session, n_trials: int, seed: int, bounds: dict[str, tuple[float, float]] | None) -> dict[str, Any]:
    from app.services.intel import get_active_config

    _, params = get_active_config(db)
    return run(load_frame(db), params, n_trials, seed, bounds)
