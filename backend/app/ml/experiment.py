"""Ejecución reproducible de UN experimento del Laboratorio desde un archivo JSON (sin API ni base de datos).

    python -m app.ml.experiment config.json

Escribe `<out_dir>/<name>.json` (configuración, versiones, hardware, SHA-256 del dataset, pliegues, pruebas de Optuna,
hiperparámetros elegidos, métricas por partición con eventos únicos y tiempos) y `<name>.preds.csv.gz` con las predicciones.
Cada cifra del artículo debe poder rastrearse a uno de esos archivos. No modifica la detección ni el score."""

import gzip
import hashlib
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
import sklearn

from app.ml import algorithms as algs
from app.ml import dataset as ds
from app.ml import training

DEFAULTS: dict[str, Any] = {"n_trials": 10, "seed": 7, "drop": [], "sampler": "tpe", "k_out": 4, "k_in": 2, "v_out": 3, "v_in": 2,
                            "horizon": 90, "space": None}  # fmt: skip
REQUIRED = ("name", "dataset_path", "algorithm", "out_dir")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_gz(path: Path) -> str:
    """SHA-256 del contenido descomprimido (la cabecera gzip lleva la fecha de escritura y cambiaría en cada corrida)."""
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def environment() -> dict[str, Any]:
    return {"python": sys.version.split()[0], "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__, "optuna": optuna.__version__}  # fmt: skip


def validate(cfg: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError(f"Faltan campos en la configuración: {', '.join(missing)}")
    full = DEFAULTS | cfg
    if full["algorithm"] not in algs.ALGORITHMS:
        raise ValueError(f"Algoritmo desconocido: {full['algorithm']}")
    bad = [g for g in full["drop"] if g not in algs.GROUPS]
    if bad:
        raise ValueError(f"Grupos de ablación desconocidos: {', '.join(bad)}")
    if full["sampler"] not in ("tpe", "random"):
        raise ValueError("sampler debe ser 'tpe' o 'aleatorio' ('random')")
    return full


def split_summary(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sp, g in df.groupby("split"):
        pos = g[g["label"] == 1]
        out[str(sp)] = {"snapshots": int(g["snapshot"].nunique()), "rows": int(len(g)), "positive_rows": int(len(pos)),
                        "events": int(pos["cve"].nunique()), "first": str(g["snapshot"].min()), "last": str(g["snapshot"].max())}  # fmt: skip
    return out


def run(cfg: dict[str, Any], report: training.Report | None = None) -> dict[str, Any]:
    full = validate(cfg)
    path = Path(full["dataset_path"])
    out_dir = Path(full["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    df = ds.load(path)
    dev_dates = sorted(df.loc[df["split"] == "desarrollo", "snapshot"].unique())
    problem = training.feasible_embargo(
        dev_dates, full["k_out"], full["k_in"], full["v_out"], full["v_in"], full["horizon"]
    )
    if problem:
        raise ValueError(problem)
    drop = tuple(sorted(set(full["drop"])))
    space = algs.custom_space(full["algorithm"], full["space"]) if full["space"] else None
    t0 = datetime.now(UTC)
    res = training.train(df, full["algorithm"], full["n_trials"], full["k_out"], full["k_in"], full["seed"], report or (lambda m, e: None),
                         drop, space, full["v_out"], full["v_in"], full["horizon"], full["sampler"])  # fmt: skip
    base = out_dir / full["name"]
    preds_path = Path(f"{base}.preds.csv.gz")
    res["preds"].to_csv(preds_path, index=False, compression="gzip")
    pruned = sum(1 for t in res["trials"] if t.get("pruned"))
    doc = {
        "config": full, "started_at": t0.isoformat(), "seconds": res["seconds"], "environment": environment(),
        "dataset": {"path": str(path), "sha256": sha256(path), "splits": split_summary(df)},
        "folds": res["folds"], "aggregate": res["aggregate"], "best_params": res["best_params"], "best_iter": res["best_iter"],
        "trials": res["trials"], "trials_pruned": pruned, "final_metrics": res["final_metrics"],
        "preds_file": preds_path.name, "preds_sha256": sha256_gz(preds_path),
    }  # fmt: skip
    Path(f"{base}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return doc


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: python -m app.ml.experiment config.json", file=sys.stderr)
        return 2
    cfg = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    doc = run(cfg, lambda msg, _e: print(f"[{time.perf_counter() - t0:7.1f} s] {msg}", flush=True))
    print(
        json.dumps(
            {"final_metrics": doc["final_metrics"], "best_params": doc["best_params"]},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
