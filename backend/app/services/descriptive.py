"""Estadística descriptiva del inventario abierto (EPSS, CVSS y score), con su lectura en español.

Solo describe: no decide nada ni toca el cruce. Las funciones `profile`/`summarize`/`distribution` son puras (DataFrame en,
dict fuera) para poder probarlas sin base de datos; `load_frame` es la única que consulta.
"""

from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

CRITICALITY = {4: "Crítica", 3: "Alta", 2: "Media", 1: "Baja"}
ENVIRONMENT = {"prod": "Producción", "staging": "Preproducción", "dev": "Desarrollo"}
SMALL_GROUP = 5  # por debajo, el grupo es orientativo

# (clave, etiqueta, unidad, tramos). EPSS va en % y con tramos desiguales porque casi todo se concentra cerca de 0.
VARIABLES: list[tuple[str, str, str, list[float]]] = [
    ("risk_score", "Score de riesgo", "", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ("epss", "EPSS", "%", [0, 1, 5, 10, 25, 50, 75, 100]),
    ("cvss", "CVSS", "", [0, 4, 7, 9, 10]),
]
CVSS_BAND = {0: "Baja (< 4)", 1: "Media (4 a 6,9)", 2: "Alta (7 a 8,9)", 3: "Crítica (≥ 9)"}

HOW_TO_READ = {
    "summary": (
        "La mediana es el valor del hallazgo del medio: la mitad está por debajo. Si la media es mucho mayor, unos pocos "
        "valores altos la inflan y la mediana describe mejor el caso típico. P25 y P75 marcan el 50 % central; P90 deja "
        "fuera solo al 10 % más alto."
    ),
    "distribution": "Cada barra es la cantidad de hallazgos abiertos cuyo valor cae en ese tramo (incluye el inicio, excluye el final).",
    "groups": (
        "Compara grupos por su mediana, que no se deja arrastrar por valores extremos. Un grupo con menos de "
        f"{SMALL_GROUP} hallazgos es orientativo: un solo caso cambia mucho la cifra."
    ),
}

_SQL = text(
    "SELECT v.cve_id, v.cvss_score AS cvss, v.risk_score, a.criticality, a.environment, "
    " (k.cve_id IS NOT NULL) AS in_kev, e.epss, a.id::text AS asset_id, a.auto_created, e.score_date AS epss_date, e.percentile "
    "FROM vulnerabilities v JOIN assets a ON a.id = v.asset_id "
    "LEFT JOIN kev_entries k ON k.cve_id = v.cve_id "
    "LEFT JOIN (SELECT DISTINCT ON (cve_id) cve_id, epss, percentile, score_date FROM epss_scores ORDER BY cve_id, score_date DESC) e "
    " ON e.cve_id = v.cve_id "
    "WHERE v.status IN ('open','in_progress')"
)
COLUMNS = ["cve_id", "cvss", "risk_score", "criticality", "environment", "in_kev", "epss", "asset_id", "auto_created", "epss_date", "percentile"]


def load_frame(db: Session) -> pd.DataFrame:
    rows = db.execute(_SQL).all()
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["auto_created"] = df["auto_created"].astype(bool)
    for col in ("cvss", "risk_score", "epss", "percentile"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    df["epss"] = df["epss"] * 100.0  # se describe en %
    df["in_kev"] = df["in_kev"].astype(bool)
    return df


def _num(x: float | None, unit: str = "", digits: int = 1) -> str:
    if x is None:
        return "—"
    s = f"{x:.{digits}f}".replace(".", ",")
    if s.endswith(",0"):
        s = s[:-2]
    return f"{s} %" if unit == "%" else s


def _med(s: pd.Series) -> float | None:
    v = s.dropna()
    return None if v.empty else _f(v.median())


def _f(x: Any) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x), 2)


def summarize(s: pd.Series) -> dict[str, Any]:
    v = s.dropna()
    out: dict[str, Any] = {"n": int(len(v)), "missing": int(s.isna().sum())}
    if v.empty:
        return out | dict.fromkeys(("mean", "std", "min", "p25", "median", "p75", "p90", "max"))
    q = v.quantile([0.25, 0.5, 0.75, 0.9])
    return out | {
        "mean": _f(v.mean()), "std": _f(v.std(ddof=1)) if len(v) > 1 else None, "min": _f(v.min()),
        "p25": _f(q[0.25]), "median": _f(q[0.5]), "p75": _f(q[0.75]), "p90": _f(q[0.9]), "max": _f(v.max()),
    }  # fmt: skip


def distribution(s: pd.Series, edges: list[float], unit: str = "") -> list[dict[str, Any]]:
    v = s.dropna()
    # El último tramo incluye su borde superior (100 en score/EPSS, 10 en CVSS).
    cut = pd.cut(v.clip(upper=edges[-1] - 1e-9), bins=edges, right=False)
    counts = cut.value_counts(sort=False)
    out = []
    for i, (_, n) in enumerate(counts.items()):
        lo, hi = edges[i], edges[i + 1]
        label = f"{_num(lo, digits=0)} a {_num(hi, digits=0)}{' %' if unit == '%' else ''}"
        out.append({"lo": lo, "hi": hi, "label": label, "count": int(n)})
    return out


def _variable_notes(key: str, label: str, unit: str, s: pd.Series, st: dict[str, Any]) -> list[str]:
    total = st["n"] + st["missing"]
    notes: list[str] = []
    if st["n"] == 0:
        return [f"Ningún hallazgo abierto tiene {label}."]
    m, md = st["mean"], st["median"]
    label = label if label.isupper() else label[0].lower() + label[1:]  # "score de riesgo" en mitad de frase; EPSS/CVSS igual
    notes.append(f"La mitad de los hallazgos tiene {label} de {_num(md, unit)} o menos; el 90 % no pasa de {_num(st['p90'], unit)}.")
    spread = max(abs(md), 1.0 if unit != "%" else 0.5)
    if m - md > 0.25 * spread:
        notes.append(f"La media ({_num(m, unit)}) supera a la mediana: unos pocos valores altos inflan el promedio; "
                     "use la mediana para el caso típico.")  # fmt: skip
    elif md - m > 0.25 * spread:
        notes.append(f"La media ({_num(m, unit)}) queda por debajo de la mediana: unos pocos valores bajos tiran del promedio.")
    if st["n"] >= 4:
        notes.append(f"El 50 % central está entre {_num(st['p25'], unit)} y {_num(st['p75'], unit)}.")
    v = s.dropna()
    if key == "epss":
        low = (v < 1).mean() * 100
        high = int((v >= 10).sum())
        lead = (f"El {_num(low, digits=0)} % tiene EPSS menor a 1 % (baja probabilidad de explotación en los próximos 30 días)"
                if low else "Ningún hallazgo tiene EPSS menor a 1 %")  # fmt: skip
        notes.append(f"{lead}; {high} {'supera' if high == 1 else 'superan'} el 10 %.")
    elif key == "cvss":
        crit = (v >= 9).mean() * 100
        notes.append(f"El {_num(crit, digits=0)} % tiene CVSS crítico (≥ 9). El CVSS mide gravedad teórica, no explotación real: "
                     "por eso el score pesa también KEV y EPSS.")  # fmt: skip
    elif key == "risk_score":
        top = int((v >= 70).sum())
        notes.append(f"{top} de {st['n']} hallazgos tienen score de 70 o más.")
    if st["missing"]:
        notes.append(f"{st['missing']} de {total} hallazgos no tienen {label}: quedan fuera de estas cifras "
                     "(en el score cuentan 0; no se inventa el dato).")  # fmt: skip
    return notes


def _group_table(df: pd.DataFrame, col: str, names: dict[Any, str], order: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for g in order:
        sub = df[df[col] == g]
        if sub.empty:
            continue
        rows.append({
            "group": str(g), "label": names.get(g, str(g)), "n": int(len(sub)), "kev": int(sub["in_kev"].sum()),
            "kev_pct": _f(sub["in_kev"].mean() * 100), "median_score": _med(sub["risk_score"]),
            "median_epss": _med(sub["epss"]), "median_cvss": _med(sub["cvss"]), "small": len(sub) < SMALL_GROUP,
        })  # fmt: skip
    return rows


def _group_notes(rows: list[dict[str, Any]], dim: str, total_kev: int) -> list[str]:
    notes: list[str] = []
    scored = [r for r in rows if r["median_score"] is not None]
    if len(scored) >= 2:
        shown = {r["label"]: round(r["median_score"], 1) for r in scored}  # se compara lo que se ve en pantalla
        top, bottom = max(shown.values()), min(shown.values())
        if top != bottom:
            tops = [k for k, v in shown.items() if v == top]
            lows = [k for k, v in shown.items() if v == bottom]
            notes.append(f"Por {dim}, la mediana de score más alta es la de {' y '.join(tops)} ({_num(top)}) "
                         f"y la más baja la de {' y '.join(lows)} ({_num(bottom)}).")  # fmt: skip
    if total_kev:
        top = max(rows, key=lambda r: r["kev"])
        if top["kev"]:
            notes.append(f"{top['label']} concentra {top['kev']} de los {total_kev} hallazgos en KEV "
                         f"({_num(100 * top['kev'] / total_kev, digits=0)} %).")  # fmt: skip
    small = [r["label"] for r in rows if r["n"] < SMALL_GROUP]
    if small:
        notes.append(f"{', '.join(small)}: menos de {SMALL_GROUP} hallazgos, cifras orientativas.")
    return notes


EPSS_STALE_DAYS = 3  # FIRST publica a diario; con más de 3 días sin actualizar, el cruce no está corriendo bien
DOMINANT_SHARE = 0.8  # un grupo con el 80 % o más deja a los demás con muy pocos casos para comparar


def _sentence(s: str) -> str:
    return s[:1].upper() + s[1:] + "."


def _check(key: str, label: str, status: str, detail: str, count: int | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "count": count, "detail": detail}


def quality(df: pd.DataFrame, today: date) -> dict[str, Any]:
    """Validación de los datos y de los grupos ANTES de leer la estadística: qué falta, qué es supuesto y qué grupo es
    demasiado pequeño o dominante para compararlo. Estados: `ok`, `warn` (sesga la lectura) e `info` (contexto)."""
    n = int(len(df))
    if n == 0:
        return {"status": "ok", "checks": [], "interpretation": ["Sin hallazgos abiertos: no hay datos que validar."]}
    checks: list[dict[str, Any]] = []

    if "auto_created" in df:
        auto = df[df["auto_created"]]
        k = int(auto["asset_id"].nunique()) if len(auto) else 0
        checks.append(_check(
            "assumed_criticality", "Criticidad supuesta", "warn" if k else "ok",
            f"{len(auto)} hallazgos están en {k} {'activo creado' if k == 1 else 'activos creados'} por la importación con criticidad "
            "supuesta (Media). Hasta completarlos, la comparación por criticidad puede estar sesgada." if k
            else "Todos los activos con hallazgos abiertos tienen su criticidad revisada.", len(auto) or None,
        ))  # fmt: skip

    for key, label in (("epss", "EPSS"), ("cvss", "CVSS"), ("risk_score", "score")):
        miss = int(df[key].isna().sum())
        checks.append(_check(
            f"missing_{key}", f"Sin {label}", "warn" if miss else "ok",
            f"{miss} de {n} hallazgos no tienen {label} ({_num(100 * miss / n, digits=0)} %); quedan fuera de sus cifras." if miss
            else f"Todos los hallazgos tienen {label}.", miss or None,
        ))  # fmt: skip

    if "epss_date" in df and df["epss_date"].notna().any():
        latest = pd.to_datetime(df["epss_date"]).max().date()
        age = (today - latest).days
        checks.append(_check(
            "epss_age", "Antigüedad de EPSS", "warn" if age > EPSS_STALE_DAYS else "ok",
            f"El EPSS más reciente es de hace {age} días ({latest.strftime('%d/%m/%Y')}); revise las ejecuciones del cruce."
            if age > EPSS_STALE_DAYS else f"EPSS al día (última fecha {latest.strftime('%d/%m/%Y')}).", age,
        ))  # fmt: skip

    groupings: tuple[tuple[str, dict[Any, str], str], ...] = (
        ("criticality", CRITICALITY, "criticidad"), ("environment", ENVIRONMENT, "entorno"))
    for col, names, dim in groupings:
        counts = df[col].value_counts()
        small = [lbl for g, lbl in names.items() if g in counts.index and counts[g] < SMALL_GROUP]
        empty = [lbl for g, lbl in names.items() if g not in counts.index]
        top_g: Any = counts.idxmax()
        top_c = int(counts.max())
        parts = []
        if small:
            parts.append(f"{', '.join(small)} con menos de {SMALL_GROUP} hallazgos (orientativo)")
        if top_c / n >= DOMINANT_SHARE and len(counts) > 1:
            parts.append(f"{names.get(top_g, str(top_g))} reúne el {_num(100 * top_c / n, digits=0)} % de los hallazgos")
        if empty:
            parts.append(f"sin hallazgos en {', '.join(empty)}")
        checks.append(_check(
            f"groups_{col}", f"Grupos por {dim}", "warn" if small or top_c / n >= DOMINANT_SHARE else ("info" if empty else "ok"),
            _sentence("; ".join(parts)) if parts else f"Todos los grupos por {dim} tienen al menos {SMALL_GROUP} hallazgos.",
            len(small) or None,
        ))  # fmt: skip

    kev_n = int(df["in_kev"].sum())
    rest_n = n - kev_n
    ok = min(kev_n, rest_n) >= SMALL_GROUP
    checks.append(_check(
        "kev_vs_rest", "KEV frente al resto", "ok" if ok else "warn",
        f"{kev_n} en KEV y {rest_n} fuera: hay casos suficientes en ambos lados." if ok
        else f"{kev_n} en KEV y {rest_n} fuera: con menos de {SMALL_GROUP} en un lado, la comparación es orientativa.",
    ))  # fmt: skip

    warns = [c for c in checks if c["status"] == "warn"]
    text = (["Datos aptos para comparar: ninguna validación encontró problemas."] if not warns else
            [f"{len(warns)} {'aviso' if len(warns) == 1 else 'avisos'} antes de leer las cifras: "
             + "; ".join(c["label"][:1].lower() + c["label"][1:] for c in warns) + "."])  # fmt: skip
    return {"status": "warn" if warns else "ok", "checks": checks, "interpretation": text}


def profile(df: pd.DataFrame, today: date | None = None) -> dict[str, Any]:
    n = int(len(df))
    out: dict[str, Any] = {"n": n, "kev": int(df["in_kev"].sum()) if n else 0, "how_to_read": HOW_TO_READ,
                           "quality": quality(df, today or datetime.now(UTC).date())}  # fmt: skip
    if n == 0:
        out |= {"variables": [], "groups": [], "kev_vs_rest": None,
                "interpretation": ["No hay hallazgos abiertos: no hay nada que describir."]}  # fmt: skip
        return out
    variables = []
    for key, label, unit, edges in VARIABLES:
        st = summarize(df[key])
        dist = distribution(df[key], edges, unit)
        if key == "cvss":
            for i, b in enumerate(dist):
                b["label"] = CVSS_BAND[i]
        variables.append({"key": key, "label": label, "unit": unit, "summary": st, "distribution": dist,
                          "interpretation": _variable_notes(key, label, unit, df[key], st)})  # fmt: skip
    out["variables"] = variables

    crit = _group_table(df, "criticality", CRITICALITY, [4, 3, 2, 1])
    env = _group_table(df, "environment", ENVIRONMENT, ["prod", "staging", "dev"])
    out["groups"] = [
        {"key": "criticality", "label": "Criticidad del activo", "rows": crit, "interpretation": _group_notes(crit, "criticidad", out["kev"])},
        {"key": "environment", "label": "Entorno", "rows": env, "interpretation": _group_notes(env, "entorno", out["kev"])},
    ]  # fmt: skip

    kev, rest = df[df["in_kev"]], df[~df["in_kev"]]
    kv: dict[str, Any] = {"kev_n": int(len(kev)), "rest_n": int(len(rest)), "kev_median_epss": _med(kev["epss"]),
          "rest_median_epss": _med(rest["epss"]), "kev_median_cvss": _med(kev["cvss"]),
          "rest_median_cvss": _med(rest["cvss"])}  # fmt: skip
    notes = []
    if kv["kev_n"] and kv["rest_n"] and kv["kev_median_epss"] is not None and kv["rest_median_epss"] is not None:
        same = kv["kev_median_epss"] > kv["rest_median_epss"]
        notes.append(f"Los hallazgos en KEV tienen una mediana de EPSS de {_num(kv['kev_median_epss'], '%')} frente a "
                     f"{_num(kv['rest_median_epss'], '%')} del resto: "
                     + ("EPSS y KEV apuntan en la misma dirección." if same
                        else "aquí EPSS no anticipa lo que KEV ya confirma; KEV manda en la prioridad."))  # fmt: skip
        if kv["kev_median_cvss"] is not None and kv["rest_median_cvss"] is not None:
            diff = kv["kev_median_cvss"] - kv["rest_median_cvss"]
            if abs(diff) < 1:
                notes.append(f"En CVSS casi no se distinguen ({_num(kv['kev_median_cvss'])} frente a {_num(kv['rest_median_cvss'])}): "
                             "ordenar solo por CVSS no separa lo explotado de lo que no.")  # fmt: skip
    elif not kv["kev_n"]:
        notes.append("Ningún hallazgo abierto está en KEV.")
    kv["interpretation"] = notes
    out["kev_vs_rest"] = kv
    out["interpretation"] = [
        f"{n} hallazgos abiertos; {out['kev']} ({_num(100 * out['kev'] / n, digits=0)} %) tienen explotación activa confirmada (KEV)."
    ]
    return out


def descriptive(db: Session) -> dict[str, Any]:
    return profile(load_frame(db))
