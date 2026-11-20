"""Fase 4: explicabilidad de un modelo entrenado (equivalentes tabulares de Grad-CAM++, mapas de atención y máscaras).

- Importancia global por PERMUTACIÓN (en prueba): cuánto cae el ROC-AUC si se desordena una variable o un grupo.
- Dependencia parcial 1D (cómo cambia la probabilidad media según el valor de una variable) y 2D (mapa de interacción
  entre las dos variables numéricas más importantes): el «mapa de atención» de un modelo tabular.
- Atribución por OCLUSIÓN («máscara»): para un CVE, cuánto cambia su probabilidad si se tapa cada grupo de variables
  con un valor típico. Es el análogo directo de Grad-CAM++/oclusión en imágenes, y vale para cualquier modelo.
- Coeficientes (solo regresión logística, que es interpretable por sí misma).
Todo se calcula sobre las variables en su escala original (días, puntaje EPSS, CVSS…), no sobre la transformada.
"""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.ml import algorithms as algs
from app.services.descriptive import _num

GROUPS: dict[str, list[str]] = {
    "EPSS": ["epss", "percentile", "epss_delta", "epss_model"],
    "CVSS de la CNA": ["cvss", "av", "ac", "pr", "ui"],
    "Antigüedad del CVE": ["days_published"],
    "Exploits públicos": ["edb_exploits"],
    "Historial KEV de la CNA": ["cna_kev_prior"],
    "CNA (quién publicó)": ["cna"],
    "Tipo de debilidad (CWE)": ["cwe"],
}
PDP_FEATURES = ["epss", "days_published", "cvss", "cna_kev_prior", "edb_exploits", "percentile"]
EQUIVALENCES = [
    {"promptuario": "Grad-CAM++", "aqui": "Atribución por oclusión",
     "porque": "Grad-CAM++ marca qué zona de una imagen pesó en la decisión. En datos tabulares, la oclusión mide cuánto cambia la "
               "probabilidad de un CVE si se tapa cada grupo de variables."},
    {"promptuario": "Mapas de atención", "aqui": "Importancia por permutación y mapa de interacción 2D",
     "porque": "Muestran en qué variables «se fija» el modelo en general y cómo combina las dos más importantes."},
    {"promptuario": "Visualización de máscaras", "aqui": "Máscaras por grupo de variables, caso por caso",
     "porque": "Cada barra de una explicación individual es el efecto de enmascarar ese grupo: aciertos, KEV que se escaparon y falsas alarmas."},
]  # fmt: skip
HOW_TO_READ = {
    "importance": ("Cuánto cae el ROC-AUC en prueba si se desordena esa variable (o grupo) rompiendo su relación con la etiqueta. "
                   "Más caída = el modelo depende más de ella. Una caída cercana a 0 indica que no la usa."),
    "pdp": ("Probabilidad media que da el modelo cuando todos los CVE toman ese valor de la variable (el resto queda igual). "
            "Muestra la forma de la relación: si sube, baja o se satura."),
    "pdp2d": ("Probabilidad media para cada combinación de las dos variables más importantes. Más intenso = mayor probabilidad de "
              "entrar a KEV. Si el patrón no es una simple suma de las dos, el modelo usa su interacción."),
    "local": ("Cada barra es lo que cambia el puntaje de ESE CVE al tapar el grupo con un valor típico (la mediana o la "
              "categoría más común). Barras hacia la derecha empujaron hacia «entra a KEV»; hacia la izquierda, en contra. "
              "Ojo: el puntaje sale de un modelo entrenado con pesos balanceados, así que NO es una probabilidad calibrada "
              "(un 99 % no significa 99 de cada 100): sirve para ordenar y comparar CVE entre sí."),
    "coef": ("En la regresión logística cada variable suma o resta al logit. Coeficiente positivo = sube la probabilidad. "
             "Las numéricas están estandarizadas, así que se pueden comparar entre sí."),
}  # fmt: skip


def _predict(model: Any, df: pd.DataFrame, drop: tuple[str, ...]) -> np.ndarray:
    out: np.ndarray = model.predict_proba(algs.prepare(df, drop))[:, 1]
    return out


def baseline_values(dev: pd.DataFrame) -> dict[str, Any]:
    """Valor «típico» con el que se tapa cada variable: mediana (numéricas) o categoría más común."""
    out: dict[str, Any] = {}
    for col in algs.NUM:
        out[col] = float(dev[col].median()) if dev[col].notna().any() else 0.0
    for col in algs.CAT:
        out[col] = dev[col].mode().iloc[0] if dev[col].notna().any() else "desconocido"
    return out


def permutation(model: Any, test: pd.DataFrame, drop: tuple[str, ...], repeats: int, seed: int,
                report: Any = None) -> dict[str, Any]:  # fmt: skip
    rng = np.random.default_rng(seed)
    y, w = test["label"].to_numpy(), test["weight"].to_numpy()
    base = float(roc_auc_score(y, _predict(model, test, drop), sample_weight=w))
    units: list[tuple[str, list[str], str]] = [(g, cols, "grupo") for g, cols in GROUPS.items()]
    units += [(c, [c], "variable") for c in algs.NUM + algs.CAT]
    rows = []
    for k, (name, cols, kind) in enumerate(units):
        if report:
            report(10 + int(45 * k / len(units)), f"Importancia por permutación: {name}")
        drops = []
        for _ in range(repeats):
            alt = test.copy()
            perm = rng.permutation(len(alt))
            for c in cols:  # el grupo se permuta junto (misma permutación): conserva su estructura interna
                alt[c] = alt[c].to_numpy()[perm]
            drops.append(base - float(roc_auc_score(y, _predict(model, alt, drop), sample_weight=w)))
        sd = float(np.std(drops, ddof=1)) if len(drops) > 1 else 0.0
        rows.append({"name": name, "kind": kind, "mean": round(float(np.mean(drops)), 4), "sd": round(sd, 4)})
    return {"base_roc_auc": round(base, 4), "rows": sorted(rows, key=lambda r: -r["mean"])}


def _grid(s: pd.Series, n: int) -> list[float]:
    v = s.dropna()
    if v.empty:
        return []
    return sorted({round(float(x), 6) for x in v.quantile(np.linspace(0.02, 0.98, n))})


def pdp(model: Any, sample: pd.DataFrame, drop: tuple[str, ...], features: list[str]) -> list[dict[str, Any]]:
    out = []
    for f in features:
        grid = _grid(sample[f], 15)
        pts = []
        for v in grid:
            alt = sample.copy()
            alt[f] = v
            pts.append({"x": v, "y": round(float(_predict(model, alt, drop).mean()), 6)})
        out.append({"feature": f, "points": pts})
    return out


def pdp2d(model: Any, sample: pd.DataFrame, drop: tuple[str, ...], fx: str, fy: str, n: int = 9) -> dict[str, Any]:
    gx, gy = _grid(sample[fx], n), _grid(sample[fy], n)
    cells = []
    for vy in gy:
        for vx in gx:
            alt = sample.copy()
            alt[fx], alt[fy] = vx, vy
            cells.append({"x": vx, "y": vy, "p": round(float(_predict(model, alt, drop).mean()), 6)})
    return {"x": fx, "y": fy, "xs": gx, "ys": gy, "cells": cells}


def occlusion(model: Any, rows: pd.DataFrame, drop: tuple[str, ...], base: dict[str, Any]) -> list[dict[str, Any]]:
    """Atribución por oclusión de cada fila: prob(fila) − prob(fila con el grupo tapado)."""
    p0 = _predict(model, rows, drop)
    contrib: dict[str, np.ndarray] = {}
    for g, cols in GROUPS.items():
        alt = rows.copy()
        for c in cols:
            alt[c] = base[c]
        contrib[g] = p0 - _predict(model, alt, drop)
    def ranked(i: int) -> list[tuple[str, float]]:
        return sorted(((g, float(contrib[g][i])) for g in GROUPS), key=lambda t: -abs(t[1]))

    out = []
    for i, (_, r) in enumerate(rows.iterrows()):
        vals = {c: (None if pd.isna(r[c]) else (round(float(r[c]), 5) if c in algs.NUM else str(r[c]))) for c in algs.NUM + algs.CAT}
        out.append({"cve": r["cve"], "snapshot": str(r["snapshot"]), "label": int(r["label"]), "prob": round(float(p0[i]), 6),
                    "values": vals, "attributions": [{"group": g, "delta": round(v, 6)} for g, v in ranked(i)]})  # fmt: skip
    return out


def coefficients(model: Any) -> list[dict[str, Any]]:
    clf = model.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        return []
    names = model.named_steps["prep"].get_feature_names_out()
    coef = clf.coef_[0]
    rows: list[dict[str, Any]] = [{"feature": str(n).split("__", 1)[-1], "coef": round(float(c), 4)} for n, c in zip(names, coef, strict=True)]
    return sorted(rows, key=lambda r: -abs(float(r["coef"])))[:20]


def explain(bundle: dict[str, Any], df: pd.DataFrame, preds: pd.DataFrame, seed: int = 7, report: Any = None,
            repeats: int = 3, n_cases: int = 5, pdp_rows: int = 1500) -> dict[str, Any]:  # fmt: skip
    model, drop = bundle["pipeline"], tuple(bundle.get("drop", []))
    dev = df[df["split"] == "desarrollo"]
    test = df[df["split"] == "prueba"].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    # Muestra para la importancia: todos los positivos + negativos al azar, con el peso ajustado (el AUC no se sesga).
    pos, neg = test[test["label"] == 1], test[test["label"] == 0]
    take = min(len(neg), 8000)
    neg_s = neg.iloc[rng.choice(len(neg), take, replace=False)].copy()
    neg_s["weight"] = neg_s["weight"] * len(neg) / take
    imp_set = pd.concat([pos, neg_s], ignore_index=True)
    if report:
        report(5, "Calculando la importancia global")
    importance = permutation(model, imp_set, drop, repeats, seed, report)
    if report:
        report(60, "Dependencia parcial (1D y mapa 2D)")
    sample = test.iloc[rng.choice(len(test), min(pdp_rows, len(test)), replace=False)].reset_index(drop=True)
    used = [r["name"] for r in importance["rows"] if r["kind"] == "variable" and r["name"] in PDP_FEATURES]
    feats = [f for f in used if not (drop and any(f in algs.GROUPS[g]["columns"] for g in drop))][:4] or ["days_published"]
    one = pdp(model, sample, drop, feats)
    two = pdp2d(model, sample, drop, feats[0], feats[1]) if len(feats) > 1 else None
    if report:
        report(85, "Explicaciones individuales por oclusión")
    p = preds[preds["split"] == "prueba"].reset_index(drop=True)
    t = test.assign(score=p["score"].to_numpy())
    cases = {
        "aciertos": t[t["label"] == 1].nlargest(n_cases, "score"),
        "escapados": t[t["label"] == 1].nsmallest(n_cases, "score"),
        "falsas_alarmas": t[t["label"] == 0].nlargest(n_cases, "score"),
    }
    base = baseline_values(dev)
    local = {k: occlusion(model, v.drop(columns=["score"]), drop, base) for k, v in cases.items()}
    out = {"importance": importance, "pdp": one, "pdp2d": two, "local": local, "coefficients": coefficients(model),
           "baseline": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in base.items()}, "drop": list(drop),
           "equivalences": EQUIVALENCES, "how_to_read": HOW_TO_READ}  # fmt: skip
    out["interpretation"] = _notes(out)
    return out


def _val(x: float) -> str:
    """Decimales según la magnitud: días y conteos sin decimales; probabilidades con 3."""
    if float(x).is_integer() or abs(x) >= 10:
        return _num(x, digits=0)
    return _num(x, digits=1) if abs(x) >= 1 else _num(x, digits=3)


def _notes(r: dict[str, Any]) -> list[str]:
    groups = [x for x in r["importance"]["rows"] if x["kind"] == "grupo"]
    top = groups[:3]
    notes = ["Los grupos de variables en los que más se apoya el modelo (caída del ROC-AUC en prueba al desordenarlos): "
             + "; ".join(f"{g['name']} ({_num(g['mean'], digits=3)})" for g in top) + "."]  # fmt: skip
    dropped = {c for g in r["drop"] for c in algs.GROUPS[g]["columns"]}
    unused = [g["name"] for g in groups if abs(g["mean"]) < 0.002 and not set(GROUPS[g["name"]]) <= dropped]
    if unused:
        notes.append(f"Casi no usa: {', '.join(unused)} (desordenarlos no cambia el resultado).")
    if r["drop"]:
        notes.append(f"Modelo entrenado sin {', '.join(r['drop']).upper()} (ablación): esas variables no pueden influir.")
    for d in r["pdp"][:2]:
        pts = d["points"]
        if len(pts) >= 2:
            lo, hi = pts[0]["y"], pts[-1]["y"]
            trend = "sube" if hi > lo * 1.2 else "baja" if hi < lo / 1.2 else "casi no cambia"
            notes.append(f"Al pasar {d['feature']} de {_val(pts[0]['x'])} a {_val(pts[-1]['x'])}, la probabilidad media "
                         f"{trend} ({_num(100 * lo, digits=3)} % → {_num(100 * hi, digits=3)} %).")  # fmt: skip
    esc = r["local"].get("escapados", [])
    if esc:
        avg = {g: np.mean([next(a["delta"] for a in c["attributions"] if a["group"] == g) for c in esc]) for g in GROUPS}
        worst = min(avg, key=lambda g: avg[g])
        notes.append(f"En los KEV que se le escaparon, lo que más empujó en contra fue «{worst}»: son CVE que no se parecen a los "
                     "que el modelo aprendió a asociar con KEV.")  # fmt: skip
        hits = r["local"].get("aciertos", [])
        age = [c["values"].get("days_published") for c in esc if c["values"].get("days_published") is not None]
        age_hit = [c["values"].get("days_published") for c in hits if c["values"].get("days_published") is not None]
        if age and age_hit and np.median(age) >= 365 and np.median(age) > 2 * max(1.0, float(np.median(age_hit))):
            notes.append(f"Los KEV que se escaparon tenían una antigüedad mediana de {_num(float(np.median(age)) / 365, digits=1)} años al "
                         f"momento de la foto, frente a {_num(float(np.median(age_hit)) / 365, digits=1)} años de los que acertó: "
                         "CISA también agrega a KEV CVE viejos que vuelven a explotarse, y esos son los más difíciles de anticipar.")  # fmt: skip
    return notes
