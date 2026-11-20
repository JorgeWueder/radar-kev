"""Perfil de un dataset del laboratorio (Fase 1): visualización, validación de grupos y estadística descriptiva con
interpretación. Los negativos están muestreados con la misma tasa en todas las fotos, así que medianas y AUC por
variable no se sesgan; las proporciones de KEV se corrigen con el peso de cada fila."""

from typing import Any

import pandas as pd

from app.ml.dataset import EXCLUDED, FEATURES
from app.services.descriptive import _num
from app.services.evaluation import _quality_of, auc

MIN_POS_SPLIT = 20
SPLITS = ("desarrollo", "validacion", "prueba")
SPLIT_LABEL = {"desarrollo": "Desarrollo", "validacion": "Validación", "prueba": "Prueba"}
BINS: dict[str, list[float]] = {
    "epss": [0, 0.001, 0.01, 0.05, 0.1, 0.5, 1.0001],
    "cvss": [0, 4, 7, 9, 10.0001],
    "days_published": [0, 30, 180, 365, 1095, 100_000],
    "edb_exploits": [0, 1, 2, 1000],
    "cna_kev_prior": [0, 1, 10, 50, 100_000],
}
HOW_TO_READ = {
    "splits": "Partición temporal: cada foto mensual cae entera en una partición, de la más antigua (desarrollo) a la más reciente (prueba).",
    "numeric": ("Compara cada variable entre los CVE que entraron a KEV y los que no. «Separa» es el AUC de esa variable sola: "
                "0,5 no separa nada y 1 separa perfecto; por debajo de 0,5 la relación es inversa (separa como 1 − AUC). "
                "Es una pista para la Fase 2, no una conclusión."),
    "categorical": ("Proporción de CVE que entraron a KEV dentro de cada categoría (corregida por el muestreo). Las categorías "
                    "con menos de 5 positivos son orientativas."),
    "checks": "Controles del dataset antes de entrenar: si algo sale en aviso, conviene revisarlo o justificarlo en el informe.",
}  # fmt: skip


def _prev(pos: float, w: float) -> float | None:
    return round(100 * pos / w, 4) if w else None


def _check(key: str, label: str, ok: bool, detail: str, warn: bool = True) -> dict[str, Any]:
    return {"key": key, "label": label, "status": "ok" if ok else ("warn" if warn else "info"), "detail": detail}


def _hist(s: pd.Series, y: pd.Series, edges: list[float]) -> list[dict[str, Any]]:
    cut = pd.cut(s, bins=edges, right=False, include_lowest=True)
    out = []
    for interval, grp in y.groupby(cut, observed=False):
        lo, hi = interval.left, interval.right
        def fmt(v: float) -> str:
            return _num(v, digits=3).rstrip("0").rstrip(",") or "0"

        last = hi == edges[-1] and edges[-1] != 1.0001 and edges[-1] != 10.0001  # tope artificial: «≥ desde»
        label = f"≥ {fmt(lo)}" if last else f"{fmt(lo)} a {fmt(min(hi, 1.0 if hi == 1.0001 else 10.0 if hi == 10.0001 else hi))}"
        out.append({"label": label, "neg": int((grp == 0).sum()), "pos": int((grp == 1).sum())})
    return out


def profile(df: pd.DataFrame, neg_rate: float) -> dict[str, Any]:
    y = df["label"]
    w = df["weight"]
    n_pos = int(y.sum())
    universe = float(w.sum())
    out: dict[str, Any] = {"how_to_read": HOW_TO_READ, "overview": {
        "rows": int(len(df)), "positives": n_pos, "negatives_sampled": int(len(df) - n_pos), "neg_rate": neg_rate,
        "universe_estimate": int(round(universe)), "prevalence_pct": _prev(n_pos, universe),
        "snapshots": int(df["snapshot"].nunique()), "cves": int(df["cve"].nunique()),
    }}  # fmt: skip

    snaps = []
    for s, g in df.groupby("snapshot", sort=True):
        snaps.append({"snapshot": str(s), "split": g["split"].iloc[0], "rows": int(len(g)), "positives": int(g["label"].sum()),
                      "prevalence_pct": _prev(float(g["label"].sum()), float(g["weight"].sum())),
                      "epss_model": str(g["epss_model"].iloc[0])})  # fmt: skip
    out["snapshots"] = snaps
    splits = []
    for sp in SPLITS:
        g = df[df["split"] == sp]
        if g.empty:
            continue
        splits.append({"split": sp, "label": SPLIT_LABEL[sp] + f" ({100 * g['snapshot'].nunique() / df['snapshot'].nunique():.0f} %)", "rows": int(len(g)), "positives": int(g["label"].sum()),
                       "snapshots": int(g["snapshot"].nunique()), "from": str(g["snapshot"].min()), "to": str(g["snapshot"].max()),
                       "share_pct": round(100 * g["snapshot"].nunique() / df["snapshot"].nunique(), 1),
                       "prevalence_pct": _prev(float(g["label"].sum()), float(g["weight"].sum()))})  # fmt: skip
    out["splits"] = splits

    numeric = []
    for f in (f for f in FEATURES if f["type"] == "num"):
        col = df[f["name"]]
        pos, neg = col[y == 1].dropna(), col[y == 0].dropna()
        a = auc(col.fillna(col.median() if col.notna().any() else 0).tolist(), (y == 1).tolist()) if n_pos and n_pos < len(df) else None
        numeric.append({
            "name": f["name"], "description": f["description"], "missing_pct": round(100 * float(col.isna().mean()), 1),
            "median_pos": None if pos.empty else round(float(pos.median()), 4),
            "median_neg": None if neg.empty else round(float(neg.median()), 4),
            "p75_pos": None if pos.empty else round(float(pos.quantile(0.75)), 4),
            "p75_neg": None if neg.empty else round(float(neg.quantile(0.75)), 4),
            "auc": None if a is None else round(a, 3),
            "hist": _hist(col, y, BINS[f["name"]]) if f["name"] in BINS else [],
        })  # fmt: skip
    out["numeric"] = sorted(numeric, key=lambda r: -abs((r["auc"] or 0.5) - 0.5))

    categorical = []
    for f in (f for f in FEATURES if f["type"] == "cat"):
        g = df.groupby(f["name"]).agg(rows=("label", "size"), positives=("label", "sum"), weight=("weight", "sum"))
        g = g.sort_values(["positives", "rows"], ascending=False).head(12)
        cats = [{"value": str(k), "rows": int(r["rows"]), "positives": int(r["positives"]),
                 "prevalence_pct": _prev(float(r["positives"]), float(r["weight"])), "small": int(r["positives"]) < 5}
                for k, r in g.iterrows()]  # fmt: skip
        categorical.append({"name": f["name"], "description": f["description"], "cardinality": int(df[f["name"]].nunique()), "top": cats})
    out["categorical"] = categorical
    out["checks"] = _checks(df, splits)
    out["excluded"] = EXCLUDED
    out["interpretation"] = _notes(out)
    return out


def _checks(df: pd.DataFrame, splits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    low = [s["label"] for s in splits if s["positives"] < MIN_POS_SPLIT]
    checks.append(_check("positives", "Positivos por partición", not low,
                         f"{', '.join(low)} con menos de {MIN_POS_SPLIT} positivos: sus métricas tendrán intervalos anchos." if low
                         else f"Todas las particiones tienen al menos {MIN_POS_SPLIT} CVE que entraron a KEV."))  # fmt: skip
    order = [(s["from"], s["to"]) for s in splits]
    temporal = all(order[i][1] < order[i + 1][0] for i in range(len(order) - 1))
    checks.append(_check("temporal", "Orden temporal de la partición", temporal,
                         "Desarrollo es anterior a validación y esta a prueba: el modelo nunca ve el futuro." if temporal
                         else "Las particiones se solapan en el tiempo: revise la construcción."))  # fmt: skip
    dup = int(df.duplicated(["snapshot", "cve"]).sum())
    checks.append(_check("duplicates", "Duplicados", dup == 0, "Ningún CVE se repite dentro de una misma foto." if dup == 0
                         else f"{dup} filas repetidas (snapshot, CVE)."))  # fmt: skip
    leak = int((pd.to_datetime(df["kev_date"]) <= pd.to_datetime(df["snapshot"])).sum())
    checks.append(_check("label_leak", "Etiqueta sin fuga", leak == 0,
                         "Ningún CVE estaba ya en KEV en la fecha de su foto (se excluyen antes de etiquetar)." if leak == 0
                         else f"{leak} filas tienen fecha de KEV anterior o igual a la foto."))  # fmt: skip
    cna_share = float((df["cvss_src"] == "cna").mean())
    checks.append(_check("cvss_src", "CVSS solo de la CNA", True,
                         f"El {_num(100 * cna_share, digits=0)} % de las filas tiene el CVSS que puso la propia CNA; el resto queda sin "
                         "CVSS (el del NVD y el de terceros se agregan después y se descartan para no filtrar la etiqueta).", warn=False))  # fmt: skip
    leaky = []
    y = df["label"] == 1
    for f in FEATURES:
        col = df[f["name"]]
        miss = col.isna() | (col == "desconocido") if f["type"] == "cat" else col.isna()
        mp, mn = float(miss[y].mean()) if y.any() else 0.0, float(miss[~y].mean())
        if abs(mp - mn) > 0.25:
            leaky.append(f"{f['name']} (falta en el {_num(100 * mp, digits=0)} % de los positivos y el {_num(100 * mn, digits=0)} % del resto)")
    checks.append(_check("missing_leak", "La ausencia del dato no delata la etiqueta", not leaky,
                         "Ninguna variable falta mucho más (o mucho menos) en los CVE que entraron a KEV." if not leaky
                         else "Revise: " + "; ".join(leaky) + ". Si un dato falta según la etiqueta, el modelo aprende la ausencia."))  # fmt: skip
    models = {s: set(df.loc[df["split"] == s, "epss_model"]) for s in SPLITS}
    unseen = models["prueba"] - models["desarrollo"]
    versions = sorted(set(df["epss_model"]))
    if unseen:
        checks.append(_check("epss_model", "Versión del modelo EPSS", False,
                             f"Prueba usa {', '.join(sorted(unseen))}, que no aparece en desarrollo: EPSS cambió de versión y "
                             "puede cambiar su escala; el modelo no la vio al entrenar."))  # fmt: skip
    elif len(versions) > 1:
        first_new = df.loc[df["epss_model"] == versions[-1], "snapshot"].min()
        checks.append(_check("epss_model", "Versión del modelo EPSS", False,
                             f"EPSS cambia de {versions[0]} a {versions[-1]} desde la foto {first_new}; desarrollo ya incluye "
                             "ambas versiones.", warn=False))  # fmt: skip
    else:
        checks.append(_check("epss_model", "Versión del modelo EPSS", True, f"Una sola versión de EPSS ({versions[0]})."))
    miss_pub = float(df["days_published"].isna().mean())
    checks.append(_check("published", "Fecha de publicación", miss_pub < 0.05,
                         f"El {_num(100 * miss_pub, digits=1)} % no tiene fecha de publicación en el NVD a la fecha de la foto.", warn=True))  # fmt: skip
    return checks


def _notes(p: dict[str, Any]) -> list[str]:
    o = p["overview"]
    def n(x: int) -> str:
        return f"{x:,}".replace(",", " ")

    notes = [
        f"{n(o['rows'])} filas de {o['snapshots']} fotos mensuales ({n(o['cves'])} CVE distintos); {o['positives']} entraron a KEV en "
        f"la ventana. Corrigiendo el muestreo, equivale a ~{n(o['universe_estimate'])} filas con una proporción de KEV del "
        f"{_num(o['prevalence_pct'], digits=3)} %: un problema muy desbalanceado, por eso la métrica principal será PR-AUC.",
    ]  # fmt: skip
    strong = [r for r in p["numeric"] if r["auc"] is not None][:3]
    if strong:
        def reading(r: dict[str, Any]) -> str:
            a = r["auc"]
            if a < 0.5:  # relación inversa: valores BAJOS se asocian a entrar a KEV
                return (f"{r['name']} (AUC {_num(a, digits=2)}: relación inversa, los valores bajos entran más a KEV; "
                        f"separa como {_num(1 - a, digits=2)}, {_quality_of(1 - a)})")  # fmt: skip
            return f"{r['name']} (AUC {_num(a, digits=2)}, {_quality_of(a)})"

        notes.append("Variables que más separan por sí solas: " + "; ".join(reading(r) for r in strong) + ".")
    notes.append(f"Se descartaron {len(EXCLUDED)} fuentes de variables por fuga de información (detalle en Metadata): SSVC de CISA, "
                 "CVSS y CWE puestos por el NVD o terceros, número de referencias y Metasploit.")  # fmt: skip
    warns = [c["label"] for c in p["checks"] if c["status"] == "warn"]
    notes.append("Validación sin avisos." if not warns else f"Avisos de validación: {'; '.join(warns)}.")
    return notes


def sample(df: pd.DataFrame, limit: int, label: int | None) -> list[dict[str, Any]]:
    import json

    g = (df if label is None else df[df["label"] == label]).head(limit)
    g = g.assign(**{c: g[c].astype("string") for c in ("snapshot", "kev_date", "published")})  # fechas como texto ISO
    out: list[dict[str, Any]] = json.loads(g.to_json(orient="records"))
    return out
