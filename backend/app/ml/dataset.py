"""Construcción del dataset del laboratorio: ¿qué CVE entrarán a KEV en los próximos N días?

Una fila = un CVE en una foto mensual S que AÚN no estaba en KEV. Etiqueta = entró a KEV en (S, S+N]. Todas las
variables se calculan con datos disponibles en S (EPSS de ese día, SSVC y exploits con fecha anterior, KEV previo de
la misma CNA). Los negativos se muestrean (con semilla) y llevan su peso = 1/tasa para corregir las métricas.
La partición es temporal: el 70 % de fotos más antiguas para desarrollo, el 15 % siguiente para validación y el 15 %
más reciente para prueba (una partición al azar usaría el futuro para predecir el pasado)."""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml import nvd, sources
from app.services.intel import read_epss_csv

Progress = Callable[[int, str], None]

FEATURES: list[dict[str, str]] = [
    {"name": "epss", "type": "num", "source": "EPSS", "description": "Probabilidad EPSS en la fecha de la foto (0 a 1)."},
    {"name": "percentile", "type": "num", "source": "EPSS", "description": "Percentil EPSS en la fecha de la foto (no depende de la escala de cada versión)."},
    {"name": "epss_delta", "type": "num", "source": "EPSS", "description": "Cambio de EPSS frente a la foto anterior (~30 días)."},
    {"name": "epss_model", "type": "cat", "source": "EPSS", "description": "Versión del modelo EPSS que generó el puntaje (cambia con el tiempo)."},
    {"name": "cvss", "type": "num", "source": "NVD (CNA)", "description": "Puntaje base CVSS puesto por la propia CNA; vacío si solo lo puso el NVD u otro después."},
    {"name": "av", "type": "cat", "source": "NVD (CNA)", "description": "Vector de ataque del CVSS de la CNA (red, adyacente, local, físico)."},
    {"name": "ac", "type": "cat", "source": "NVD (CNA)", "description": "Complejidad del ataque (CVSS de la CNA)."},
    {"name": "pr", "type": "cat", "source": "NVD (CNA)", "description": "Privilegios requeridos (CVSS de la CNA)."},
    {"name": "ui", "type": "cat", "source": "NVD (CNA)", "description": "Interacción del usuario requerida (CVSS de la CNA)."},
    {"name": "cwe", "type": "cat", "source": "NVD (CNA)", "description": "Tipo de debilidad (CWE) indicado por la CNA."},
    {"name": "cna", "type": "cat", "source": "NVD", "description": "Quién publicó el CVE (CNA: Microsoft, Cisco, GitHub…); se fija al publicar."},
    {"name": "days_published", "type": "num", "source": "NVD", "description": "Días entre la publicación del CVE y la foto."},
    {"name": "edb_exploits", "type": "num", "source": "Exploit-DB", "description": "Exploits públicos del CVE dados de alta en Exploit-DB antes de la foto."},
    {"name": "cna_kev_prior", "type": "num", "source": "KEV + NVD", "description": "CVE de la misma CNA que ya estaban en KEV antes de la foto."},
]  # fmt: skip
EXCLUDED: list[dict[str, str]] = [
    {"name": "ssvc_exploitation / ssvc_automatable", "source": "CISA SSVC",
     "reason": "El feed solo trae la última evaluación y CISA la actualiza cuando hay explotación: el 99,5 % de los positivos "
               "salía «sin evaluar a la fecha» frente al 62 % del resto. La ausencia delataba la etiqueta."},
    {"name": "CVSS del NVD o de terceros (CISA ADP)", "source": "NVD",
     "reason": "Se agregan después de publicar y con prioridad a los CVE explotados: todos los positivos tenían CVSS y ningún CVE sin "
               "CVSS entraba a KEV. Solo se usa el CVSS de la propia CNA."},
    {"name": "CWE asignado por el NVD", "source": "NVD", "reason": "Se asigna al analizar, a menudo después de la foto; solo se usa el de la CNA."},
    {"name": "n_refs (número de referencias)", "source": "NVD", "reason": "Es el estado actual: las referencias a exploits y avisos se agregan cuando ya hay explotación."},
    {"name": "Módulos de Metasploit", "source": "Metasploit", "reason": "Solo traen la fecha de última modificación, no la de creación."},
]  # fmt: skip
FEATURE_NAMES = [f["name"] for f in FEATURES]
ID_COLUMNS = ["snapshot", "cve", "label", "weight", "split", "kev_date", "published"]


def snapshots(start: date, until: date, horizon_days: int) -> list[date]:
    """Primer día de cada mes desde `start` mientras la ventana de la etiqueta quepa antes de `until`."""
    out: list[date] = []
    d = date(start.year, start.month, 1)
    while d + timedelta(days=horizon_days) <= until:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def split_of(n: int) -> list[str]:
    """Partición temporal 70/15/15 por fotos (al menos una foto en validación y en prueba)."""
    if n < 3:
        raise ValueError("Hacen falta al menos 3 fotos mensuales para la partición 70/15/15")
    n_test = max(1, round(0.15 * n))
    n_val = max(1, round(0.15 * n))
    return ["desarrollo"] * (n - n_val - n_test) + ["validacion"] * n_val + ["prueba"] * n_test


def exploits(path: Path) -> pd.DataFrame:
    """(cve, date_added) de cada exploit de Exploit-DB que cita un CVE."""
    df = pd.read_csv(path, usecols=["codes", "date_added"], dtype=str)
    df = df.dropna(subset=["codes"]).assign(cve=lambda d: d["codes"].str.split(";")).explode("cve")
    df = df[df["cve"].str.match(r"^CVE-\d{4}-\d{4,}$", na=False)]
    df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce").dt.date
    return df.dropna(subset=["date_added"])[["cve", "date_added"]]


def snapshot_rows(s: date, horizon: int, epss: pd.DataFrame, prev: pd.DataFrame | None, model: str | None,
                  kev: pd.DataFrame, nvd_t: pd.DataFrame, edb: pd.DataFrame, neg_rate: float, rng: np.random.Generator) -> pd.DataFrame:  # fmt: skip
    """Filas de una foto. Nada posterior a `s` entra en las variables."""
    end = s + timedelta(days=horizon)
    known = set(kev.loc[kev["date_added"] <= s, "cve"])
    df = epss[~epss["cve"].isin(known)].copy()
    kev_future = kev[(kev["date_added"] > s) & (kev["date_added"] <= end)].set_index("cve")["date_added"]
    df["kev_date"] = df["cve"].map(kev_future)
    df["label"] = df["kev_date"].notna().astype(int)
    keep = (df["label"] == 1) | (rng.random(len(df)) < neg_rate)
    df = df[keep].copy()
    df["weight"] = np.where(df["label"] == 1, 1.0, 1.0 / neg_rate)
    df["snapshot"] = s
    df["epss_model"] = model or "desconocido"
    df["epss_delta"] = df["epss"] - df["cve"].map(prev.set_index("cve")["epss"]) if prev is not None else np.nan

    df = df.merge(nvd_t, on="cve", how="left")
    pub = pd.to_datetime(df["published"])
    df["days_published"] = (pd.Timestamp(s) - pub).dt.days
    df.loc[df["days_published"] < 0, "days_published"] = np.nan  # publicado en el NVD después de la foto
    prior = edb[edb["date_added"] <= s].groupby("cve").size()
    df["edb_exploits"] = df["cve"].map(prior).fillna(0).astype(int)
    kev_cna = kev[kev["date_added"] <= s].merge(nvd_t[["cve", "cna"]], on="cve", how="inner").groupby("cna").size()
    df["cna_kev_prior"] = df["cna"].map(kev_cna).fillna(0).astype(int)
    for col in ("av", "ac", "pr", "ui", "cwe", "cna"):
        df[col] = df[col].fillna("desconocido")
    return df[["snapshot", "cve", "label", "weight", "kev_date", "published", "cvss_src", *FEATURE_NAMES]]


def build(kev: pd.DataFrame, start: date, until: date, horizon: int, neg_rate: float, seed: int, out_path: Path,
          progress: Progress) -> dict[str, Any]:  # fmt: skip
    """Descarga las fuentes, arma todas las fotos y escribe el CSV comprimido. Devuelve procedencia y estadísticas."""
    shots = snapshots(start, until, horizon)
    splits = split_of(len(shots))
    meta: list[dict[str, Any]] = [{"kind": "kev", "name": sources.LICENSES["kev"][0], "license": sources.LICENSES["kev"][1],
                                   "url": "tabla kev_entries (actualizada por el flujo diario)", "entries": int(len(kev)),
                                   "last_date_added": until.isoformat()}]  # fmt: skip
    progress(3, "Descargando Exploit-DB")
    edb_path, m = sources.exploitdb()
    meta.append(m)
    edb = exploits(edb_path)

    years = list(range(2002, until.year + 1))
    nvd_paths: list[Path] = []
    for i, y in enumerate(years):
        progress(5 + int(30 * i / len(years)), f"Descargando NVD {y}")
        p, m = sources.nvd_year(y)
        nvd_paths.append(p)
        meta.append(m)
    progress(36, "Leyendo los feeds del NVD (registro por registro)")
    nvd_t = nvd.table(nvd_paths)

    rng = np.random.default_rng(seed)
    first = shots[0] - timedelta(days=30)
    p0, _, m0 = sources.epss_for(first)
    prev, _, _ = read_epss_csv(p0.read_bytes())
    meta.append(m0)
    parts: list[pd.DataFrame] = []
    for i, (s, split) in enumerate(zip(shots, splits, strict=True)):
        progress(45 + int(50 * i / len(shots)), f"Foto {s.isoformat()} ({i + 1} de {len(shots)})")
        path, day, m = sources.epss_for(s)
        epss, _, model = read_epss_csv(path.read_bytes())
        meta.append(m | {"model_version": model})
        rows = snapshot_rows(s, horizon, epss[["cve", "epss", "percentile"]], prev, model, kev, nvd_t, edb, neg_rate, rng)
        rows["split"] = split
        parts.append(rows)
        prev = epss[["cve", "epss"]]
    progress(96, "Guardando el dataset")
    df = pd.concat(parts, ignore_index=True)
    df.to_csv(out_path, index=False, compression="gzip")
    by_split = df.groupby("split").agg(rows=("cve", "size"), positives=("label", "sum"), snapshots=("snapshot", "nunique"))
    stats = {
        "rows": int(len(df)), "positives": int(df["label"].sum()), "snapshots": [s.isoformat() for s in shots],
        "by_split": {k: {kk: int(vv) for kk, vv in v.items()} for k, v in by_split.to_dict("index").items()},
        "nvd_cves": int(len(nvd_t)), "edb_exploits": int(len(edb)),
    }  # fmt: skip
    return {"sources": meta, "stats": stats}


def load(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, compression="gzip", dtype={"cve": str, "split": str})
    for col in ("snapshot", "kev_date", "published"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df
