"""Fase 6: inferencia individual. Para un CVE (del dataset o con valores a mano): probabilidad CALIBRADA de entrar a KEV
en el horizonte del dataset, con su intervalo, severidad (banda), posición en el universo y explicación por oclusión.

- Calibración de Platt en VALIDACIÓN (no en prueba): logit(p) = a·logit(puntaje) + b, ajustada con los pesos de cada fila
  (los negativos están muestreados). El puntaje de los modelos no es una probabilidad (se entrenan con pesos balanceados).
  Platt tiene 2 parámetros: con ~90 positivos en validación es más estable que la isotónica.
- Intervalo individual: 200 calibraciones bootstrap estratificadas (positivos y negativos por separado) en validación.
- Severidad por posición en el universo de validación: Crítica = 1 % superior (el punto de operación de la Fase 3),
  Alta = 1 a 5 %, Media = 5 a 20 %, Baja = el resto. Así una banda significa «cuánto hay que revisar», no un umbral arbitrario.
- La calibración se verifica en PRUEBA (meses que no vio): observado/esperado, pendiente e intercepto
  de calibración con IC bootstrap (suman el error de calibrar y el azar de prueba), Brier frente a predecir la tasa base, Hosmer-Lemeshow por tramos y tasa real por banda (Wilson).
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats  # chi² de Hosmer-Lemeshow

from app.ml import algorithms as algs
from app.ml import explain as xp
from app.services.descriptive import _num

EPS = 1e-6
N_BOOT = 200
BANDS: list[dict[str, Any]] = [
    {"key": "critica", "label": "Crítica", "top": 0.01, "meaning": "Entre el 1 % del universo con mayor probabilidad: revisar ya."},
    {"key": "alta", "label": "Alta", "top": 0.05, "meaning": "Entre el 1 % y el 5 % superior: revisar esta semana."},
    {"key": "media", "label": "Media", "top": 0.20, "meaning": "Entre el 5 % y el 20 % superior: vigilar."},
    {"key": "baja", "label": "Baja", "top": 1.0, "meaning": "El 80 % restante: prioridad normal."},
]  # fmt: skip
RELIABILITY_TOPS = [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]  # tramos para la curva de fiabilidad y Hosmer-Lemeshow
HOW_TO_READ = {
    "probability": ("Probabilidad CALIBRADA de que el CVE entre a KEV en el horizonte del dataset. El modelo da un puntaje para ordenar; "
                    "la calibración (ajustada en validación) lo traduce a una frecuencia esperada. El intervalo sale de recalibrar 200 veces "
                    "con remuestreo: si es ancho, la cifra exacta es incierta aunque el orden sea útil."),
    "band": ("La banda depende de la posición del CVE en el universo de validación: Crítica es el 1 % con mayor puntaje (el mismo punto de "
             "operación de la Fase 3). La tabla de bandas dice qué fracción de cada una entró de verdad a KEV en prueba."),
    "attribution": ("Cuánto multiplica la probabilidad calibrada cada grupo de variables frente a taparlo con un valor típico (mediana o "
                    "categoría más común de desarrollo). ×3 = con ese grupo la probabilidad es el triple; ×0,5 = la mitad. "
                    "«Sin él» es la banda que tendría el CVE con el grupo tapado."),
    "calibration": ("Se verifica en prueba, con meses que ni el modelo ni la calibración vieron. Observado/esperado cerca de 1 y pendiente "
                    "cerca de 1 indican buena calibración; pendiente menor que 1 = predicciones demasiado extremas. El Brier se compara con "
                    "predecir siempre la tasa base (mejora > 0 = aporta)."),
    "reliability": ("Cada tramo agrupa a los CVE por su posición (0,1 % superior, 0,1 a 0,5 %…). Si la calibración es buena, la "
                    "probabilidad media predicha y la tasa observada se parecen. Con pocos positivos por tramo los intervalos son anchos."),
}  # fmt: skip


def _logit(s: Any) -> np.ndarray:
    v = np.clip(np.asarray(s, dtype=float), EPS, 1 - EPS)
    out: np.ndarray = np.log(v / (1 - v))
    return out


def _platt(x: np.ndarray, y: np.ndarray, w: np.ndarray, iters: int = 100) -> tuple[float, float]:
    """Regresión logística ponderada de 2 parámetros (logit(p) = a·x + b) por Newton-Raphson, sin regularización.
    Converge en pocas iteraciones; un solver genérico sin escalar x se detenía lejos del óptimo."""
    X = np.column_stack([x, np.ones_like(x)])
    pbar = float(np.clip((w * y).sum() / w.sum(), EPS, 1 - EPS))
    beta = np.array([1.0, np.log(pbar / (1 - pbar)) - float((w * x).sum() / w.sum())])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ beta, -35, 35)))
        g = X.T @ (w * (y - p))
        h = (X * (w * p * (1 - p))[:, None]).T @ X + 1e-9 * np.eye(2)
        step = np.linalg.solve(h, g)
        norm = float(np.abs(step).max())
        if norm > 5:  # amortigua pasos enormes (separación casi perfecta)
            step *= 5 / norm
        beta += step
        if norm < 1e-9:
            break
    return float(beta[0]), float(beta[1])


def _boot_weights(y: np.ndarray, w: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Pesos de una réplica bootstrap estratificada (positivos y negativos por separado): w × veces elegida."""
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
    out: np.ndarray = w * np.bincount(idx, minlength=len(y))
    return out


def apply(params: tuple[float, float] | list[float], score: Any) -> np.ndarray:
    a, b = params
    out: np.ndarray = np.atleast_1d(1 / (1 + np.exp(-(a * _logit(score) + b))))
    return out


def _threshold(score: np.ndarray, w: np.ndarray, top: float) -> float:
    """Puntaje a partir del cual queda el `top` (fracción ponderada) del universo."""
    order = np.argsort(-score)
    cw = np.cumsum(w[order]) / w.sum()
    return float(score[order][min(int(np.searchsorted(cw, top)), len(score) - 1)])


def top_grid(score: np.ndarray, w: np.ndarray) -> dict[str, list[float]]:
    tops = np.geomspace(1e-5, 1, 300)
    return {"top": [float(t) for t in tops], "score": [_threshold(score, w, float(t)) for t in tops]}


def top_of(grid: dict[str, Any], s: float) -> float:
    """Fracción del universo con un puntaje mayor o igual (posición: 0,01 = 1 % superior)."""
    thr, tops = np.asarray(grid["score"])[::-1], np.asarray(grid["top"])[::-1]
    return float(np.interp(s, thr, tops, left=1.0, right=float(tops[0])))


def band_of(thresholds: dict[str, float], s: float) -> str:
    for b in BANDS[:-1]:
        if s >= thresholds[b["key"]]:
            return str(b["key"])
    return "baja"


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def calibrate(preds: pd.DataFrame, seed: int = 7, n_boot: int = N_BOOT) -> dict[str, Any]:
    """Calibración en validación, bandas por posición y verificación completa en prueba."""
    val = preds[preds["split"] == "validacion"]
    test = preds[preds["split"] == "prueba"]
    if val["label"].sum() < 5 or test.empty:
        raise ValueError("Hacen falta al menos 5 positivos en validación y datos de prueba para calibrar")
    sv, yv, wv = val["score"].to_numpy(float), val["label"].to_numpy(int), val["weight"].to_numpy(float)
    params = _platt(_logit(sv), yv, wv)
    rng = np.random.default_rng(seed)
    boot = []
    xv = _logit(sv)
    for _ in range(n_boot):
        boot.append(_platt(xv, yv, _boot_weights(yv, wv, rng)))
    thresholds = {b["key"]: _threshold(sv, wv, b["top"]) for b in BANDS[:-1]}
    base_val = float((wv * yv).sum() / wv.sum())

    st, yt, wt = test["score"].to_numpy(float), test["label"].to_numpy(int), test["weight"].to_numpy(float)
    pt = apply(params, st)
    base_test = float((wt * yt).sum() / wt.sum())
    obs, exp = float((wt * yt).sum()), float((wt * pt).sum())

    def wmean(v: np.ndarray) -> float:
        return float((wt * v).sum() / wt.sum())

    brier_raw, brier_cal, brier_ref = wmean((st - yt) ** 2), wmean((pt - yt) ** 2), wmean((base_val - yt) ** 2)
    slope, intercept = _platt(_logit(pt), yt, wt)
    # Intervalos que suman las dos fuentes de error: la calibración (cada réplica usa una calibración bootstrap de
    # validación) y el azar de prueba (remuestreo estratificado; el conteo de positivos, por Poisson).
    sl, it, oe = [], [], []
    for bp in boot:
        wb = _boot_weights(yt, wt, rng)
        pb = apply(bp, st)
        a, b = _platt(_logit(pb), yt, wb)
        sl.append(a)
        it.append(b)
        oe.append(float(rng.poisson(obs)) / float((wb * pb).sum()))

    bands_t = np.array([band_of(thresholds, s) for s in st])
    total_pos = max(1.0, obs)
    band_rows = []
    for band in BANDS:
        m = bands_t == band["key"]
        n_w, k = float(wt[m].sum()), float((wt[m] * yt[m]).sum())
        rate = k / n_w if n_w else 0.0
        lo_b, hi_b = wilson(k, n_w)
        band_rows.append({"key": band["key"], "label": band["label"], "meaning": band["meaning"], "share": round(n_w / wt.sum(), 5),
                          "rows": int(m.sum()), "positives": int(k), "rate": rate, "rate_lo": lo_b, "rate_hi": hi_b,
                          "pred": float((wt[m] * pt[m]).sum() / n_w) if n_w else None,
                          "lift": rate / base_test if base_test else None, "recall": k / total_pos})  # fmt: skip

    edges = [_threshold(sv, wv, t) for t in RELIABILITY_TOPS[:-1]]
    rel, hl = [], 0.0
    prev = np.inf
    for t, e in zip(RELIABILITY_TOPS, [*edges, -np.inf], strict=True):
        m = (st < prev) & (st >= e)
        prev = e
        n_w = float(wt[m].sum())
        if n_w <= 0:
            continue
        k, e_g = float((wt[m] * yt[m]).sum()), float((wt[m] * pt[m]).sum())
        lo_r, hi_r = wilson(k, n_w)
        rel.append({"top": t, "rows": int(m.sum()), "positives": int(k), "expected": e_g, "pred": e_g / n_w, "obs": k / n_w,
                    "obs_lo": lo_r, "obs_hi": hi_r})  # fmt: skip
        if e_g > 0:
            hl += (k - e_g) ** 2 / (e_g * max(1e-12, 1 - e_g / n_w))
    df_hl = max(1, len(rel) - 2)
    out = {
        "params": list(params), "boot": [list(p) for p in boot], "thresholds": thresholds, "grid": top_grid(sv, wv),
        "base_rate": {"validacion": base_val, "prueba": base_test},
        "test": {
            "observed": obs, "expected": exp, "oe": obs / exp if exp else None,
            "oe_lo": float(np.percentile(oe, 2.5)), "oe_hi": float(np.percentile(oe, 97.5)),
            "slope": slope, "slope_lo": float(np.percentile(sl, 2.5)), "slope_hi": float(np.percentile(sl, 97.5)),
            "intercept": intercept, "intercept_lo": float(np.percentile(it, 2.5)), "intercept_hi": float(np.percentile(it, 97.5)),
            "brier_raw": brier_raw, "brier_cal": brier_cal, "brier_ref": brier_ref, "brier_skill": 1 - brier_cal / brier_ref if brier_ref else None,
            "hl": hl, "hl_df": df_hl, "hl_p": float(stats.chi2.sf(hl, df_hl)),
            "positives": int(obs), "rows": int(len(test)),
        },
        "bands": band_rows, "reliability": rel,
    }  # fmt: skip
    out["reading"] = calibration_notes(out)
    return out


def _pct(v: float | None, digits: int | None = None) -> str:
    if v is None:
        return "—"
    p = 100 * v
    d = digits if digits is not None else (1 if p >= 1 else 2 if p >= 0.1 else 3)
    return f"{_num(p, digits=d)} %"


def _x(v: float) -> str:
    """Factores y «veces»: sin decimales desde 10, uno desde 1 y dos por debajo (×3637, ×3,2, ×0,45)."""
    return _num(v, digits=0 if v >= 10 else 1 if v >= 1 else 2)


def calibration_notes(c: dict[str, Any]) -> list[str]:
    t = c["test"]
    out = []
    if t["oe"] is not None:
        lo, hi = round(t["oe_lo"], 2), round(t["oe_hi"], 2)  # se compara lo que se muestra
        verdict = ("compatible con una calibración correcta" if lo <= 1 <= hi
                   else "el modelo SUBESTIMA (entraron más de los esperados)" if lo > 1 else "el modelo SOBREESTIMA (entraron menos de los esperados)")  # fmt: skip
        out.append(f"En prueba la calibración esperaba {_num(t['expected'], digits=1)} entradas a KEV y hubo {t['positives']}: "
                   f"observado/esperado = {_num(t['oe'], digits=2)} (IC 95 % {_num(t['oe_lo'], digits=2)} a {_num(t['oe_hi'], digits=2)}), {verdict}.")  # fmt: skip
    s_lo, s_hi = round(t["slope_lo"], 2), round(t["slope_hi"], 2)
    shape = ("demasiado extremas (separa menos de lo que promete)" if s_hi < 1
             else "demasiado moderadas (separa más de lo que indica)" if s_lo > 1 else "de una dispersión compatible con la real")  # fmt: skip
    out.append(f"Pendiente de calibración {_num(t['slope'], digits=2)} (IC 95 % {_num(t['slope_lo'], digits=2)} a {_num(t['slope_hi'], digits=2)}): "
               f"las probabilidades son {shape}.")  # fmt: skip
    if t["brier_skill"] is not None:
        out.append(f"Brier calibrado {_num(t['brier_cal'], digits=6)} frente a {_num(t['brier_ref'], digits=6)} de predecir siempre la tasa base "
                   f"(mejora {_num(100 * t['brier_skill'], digits=1)} %); el puntaje sin calibrar tiene {_num(t['brier_raw'], digits=4)}: "
                   "por eso no se muestra como probabilidad.")  # fmt: skip
    out.append(f"Hosmer-Lemeshow por tramos: χ² = {_num(t['hl'], digits=1)} con {t['hl_df']} g.l., p = "
               f"{'< 0,001' if t['hl_p'] < 0.001 else _num(t['hl_p'], digits=3)}"
               f"{' (diferencias significativas entre predicho y observado)' if t['hl_p'] < 0.05 else ' (sin diferencias significativas)'}. "
               "Con pesos de muestreo y pocos positivos es aproximado.")  # fmt: skip
    crit = next(b for b in c["bands"] if b["key"] == "critica")
    if crit["share"] > 0.015 or crit["share"] < 0.0066:
        out.append(f"En prueba la banda Crítica abarcó el {_pct(crit['share'])} del universo, no el 1 % de validación: los puntajes "
                   "se desplazaron entre los meses de validación y los de prueba (deriva). Las bandas siguen ordenando, pero "
                   "conviene recalibrar con meses recientes.")  # fmt: skip
    if crit["lift"] is not None:
        out.append(f"En la banda Crítica (1 % del universo) entró a KEV el {_pct(crit['rate'])} (IC 95 % {_pct(crit['rate_lo'])} a {_pct(crit['rate_hi'])}), "
                   f"{_x(crit['lift'])} veces la tasa base de prueba, y concentra el {_num(100 * crit['recall'], digits=0)} % de las entradas.")  # fmt: skip
    return out


def frame(values: dict[str, Any]) -> pd.DataFrame:
    row: dict[str, Any] = {c: values.get(c) for c in algs.NUM + algs.CAT}
    for c in algs.NUM:
        row[c] = np.nan if row[c] is None else float(row[c])
    for c in algs.CAT:
        row[c] = "desconocido" if row[c] in (None, "") else str(row[c])
    return pd.DataFrame([row])


def predict(bundle: dict[str, Any], row: pd.DataFrame, cal: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Predicción de UNA fila: puntaje, probabilidad calibrada con IC 90 %, banda, posición y atribución por oclusión."""
    model, drop = bundle["pipeline"], tuple(bundle.get("drop", []))
    s = float(xp._predict(model, row, drop)[0])
    p = float(apply(cal["params"], s)[0])
    ps = np.array([apply(b, s)[0] for b in cal["boot"]])
    alts: list[tuple[str, pd.DataFrame]] = []
    for g, cols in xp.GROUPS.items():
        alt = row.copy()
        for c in cols:
            alt[c] = base[c]
        alts.append((g, alt))
    alt_scores = xp._predict(model, pd.concat([a for _, a in alts], ignore_index=True), drop)
    attributions: list[dict[str, Any]] = []
    for (g, _), sa in zip(alts, alt_scores, strict=True):
        pa = float(apply(cal["params"], sa)[0])
        attributions.append({"group": g, "factor": p / pa if pa > 0 else None, "delta_score": s - float(sa),
                             "band_without": band_of(cal["thresholds"], float(sa))})  # fmt: skip
    attributions.sort(key=lambda a: -abs(np.log(a["factor"])) if a["factor"] else 0)
    dropped = {c for g in drop for c in algs.GROUPS[g]["columns"]}
    for a in attributions:
        a["unused"] = set(xp.GROUPS[a["group"]]) <= dropped
    base_rate = cal["base_rate"]["validacion"]
    return {"score": s, "probability": p, "p_lo": float(np.percentile(ps, 5)), "p_hi": float(np.percentile(ps, 95)),
            "band": band_of(cal["thresholds"], s), "top": top_of(cal["grid"], s), "lift": p / base_rate if base_rate else None,
            "base_rate": base_rate, "attributions": attributions}  # fmt: skip


def reading(res: dict[str, Any], cal: dict[str, Any], horizon: int, case: dict[str, Any] | None) -> list[str]:
    band = next(b for b in BANDS if b["key"] == res["band"])
    out = [f"Probabilidad calibrada de entrar a KEV en los próximos {horizon} días: {_pct(res['probability'])} "
           f"(IC 90 % {_pct(res['p_lo'])} a {_pct(res['p_hi'])}), {_x(res['lift'] or 0)} veces la tasa base del universo "
           f"({_pct(res['base_rate'])})."]  # fmt: skip
    top = res["top"]
    pos = "< 0,001 %" if top <= 1e-5 else _pct(top)
    out.append(f"Queda en el {pos} superior del universo: severidad {band['label']}. {band['meaning']}")
    stat = next(b for b in cal["bands"] if b["key"] == res["band"])
    out.append(f"En prueba, de los CVE en la banda {band['label']} entró a KEV el {_pct(stat['rate'])} "
               f"(IC 95 % {_pct(stat['rate_lo'])} a {_pct(stat['rate_hi'])}).")  # fmt: skip
    used = [a for a in res["attributions"] if a["factor"] and not a["unused"]]
    up = [a for a in used if a["factor"] >= 1.1][:2]
    down = [a for a in used if a["factor"] <= 1 / 1.1][:2]
    if up:
        out.append("Lo que más la sube: " + " y ".join(f"{a['group']} (×{_x(a['factor'])})" for a in up) + ".")
    if down:
        out.append("Lo que más la baja: " + " y ".join(f"{a['group']} (×{_x(a['factor'])})" for a in down) + ".")
    if not up and not down:
        out.append("Ningún grupo de variables cambia la probabilidad más de un 10 % frente a su valor típico.")
    if case is None:
        out.append("Valores ingresados a mano: es un escenario hipotético, no un CVE real.")
    else:
        if case["split"] == "desarrollo":
            out.append("Ojo: esta fila se usó para ENTRENAR el modelo; su predicción no sirve como prueba.")
        if case["label"]:
            out.append(f"Resultado real: entró a KEV el {case['kev_date']}, {case['days_to_kev']} días después de la foto.")
        else:
            out.append(f"Resultado real: no entró a KEV en los {horizon} días siguientes a la foto.")
    return out


def options(dev: pd.DataFrame) -> dict[str, Any]:
    """Valores típicos y rangos para el formulario: categorías más frecuentes y percentiles 1/99 de las numéricas."""
    cats = {c: [str(v) for v in dev[c].astype(str).value_counts().head(40 if c in ("cna", "cwe") else 12).index] for c in algs.CAT}
    nums = {}
    for c in algs.NUM:
        s = dev[c].dropna()
        nums[c] = {"p01": float(s.quantile(0.01)) if len(s) else 0.0, "p99": float(s.quantile(0.99)) if len(s) else 0.0}
    return {"categorical": cats, "numeric": nums}
