"""Prueba prospectiva de EPSS sobre TODO el universo de CVE: ¿el EPSS publicado hace N días anticipaba qué CVE
entrarían después a KEV?

Por qué prospectiva: EPSS se calcula en parte con evidencia de explotación, así que comparar el EPSS de hoy con KEV
mezclaría causa y efecto. Aquí se toma el CSV completo de EPSS de la fecha `as_of`, se EXCLUYEN los CVE que ya estaban
en KEV en esa fecha y se marca como positivo el CVE que entró a KEV en (as_of, until]. Así EPSS no puede "ver" la
respuesta. Sin SciPy ni sklearn; todo vectorizado con numpy/pandas (unos 300 000 CVE).
"""

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.intel import KevEntry, UniverseEvaluation
from app.services.descriptive import _num
from app.services.evaluation import _quality_of, auc_ci

HORIZONS = (30, 90, 180)
TOP_SHARES = (0.001, 0.005, 0.01, 0.05, 0.10)  # "parchear el X % de CVE con mayor EPSS"
THRESHOLDS = (0.01, 0.10, 0.50)  # reglas fijas de EPSS
MAX_POINTS = 250  # puntos de curva que se guardan (las curvas completas tendrían cientos de miles)
MIN_POSITIVES = 20

HOW_TO_READ = {
    "effort": (
        "Cada fila ordena todos los CVE por EPSS (de mayor a menor) y toma el primer X %. Cobertura: parte de los CVE que "
        "luego entraron a KEV que quedaban dentro. Veces mejor que el azar: cobertura dividida entre el esfuerzo (al azar, "
        "parchear el 1 % cubre el 1 %)."
    ),
    "rules": "Cada regla marca los CVE con EPSS igual o mayor al umbral en la fecha de la prueba.",
    "curves": (
        "La curva ROC usa todos los CVE con EPSS en la fecha de la prueba: al bajar el umbral, qué parte de las entradas a "
        "KEV se anticipa (eje vertical) frente a qué parte del resto se arrastra (eje horizontal). La diagonal es el azar."
    ),
}


class UniverseError(RuntimeError):
    """No se pudo obtener el EPSS histórico o no hay datos suficientes."""


def _int(n: int) -> str:
    return f"{n:,}".replace(",", " ")  # miles con espacio, como en el resto de la UI


def _sample(must: np.ndarray, n: int) -> np.ndarray:
    """Índices de puntos de curva: todos los umbrales donde se captura un positivo + una grilla logarítmica."""
    grid = np.unique(np.geomspace(1, max(n, 1), num=MAX_POINTS).astype(int) - 1)
    return np.unique(np.concatenate([must, grid]))


def prospective(epss: pd.DataFrame, kev: pd.DataFrame, as_of: date, until: date) -> dict[str, Any]:
    """`epss`: cve, epss (0-1) de la fecha `as_of`. `kev`: cve, date_added. Devuelve métricas y su lectura."""
    known = set(kev.loc[kev["date_added"] <= as_of, "cve"])
    future = kev[(kev["date_added"] > as_of) & (kev["date_added"] <= until)]
    future_set = set(future["cve"])
    df = epss[~epss["cve"].isin(known)]
    y = df["cve"].isin(future_set).to_numpy()
    s = df["epss"].to_numpy(dtype=float)
    n, n_pos = int(len(y)), int(y.sum())
    n_neg = n - n_pos
    not_scored = len(future_set - set(epss["cve"]))
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(), "until": until.isoformat(), "horizon_days": (until - as_of).days,
        "n": n, "excluded_known": len(known & set(epss["cve"])), "positives": n_pos, "not_scored": not_scored,
        "prevalence_pct": round(100 * n_pos / n, 4) if n else None, "how_to_read": HOW_TO_READ,
        "share_below_1pct": round(100 * float((s < 0.01).mean()), 1) if n else None,
    }  # fmt: skip
    if not n_pos or not n_neg:
        out |= {"auc": None, "auc_ci": None, "ap": None, "roc": [], "pr": [], "effort": [], "rules": [],
                "interpretation": ["No hubo CVE nuevos en KEV con EPSS en la ventana: no hay nada que anticipar."]}  # fmt: skip
        return out

    ranks = pd.Series(s).rank(method="average").to_numpy()
    auc = float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))
    lo, hi = auc_ci(auc, n_pos, n_neg)

    order = np.argsort(-s, kind="stable")
    ss, yy = s[order], y[order]
    last = np.r_[np.nonzero(np.diff(ss))[0], n - 1]  # último índice de cada grupo de empates (un umbral)
    tp = np.cumsum(yy)[last]
    marked = last + 1
    fp = marked - tp
    tpr, fpr, prec = tp / n_pos, fp / n_neg, tp / marked
    ap = float(np.sum(np.diff(np.r_[0.0, tpr]) * prec))
    must = np.nonzero(np.diff(np.r_[0, tp]))[0]  # umbrales donde se captura un positivo
    pick = _sample(must, len(last))
    out["roc"] = [{"fpr": round(float(fpr[i]), 6), "tpr": round(float(tpr[i]), 4)} for i in pick]
    out["roc"].insert(0, {"fpr": 0.0, "tpr": 0.0})
    out["pr"] = [{"recall": round(float(tpr[i]), 4), "precision": round(float(prec[i]), 6)} for i in pick]

    cum = np.cumsum(yy)
    out["effort"] = []
    for share in TOP_SHARES:
        k = max(1, math.ceil(share * n))
        hit = int(cum[k - 1])
        cov = hit / n_pos
        out["effort"].append({"share_pct": share * 100, "cves": k, "captured": hit, "coverage_pct": round(100 * cov, 1),
                              "precision_pct": round(100 * hit / k, 3), "lift": round(cov / share, 1)})  # fmt: skip
    out["rules"] = []
    for t in THRESHOLDS:
        m = s >= t
        hit = int((m & y).sum())
        k = int(m.sum())
        out["rules"].append({"threshold_pct": t * 100, "marked": k, "effort_pct": round(100 * k / n, 2), "captured": hit,
                             "coverage_pct": round(100 * hit / n_pos, 1),
                             "precision_pct": round(100 * hit / k, 3) if k else None})  # fmt: skip
    pos = s[y]
    out |= {"auc": round(auc, 3), "auc_ci": [round(lo, 3), round(hi, 3)], "ap": round(ap, 4),
            "pos_median_epss_pct": round(100 * float(np.median(pos)), 2),
            "pos_share_below_1pct": round(100 * float((pos < 0.01).mean()), 1)}  # fmt: skip
    out["interpretation"] = _notes(out)
    return out


def _notes(r: dict[str, Any]) -> list[str]:
    e1 = next(x for x in r["effort"] if x["share_pct"] == 1)
    r10 = next(x for x in r["rules"] if x["threshold_pct"] == 10)
    notes = [
        f"Del EPSS publicado el {date.fromisoformat(r['as_of']).strftime('%d/%m/%Y')} ({_int(r['n'])} CVE que aún no estaban en KEV), "
        f"{r['positives']} entraron a KEV en los {r['horizon_days']} días siguientes: el {_num(r['prevalence_pct'], digits=3)} % del universo.",
        f"EPSS anticipó esas entradas con un AUC de {_num(r['auc'], digits=2)} ({_quality_of(r['auc'])}; IC 95 % de "
        f"{_num(r['auc_ci'][0], digits=2)} a {_num(r['auc_ci'][1], digits=2)}).",
        f"Parchear el 1 % de CVE con mayor EPSS ({_int(e1['cves'])} CVE) habría cubierto el {_num(e1['coverage_pct'], digits=0)} % de lo que "
        f"luego entró a KEV: {_num(e1['lift'], digits=0)} veces más que al azar.",
        f"La regla EPSS ≥ 10 % marcaba el {_num(r10['effort_pct'])} % de los CVE y cubría el {_num(r10['coverage_pct'], digits=0)} %.",
        f"Antes de entrar a KEV, la mitad de esos CVE tenía un EPSS de {_num(r['pos_median_epss_pct'], digits=2)} % o menos, y el "
        f"{_num(r['pos_share_below_1pct'], digits=0)} % estaba por debajo de 1 %. EPSS suele subir cuando aparece la evidencia de "
        "explotación, no antes: ordena muy bien la cima, pero muchas entradas a KEV llegan desde abajo.",
        f"El {_num(r['share_below_1pct'], digits=0)} % de los CVE tenía EPSS menor a 1 %: es el volumen que se puede postergar "
        "con poco riesgo.",
        "Prueba prospectiva: se excluyen los CVE que ya estaban en KEV en la fecha del EPSS, así que EPSS no podía «ver» la "
        "respuesta. KEV no lista todo lo explotado; un CVE fuera de KEV no es necesariamente seguro.",
    ]  # fmt: skip
    if r["not_scored"]:
        notes.append(f"{r['not_scored']} CVE entraron a KEV en la ventana pero no tenían EPSS en esa fecha (se publicaron después); "
                     "quedan fuera de la prueba.")  # fmt: skip
    if r["positives"] < MIN_POSITIVES:
        notes.append(f"Solo {r['positives']} entradas nuevas en KEV: amplíe el horizonte para un intervalo más estrecho.")
    return notes


def latest(db: Session) -> dict[str, Any] | None:
    row = db.execute(select(UniverseEvaluation).order_by(UniverseEvaluation.computed_at.desc()).limit(1)).scalars().first()
    if row is None:
        return None
    # "Cómo leerla" sale del código actual (no del guardado), para que una mejora del texto llegue a resultados viejos.
    return dict(row.result) | {"computed_at": row.computed_at.isoformat(), "model_version": row.model_version, "how_to_read": HOW_TO_READ}


def compute(db: Session, horizon_days: int = 90, today: date | None = None) -> dict[str, Any]:
    """Descarga el EPSS completo de hace `horizon_days` días (o el día publicado más cercano antes), cruza con el
    catálogo KEV de la base y guarda el resultado. El catálogo KEV debe estar al día (lo actualiza el flujo diario)."""
    from app.services import feeds
    from app.services.intel import read_epss_csv

    if horizon_days not in HORIZONS:
        raise UniverseError(f"Horizonte no admitido: use {', '.join(map(str, HORIZONS))} días")
    kev_rows = db.execute(select(KevEntry.cve_id, KevEntry.date_added)).all()
    if not kev_rows:
        raise UniverseError("El catálogo KEV está vacío: ejecute primero el flujo diario")
    kev = pd.DataFrame(kev_rows, columns=["cve", "date_added"])
    until = min(today or datetime.now(UTC).date(), max(kev["date_added"]))  # no observar más allá de lo que hay en KEV
    target = until - timedelta(days=horizon_days)
    for back in range(4):  # FIRST a veces no publica un día: se toma el anterior más cercano
        day = target - timedelta(days=back)
        raw = feeds.fetch_epss_csv_for(day.isoformat())
        if raw is not None:
            break
    else:
        raise UniverseError(f"FIRST no tiene el CSV de EPSS de {target.isoformat()} ni de los 3 días anteriores")
    try:
        epss, sdate, model = read_epss_csv(raw)
    except ValueError as e:  # IntelError: el CSV no tiene el formato esperado
        raise UniverseError(f"CSV de EPSS de {day.isoformat()} inválido: {e}") from None
    result = prospective(epss, kev, sdate, until)
    db.add(UniverseEvaluation(as_of=sdate, until=until, horizon_days=(until - sdate).days, model_version=model, result=result))
    db.commit()
    out = latest(db)
    assert out is not None
    return out
