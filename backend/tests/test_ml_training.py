import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.ml import algorithms as algs
from app.ml import training
from app.ml.dataset import split_of
from app.ml.metrics import evaluate, recall_at
from app.models.ml import MlDataset
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_dataset import wait_job
from tests.test_reports import Env


def synthetic(n_snaps: int = 20, rows: int = 300, seed: int = 0) -> pd.DataFrame:
    """Dataset con señal real: la probabilidad de entrar a KEV crece con EPSS, CVSS y si el CVE es reciente."""
    rng = np.random.default_rng(seed)
    snaps = [date(2025, 1, 1) + timedelta(days=31 * i) for i in range(n_snaps)]
    snaps = [date(s.year, s.month, 1) for s in snaps]
    splits = split_of(n_snaps)
    parts = []
    for s, sp in zip(snaps, splits, strict=True):
        epss = rng.beta(0.3, 8, rows)
        cvss = np.where(rng.random(rows) < 0.6, rng.uniform(3, 10, rows), np.nan)
        days = rng.integers(1, 3000, rows).astype(float)
        logit = -4.5 + 8 * epss + 0.35 * np.nan_to_num(cvss, nan=4) - 0.0008 * days  # ~4 % positivos
        y = (rng.random(rows) < 1 / (1 + np.exp(-logit))).astype(int)
        parts.append(pd.DataFrame({
            "snapshot": s, "cve": [f"CVE-{s.isoformat()}-{i}" for i in range(rows)], "label": y, "weight": np.where(y == 1, 1.0, 10.0),
            "split": sp, "kev_date": None, "published": None, "cvss_src": "cna", "epss": epss, "percentile": epss, "epss_delta": 0.0,
            "epss_model": "v1", "cvss": cvss, "av": rng.choice(["NETWORK", "LOCAL"], rows), "ac": "LOW", "pr": "NONE", "ui": "NONE",
            "cwe": rng.choice(["CWE-78", "CWE-79", "CWE-22"], rows), "cna": rng.choice(["ms", "gh", "mitre"], rows),
            "days_published": days, "edb_exploits": rng.integers(0, 2, rows), "cna_kev_prior": rng.integers(0, 50, rows),
        }))  # fmt: skip
    return pd.concat(parts, ignore_index=True)


def test_forward_folds_always_train_on_the_past() -> None:
    snaps = [date(2025, m, 1) for m in range(1, 13)] + [date(2026, 1, 1), date(2026, 2, 1)]
    folds = training.forward_folds(snaps, 5)
    assert len(folds) == 5 and len(folds[0][0]) == 4 and all(len(va) == 2 for _, va in folds)
    assert all(max(tr) < min(va) for tr, va in folds)
    assert [len(tr) for tr, _ in folds] == [4, 6, 8, 10, 12]
    inner = training.forward_folds(folds[0][0], 3)
    assert [(len(tr), len(va)) for tr, va in inner] == [(1, 1), (2, 1), (3, 1)]
    assert training.feasible(14, 5, 3) is None
    assert "fecha anterior" in (training.feasible(12, 5, 3) or "") and "al menos 6" in (training.feasible(5, 5, 3) or "")


def test_weighted_metrics() -> None:
    y = np.array([1, 0, 0, 1, 0])
    s = np.array([0.9, 0.8, 0.1, 0.7, 0.2])
    m = evaluate(y, s, np.ones(5))
    assert m["roc_auc"] == pytest.approx(5 / 6, abs=1e-3) and 0 < m["pr_auc"] <= 1
    assert recall_at(y, s, np.ones(5), 0.2) == 0.5  # el primer 20 % (1 fila) contiene 1 de los 2 positivos
    assert evaluate(np.zeros(3), np.ones(3), np.ones(3))["pr_auc"] is None


@pytest.fixture
def small_trees(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Árboles chicos y un solo hilo en los tests (misma lógica, segundos en vez de minutos: con datos minúsculos, los
    hilos de OpenMP cuestan más de lo que ahorran)."""
    from threadpoolctl import threadpool_limits

    small = {"n_estimators": (10, 30, 20), "max_depth": (2, 6, 4), "max_iter": (10, 30, 20), "max_leaf_nodes": (7, 15, 7)}
    spaces = {k: [dict(p) for p in v] for k, v in algs.SPACES.items()}
    for params in spaces.values():
        for p in params:
            if p["name"] in small:
                p["low"], p["high"], p["default"] = small[p["name"]]
    monkeypatch.setattr(algs, "SPACES", spaces)
    with threadpool_limits(1):
        yield


@pytest.mark.parametrize("algo", ["logreg", "random_forest", "hgb"])
def test_nested_cv_and_final_model_for_each_algorithm(algo: str, small_trees: None) -> None:
    df = synthetic()
    events: list[tuple[str, Any]] = []
    res = training.train(df, algo, n_trials=2, k_out=5, k_in=3, seed=1, report=lambda m, e: events.append((m, e)))
    assert len(res["folds"]) == 5 and len(res["trials"]) == 6 * 2  # 5 pliegues + modelo final, 2 pruebas cada uno
    assert res["trials"][0]["params"] == algs.defaults(algo)  # la prueba 0 de cada búsqueda es la configuración por defecto
    for f in res["folds"]:
        assert f["train"][1] < f["val"][0] and f["metrics"]["pr_auc"] is not None and "epss" in f["baselines"]
    agg = res["aggregate"]
    assert agg["model"]["pr_auc"]["n"] == 5 and agg["model"]["roc_auc"]["mean"] > 0.65  # aprende la señal sintética
    assert set(res["preds"]["split"]) == {"validacion", "prueba"} and {"baseline_epss", "baseline_cvss"} <= set(res["preds"].columns)
    assert res["final_metrics"]["validacion"]["roc_auc"] > 0.7  # hay señal y el modelo la encuentra
    assert any(e and "fold" in e for _, e in events) and sum(1 for _, e in events if e and "trial" in e) == 12
    assert training.notes(algo, agg, res["final_metrics"], 5)[0].startswith(algs.ALGORITHMS[algo]["label"])


def test_train_endpoint_runs_in_background_and_stores_the_model(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    path = tmp_path / "ds.csv.gz"
    synthetic(rows=200).to_csv(path, index=False, compression="gzip")
    did, short = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="sintético", status="ready", file_path=str(path), params={"horizon_days": 90},
                         stats={"by_split": {"desarrollo": {"snapshots": 14}}}, sources=[], tags=[]))  # fmt: skip
        db.add(MlDataset(id=short, name="corto", status="ready", file_path=str(path), params={},
                         stats={"by_split": {"desarrollo": {"snapshots": 8}}}, sources=[], tags=[]))  # fmt: skip
        db.commit()
    body = {"dataset_id": str(did), "algorithm": "logreg", "n_trials": 2}
    assert c.post("/api/v1/ml/models", json=body, headers=login(c, "gerencia@radar.local")).status_code == 403
    h = login(c, "analista@radar.local")
    assert c.post("/api/v1/ml/models", json=body | {"dataset_id": str(short)}, headers=h).status_code == 422
    assert c.post("/api/v1/ml/models", json=body | {"algorithm": "svm"}, headers=h).status_code == 422
    assert {a["key"] for a in c.get("/api/v1/ml/algorithms", headers=h).json()} == {"logreg", "random_forest", "hgb"}
    r = c.post("/api/v1/ml/models", json=body, headers=h)
    assert r.status_code == 202, r.text
    job = wait_job(c, h, r.json()["job_id"], timeout=120)
    assert job["status"] == "done", job["message"]
    mod = c.get(f"/api/v1/ml/models/{r.json()['model_id']}", headers=login(c, "gerencia@radar.local")).json()
    assert mod["status"] == "ready" and len(mod["folds"]) == 5 and len(mod["trials"]) == 12 and mod["reading"]
    assert mod["config"]["k_out"] == 5 and mod["config"]["k_in"] == 3 and mod["best_params"]
    assert (tmp_path / "models" / f"{mod['id']}.joblib").exists() and (tmp_path / "models" / f"{mod['id']}.preds.csv.gz").exists()
    listed = c.get("/api/v1/ml/models", params={"dataset_id": str(did)}, headers=h).json()
    assert [x["id"] for x in listed] == [mod["id"]] and "trials" not in listed[0]
