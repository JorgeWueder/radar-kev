import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.ml import assess
from app.models.ml import MlDataset, MlModel
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_dataset import wait_job
from tests.test_ml_training import synthetic
from tests.test_reports import Env


def preds(noise: float, seed: int) -> pd.DataFrame:
    """Predicciones de validación y prueba: un puntaje que separa mejor cuanto menor es `noise`."""
    df = synthetic(rows=400, seed=0)
    rest = df[df["split"].isin(["validacion", "prueba"])].reset_index(drop=True)
    rng = np.random.default_rng(seed)
    out = rest[["snapshot", "cve", "split", "label", "weight"]].copy()
    out["score"] = rest["label"] * 1.0 + rng.normal(0, noise, len(rest))
    out["baseline_epss"] = rest["epss"]
    out["baseline_cvss"] = rest["cvss"].fillna(0)
    return out


def folds(base: float) -> list[dict[str, Any]]:
    return [{"metrics": {"pr_auc": base + 0.01 * i}, "baselines": {"epss": {"pr_auc": 0.02 + 0.005 * i}, "cvss": {"pr_auc": 0.001 * i}}}
            for i in range(5)]  # fmt: skip


def test_threshold_is_set_on_validation_and_confusion_adds_up() -> None:
    s = np.arange(100, dtype=float)
    assert assess.threshold_for(s, np.ones(100), 0.05) == 95.0  # marca s >= 95: las 5 filas del 5 % superior
    y = (s >= 90).astype(int)
    c = assess.confusion(y, s, np.where(y == 1, 1.0, 10.0), 95.0)
    assert c["raw"] == {"tp": 5, "fp": 0, "fn": 5, "tn": 90} and c["recall"] == 0.5
    assert c["estimated"]["tn"] == 900 and c["precision"] == 1.0


def test_bootstrap_mcnemar_and_friedman() -> None:
    rng = np.random.default_rng(1)
    y = (rng.random(3000) < 0.05).astype(int)
    w = np.ones(3000)
    good, bad = y + rng.normal(0, 0.3, 3000), y + rng.normal(0, 3, 3000)
    d = assess.bootstrap_diff(y, w, good, bad, n=100)
    assert d["roc_auc"]["ci"][0] > 0 and d["roc_auc"]["p"] < 0.05  # el bueno gana de forma robusta
    same = assess.bootstrap_diff(y, w, good, good + 1e-9 * rng.random(3000), n=100)
    assert same["roc_auc"]["ci"][0] <= 0 <= same["roc_auc"]["ci"][1]
    m = assess.mcnemar(y, good > 0.5, bad > 0.5)
    assert m["only_a"] > m["only_b"] and m["p"] < 0.05
    f = assess.friedman({"a": [0.9, 0.8, 0.85, 0.9, 0.88], "b": [0.5, 0.4, 0.45, 0.5, 0.42], "c": [0.1, 0.2, 0.15, 0.1, 0.12]})
    assert f["p"] < 0.05 and f["mean_rank"]["a"] == 1.0 and f["mean_rank"]["c"] == 3.0


def test_assess_compares_models_and_baselines_on_test() -> None:
    models = [{"id": "m1", "name": "Bueno", "algorithm": "hgb", "drop": [], "folds": folds(0.08), "preds": preds(0.4, 1)},
              {"id": "m2", "name": "Ruidoso", "algorithm": "logreg", "drop": [], "folds": folds(0.01), "preds": preds(2.0, 2)}]  # fmt: skip
    r = assess.assess(models, 5.0)
    keys = [x["key"] for x in r["rows"]]
    assert keys == ["m1", "m2", "epss", "cvss"] and r["best"] == "m1"
    assert r["confusion"]["m1"]["raw"]["tp"] + r["confusion"]["m1"]["raw"]["fn"] == int(models[0]["preds"].query("split == 'prueba'")["label"].sum())
    assert {p["b"] for p in r["pairs"]} == {"m2", "epss", "cvss"} and all("mcnemar" in p for p in r["pairs"])
    assert r["friedman"]["p"] is not None and len(r["stability"]) == 3  # 3 fotos de prueba
    assert set(r["curves"]["m1"]) == {"roc", "pr"} and len(r["curves"]["m1"]["roc"]) <= assess.POINTS
    assert r["best"] == r["test_best"] == "m1"  # elegido en validación; aquí también es el mejor en prueba
    assert r["interpretation"][0].startswith("Modelo elegido en validación (sin mirar la prueba): Bueno")
    assert "5 %" in r["how_to_read"]["confusion"]


def test_evaluation_endpoint_caches_and_requires_models(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    ds_path = tmp_path / "ds.csv.gz"
    ds_path.write_bytes(b"x")
    did, mid = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="d", status="ready", file_path=str(ds_path), params={}, stats={}, sources=[], tags=[]))
        db.commit()
    h = login(c, "auditor@radar.local")
    assert c.get(f"/api/v1/ml/datasets/{did}/evaluation", headers=h).status_code == 409
    p = tmp_path / "m.preds.csv.gz"
    preds(0.5, 3).to_csv(p, index=False, compression="gzip")
    with m() as db:
        db.add(MlModel(id=mid, dataset_id=did, algorithm="hgb", name="HGB", status="ready", config={"drop": []}, folds=folds(0.05),
                       trials=[], aggregate={}, best_params={}, final_metrics={}, reading=[], preds_path=str(p)))  # fmt: skip
        db.commit()
    first = c.get(f"/api/v1/ml/datasets/{did}/evaluation", params={"op": 5}, headers=h).json()
    assert first["status"] == "computing"  # se calcula en segundo plano
    job = wait_job(c, h, first["job_id"], timeout=120)
    assert job["status"] == "done", job["message"] and any("Bootstrap" in e["msg"] for e in job["log"])
    r = c.get(f"/api/v1/ml/datasets/{did}/evaluation", params={"op": 5}, headers=h)
    assert r.status_code == 200 and r.json()["best"] == str(mid) and r.json()["models"][0]["name"] == "HGB" and r.json()["operating_pct"] == 5
    assert len(list((tmp_path / "cache").glob("eval_*.json"))) == 1
    assert c.get(f"/api/v1/ml/datasets/{did}/evaluation", params={"op": 5}, headers=h).json() == r.json()  # desde la caché
    assert c.get(f"/api/v1/ml/datasets/{did}/evaluation", params={"op": 3}, headers=h).status_code == 422
