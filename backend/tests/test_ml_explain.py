import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from app.core.config import get_settings
from app.ml import algorithms as algs
from app.ml import explain as xp
from app.ml import training
from app.models.ml import MlDataset, MlModel
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_dataset import wait_job
from tests.test_ml_training import synthetic
from tests.test_reports import Env


@pytest.fixture(autouse=True)
def _one_thread() -> Iterator[None]:
    with threadpool_limits(1):
        yield


def trained(algo: str, drop: tuple[str, ...] = ()) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    df = synthetic(rows=500, seed=3)
    params = algs.defaults(algo) | ({"max_iter": 60} if algo == "hgb" else {})
    dev, rest = df[df["split"] == "desarrollo"], df[df["split"].isin(["validacion", "prueba"])]
    model, s = training.fit_predict(algo, params, 1, dev, rest, drop)
    preds = rest[["snapshot", "cve", "split", "label", "weight"]].assign(score=s)
    return {"pipeline": model, "drop": list(drop)}, df, preds


def test_explanations_point_to_the_real_signal() -> None:
    bundle, df, preds = trained("hgb")
    r = xp.explain(bundle, df, preds, repeats=2, pdp_rows=300, n_cases=3)
    groups = {x["name"]: x["mean"] for x in r["importance"]["rows"] if x["kind"] == "grupo"}
    assert groups["EPSS"] > groups["CNA (quién publicó)"] and groups["CVSS de la CNA"] > groups["CNA (quién publicó)"]
    epss = next(d for d in r["pdp"] if d["feature"] == "epss")["points"]
    assert epss[-1]["y"] > epss[0]["y"]  # a más EPSS, más probabilidad (así se generaron los datos)
    assert r["pdp2d"] is not None and len(r["pdp2d"]["cells"]) == len(r["pdp2d"]["xs"]) * len(r["pdp2d"]["ys"])
    assert set(r["local"]) == {"aciertos", "escapados", "falsas_alarmas"} and all(len(v) == 3 for v in r["local"].values())
    case = r["local"]["aciertos"][0]
    assert case["label"] == 1 and len(case["attributions"]) == len(xp.GROUPS) and "epss" in case["values"]
    assert r["coefficients"] == [] and len(r["equivalences"]) == 3 and r["interpretation"]


def test_ablated_group_gets_zero_attribution_and_logreg_has_coefficients() -> None:
    bundle, df, preds = trained("hgb", ("epss",))
    r = xp.explain(bundle, df, preds, repeats=2, pdp_rows=200, n_cases=2)
    for cases in r["local"].values():
        for c in cases:
            assert next(a["delta"] for a in c["attributions"] if a["group"] == "EPSS") == 0  # tapar EPSS no cambia nada
    assert next(x for x in r["importance"]["rows"] if x["name"] == "EPSS")["mean"] == 0
    assert not any(t.startswith("Casi no usa: EPSS") for t in r["interpretation"])  # ya lo dice la nota de ablación
    assert all(d["feature"] not in ("epss", "percentile") for d in r["pdp"])
    lr, df2, preds2 = trained("logreg")
    coef = xp.explain(lr, df2, preds2, repeats=1, pdp_rows=200, n_cases=1)["coefficients"]
    assert coef and abs(coef[0]["coef"]) >= abs(coef[-1]["coef"])


def test_explanation_endpoint(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    bundle, df, preds = trained("logreg")
    ds_path, model_path, preds_path = tmp_path / "ds.csv.gz", tmp_path / "m.joblib", tmp_path / "m.preds.csv.gz"
    df.to_csv(ds_path, index=False, compression="gzip")
    joblib.dump(bundle, model_path)
    preds.to_csv(preds_path, index=False, compression="gzip")
    did, mid = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="d", status="ready", file_path=str(ds_path), params={}, stats={}, sources=[], tags=[]))
        db.flush()
        db.add(MlModel(id=mid, dataset_id=did, algorithm="logreg", name="LR", status="ready", config={}, folds=[], trials=[], aggregate={},
                       best_params={}, final_metrics={}, reading=[], model_path=str(model_path), preds_path=str(preds_path)))  # fmt: skip
        db.commit()
    h = login(c, "gerencia@radar.local")
    first = c.get(f"/api/v1/ml/models/{mid}/explanation", headers=h).json()
    assert first["status"] == "computing"
    job = wait_job(c, h, first["job_id"], timeout=180)
    assert job["status"] == "done", job["message"]
    r = c.get(f"/api/v1/ml/models/{mid}/explanation", headers=h).json()
    assert r["model"]["name"] == "LR" and r["coefficients"] and (tmp_path / "cache" / f"explain_{mid}_v4.json").exists()
    assert c.get(f"/api/v1/ml/models/{uuid.uuid4()}/explanation", headers=h).status_code == 404
