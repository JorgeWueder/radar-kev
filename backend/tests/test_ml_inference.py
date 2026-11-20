import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sqlalchemy import select
from threadpoolctl import threadpool_limits

from app.core.config import get_settings
from app.ml import inference as inf
from app.ml import training
from app.models.audit import AuditLog
from app.models.ml import MlDataset, MlModel
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_training import synthetic
from tests.test_reports import Env


@pytest.fixture(autouse=True)
def _one_thread() -> Iterator[None]:
    with threadpool_limits(1):
        yield


def test_platt_matches_unregularized_logistic_regression() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=4000)
    y = (rng.random(4000) < 1 / (1 + np.exp(-(1.7 * x - 2.0)))).astype(int)
    w = np.where(y == 1, 1.0, rng.choice([1.0, 20.0], 4000))
    a, b = inf._platt(x, y, w)
    ref = LogisticRegression(C=1e9, max_iter=5000, tol=1e-12).fit(x.reshape(-1, 1), y, sample_weight=w)
    assert a == pytest.approx(ref.coef_[0, 0], rel=1e-4) and b == pytest.approx(ref.intercept_[0], rel=1e-4)


def test_intervals() -> None:
    lo, hi = inf.wilson(5, 100)
    assert 0.02 < lo < 0.05 < hi < 0.12
    assert inf.wilson(0, 0) == (0.0, 1.0)


def preds_from(rng: np.random.Generator, n: int, a: float, b: float) -> pd.DataFrame:
    """Predicciones cuyo logit verdadero es a·logit(puntaje) + b, con negativos muestreados al 10 % (peso 10)."""
    s = rng.beta(0.5, 6, n)
    p = 1 / (1 + np.exp(-(a * inf._logit(s) + b)))
    y = (rng.random(n) < p).astype(int)
    keep = (y == 1) | (rng.random(n) < 0.1)
    return pd.DataFrame({"score": s[keep], "label": y[keep], "weight": np.where(y[keep] == 1, 1.0, 10.0)})


def test_calibration_recovers_the_truth_and_is_checked_on_test() -> None:
    rng = np.random.default_rng(3)
    val, test = preds_from(rng, 60_000, 1.3, -1.5), preds_from(rng, 60_000, 1.3, -1.5)
    p = pd.concat([val.assign(split="validacion"), test.assign(split="prueba")], ignore_index=True)
    c = inf.calibrate(p, n_boot=60)
    a, b = c["params"]
    assert a == pytest.approx(1.3, abs=0.15) and b == pytest.approx(-1.5, abs=0.3)
    t = c["test"]
    assert t["oe_lo"] <= 1 <= t["oe_hi"] and t["slope"] == pytest.approx(1, abs=0.15)
    assert sum(b["recall"] for b in c["bands"]) == pytest.approx(1)
    crit = next(b for b in c["bands"] if b["key"] == "critica")
    assert crit["share"] == pytest.approx(0.01, abs=0.004) and crit["lift"] > 3  # mismo universo: ~1 % en la banda Crítica
    assert inf.top_of(c["grid"], c["thresholds"]["critica"]) == pytest.approx(0.01, rel=0.1)
    assert any("compatible con una calibración correcta" in r for r in c["reading"])
    # Si en prueba entran la mitad de los esperados, la verificación lo detecta.
    shifted = pd.concat([val.assign(split="validacion"), preds_from(rng, 60_000, 1.3, -2.3).assign(split="prueba")], ignore_index=True)
    assert any("SOBREESTIMA" in r for r in inf.calibrate(shifted, n_boot=30)["reading"])
    with pytest.raises(ValueError):
        inf.calibrate(p[p["label"] == 0])


def setup_model(m: Any, tmp: Path) -> tuple[uuid.UUID, pd.DataFrame]:
    df = synthetic(rows=300, seed=5)
    df["cve"] = [f"CVE-2025-{10_000 + i % 300}" for i in range(len(df))]  # el mismo CVE aparece en cada foto
    df["kev_date"] = [s + timedelta(days=20) if y else None for s, y in zip(df["snapshot"], df["label"], strict=True)]
    path = tmp / "ds.csv.gz"
    df.to_csv(path, index=False, compression="gzip")
    res = training.train(df, "logreg", 2, 5, 3, 1, lambda msg, e: None)
    model_path, preds_path = tmp / "m.joblib", tmp / "m.preds.csv.gz"
    joblib.dump({"pipeline": res["model"], "drop": []}, model_path)
    res["preds"].to_csv(preds_path, index=False, compression="gzip")
    did, mid = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="Sintético", status="ready", file_path=str(path), params={"horizon_days": 90}, stats={}, tags=[], sources=[]))
        db.flush()
        db.add(MlModel(id=mid, dataset_id=did, algorithm="logreg", name="Regresión logística", status="ready", seconds=1.0,
                       config={"drop": []}, folds=res["folds"], aggregate=res["aggregate"], trials=res["trials"], best_params=res["best_params"],
                       final_metrics=res["final_metrics"], reading=[], model_path=str(model_path), preds_path=str(preds_path)))  # fmt: skip
        db.commit()
    return mid, df


def test_inference_api(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    mid, df = setup_model(m, tmp_path)
    h = login(c, "analista@radar.local")
    base = f"/api/v1/ml/models/{mid}"

    s = c.get(f"{base}/inference", headers=h).json()
    assert "boot" not in s["calibration"] and "grid" not in s["calibration"]
    assert [b["key"] for b in s["calibration"]["bands"]] == ["critica", "alta", "media", "baja"]
    assert s["horizon_days"] == 90 and set(s["baseline"]) >= {"epss", "cna"} and s["options"]["categorical"]["cna"]

    cases = c.get(f"{base}/cases", params={"q": "CVE-2025-1001"}, headers=h).json()
    assert cases and all(x["cve"].startswith("CVE-2025-1001") for x in cases)
    assert cases[0]["snapshot"] >= cases[-1]["snapshot"]
    assert c.get(f"{base}/cases", params={"q": "drop table"}, headers=h).status_code == 422

    pos = df[(df["label"] == 1) & (df["split"] == "prueba")].iloc[0]
    r = c.post(f"{base}/predict", json={"cve": pos["cve"], "snapshot": str(pos["snapshot"])}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    res = out["result"]
    assert 0 < res["p_lo"] <= res["probability"] <= res["p_hi"] < 1 and res["band"] in {"critica", "alta", "media", "baja"}
    assert len(res["attributions"]) == 7 and out["case"]["label"] == 1 and out["case"]["days_to_kev"] == 20
    assert any("Resultado real: entró a KEV" in t for t in out["reading"])

    dev = df[df["split"] == "desarrollo"].iloc[0]
    out = c.post(f"{base}/predict", json={"cve": dev["cve"], "snapshot": str(dev["snapshot"])}, headers=h).json()
    assert any("se usó para ENTRENAR" in t for t in out["reading"])

    hot = s["baseline"] | {"epss": 0.9, "percentile": 0.99, "cvss": 9.8, "days_published": 5}
    cold = s["baseline"] | {"epss": 0.0005, "percentile": 0.05, "cvss": None, "days_published": 2900}
    p_hot = c.post(f"{base}/predict", json={"values": hot}, headers=h).json()
    p_cold = c.post(f"{base}/predict", json={"values": cold}, headers=h).json()
    assert p_hot["result"]["probability"] > p_cold["result"]["probability"]
    assert p_cold["values"]["cvss"] is None and any("hipotético" in t for t in p_cold["reading"])

    assert c.post(f"{base}/predict", json={}, headers=h).status_code == 422
    assert c.post(f"{base}/predict", json={"cve": "CVE-2025-10001", "values": hot}, headers=h).status_code == 422
    assert c.post(f"{base}/predict", json={"values": hot | {"epss": 3}}, headers=h).status_code == 422
    assert c.post(f"{base}/predict", json={"cve": "CVE-1999-0001"}, headers=h).status_code == 404

    rk = c.get(f"{base}/ranking", headers=h).json()
    assert rk["split"] == "prueba" and len(rk["rows"]) == 20 and rk["snapshot"] == rk["snapshots"][-1]
    assert rk["rows"][0]["probability"] >= rk["rows"][-1]["probability"]
    assert c.get(f"{base}/ranking", params={"snapshot": "2020-01-01"}, headers=h).status_code == 422

    with m() as db:
        n = db.execute(select(AuditLog).where(AuditLog.module == "ml", AuditLog.action == "model_predict")).scalars().all()
        assert len(n) == 4


def test_inference_needs_a_ready_model(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, _ = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    h = login(c, "analista@radar.local")
    assert c.get(f"/api/v1/ml/models/{uuid.uuid4()}/inference", headers=h).status_code == 404
