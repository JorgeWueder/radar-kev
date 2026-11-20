import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from threadpoolctl import threadpool_limits

from app.core.config import get_settings
from app.ml import algorithms as algs
from app.ml import optimize
from app.models.ml import MlDataset
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_dataset import wait_job
from tests.test_ml_training import synthetic
from tests.test_reports import Env


@pytest.fixture(autouse=True)
def _one_thread() -> Iterator[None]:
    with threadpool_limits(1):
        yield


def test_custom_space_is_validated_against_the_limits() -> None:
    sp = {p["name"]: p for p in algs.custom_space("logreg", {"C": {"low": 1e-4, "high": 0.5}, "class_weight": {"choices": ["none"]}})}
    assert sp["C"]["low"] == 1e-4 and sp["C"]["high"] == 0.5 and sp["C"]["default"] == 0.5  # el defecto (1) se recorta al rango
    assert sp["class_weight"]["choices"] == ["none"] and sp["class_weight"]["default"] == "none"
    assert algs.custom_space("hgb", None) == algs.SPACES["hgb"]
    rf = {p["name"]: p for p in algs.custom_space("random_forest", {"max_depth": {"low": 3.4, "high": 20.6}})}
    assert (rf["max_depth"]["low"], rf["max_depth"]["high"]) == (3, 21)
    for bad in ({"C": {"low": 1, "high": 0.1}}, {"C": {"low": 1e-9, "high": 1}}, {"C": {"high": 1000}},
                {"class_weight": {"choices": ["equilibrado"]}}, {"gamma": {"low": 1, "high": 2}}):  # fmt: skip
        with pytest.raises(ValueError):
            algs.custom_space("logreg", bad)


def test_edges_suggest_a_wider_range_unless_at_the_limit() -> None:
    space = algs.custom_space("logreg", None)
    e = optimize.edges({"C": 0.0012, "class_weight": "balanced"}, space, "logreg")
    assert len(e) == 1 and e[0]["side"] == "inferior" and e[0]["suggest"] == {"low": pytest.approx(1e-4), "high": 10.0}
    assert optimize.edges({"C": 0.3}, space, "logreg") == []
    at_limit = algs.custom_space("logreg", {"C": {"low": 1e-5, "high": 1}})
    e = optimize.edges({"C": 1.1e-5}, at_limit, "logreg")
    assert e[0]["at_limit"] and e[0]["suggest"] is None
    rf = algs.custom_space("random_forest", None)
    e = optimize.edges({"n_estimators": 300, "max_depth": 9, "min_samples_leaf": 10}, rf, "random_forest")
    assert [x["param"] for x in e] == ["n_estimators"] and e[0]["side"] == "superior" and e[0]["suggest"] == {"low": 100.0, "high": 400.0}


def cfg(**kw: Any) -> dict[str, Any]:
    return {"sampler": "tpe", "pruner": "median", "n_trials": 8, "timeout_minutes": 10, "seed": 3, "k_in": 3, "include_defaults": True, "drop": []} | kw


def test_study_runs_reports_each_trial_and_summarizes() -> None:
    dev = synthetic(n_snaps=8, rows=300, seed=2)
    seen: list[dict[str, Any]] = []
    res = optimize.run(dev, "logreg", algs.custom_space("logreg", None), cfg(), lambda r: seen.append(r) is not None)
    assert len(seen) == 8 and seen == res["trials"] and seen[0]["default"] and seen[0]["params"] == algs.defaults("logreg")
    assert all(r["state"] in {"completa", "podada"} for r in seen) and res["n_folds"] == 3
    best = max((r for r in seen if r["state"] == "completa"), key=lambda r: r["value"])
    assert res["best_value"] == pytest.approx(best["value"], abs=1e-6) and res["best_params"] == best["params"]
    assert seen[-1]["best"] == pytest.approx(res["best_value"], abs=1e-6)
    s = res["summary"]
    assert s["n_trials"] == 8 and s["best_trial"] == best["number"] and s["reading"][0].startswith("Mejor PR-AUC interna")
    assert {i["param"] for i in s["importance"]} <= {"C", "class_weight"}
    assert any("prueba 0" in t for t in s["reading"])
    assert any("fase inicial al azar" in t for t in s["reading"])  # 8 pruebas con TPE: no salió del arranque aleatorio


def test_study_can_be_stopped_between_trials() -> None:
    dev = synthetic(n_snaps=8, rows=200, seed=4)
    n = {"k": 0}

    def stop_after_three(rec: dict[str, Any]) -> bool:
        n["k"] += 1
        return n["k"] >= 3

    res = optimize.run(dev, "logreg", algs.custom_space("logreg", None), cfg(sampler="random", pruner="none", n_trials=20), stop_after_three)
    assert len(res["trials"]) == 3 and res["summary"]["n_trials"] == 3


def test_study_api_runs_in_background(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    path = tmp_path / "ds.csv.gz"
    synthetic(rows=200).to_csv(path, index=False, compression="gzip")
    did = uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="sintético", status="ready", file_path=str(path), params={"horizon_days": 90},
                         stats={"by_split": {"desarrollo": {"snapshots": 14}}}, sources=[], tags=[]))  # fmt: skip
        db.commit()
    body = {"dataset_id": str(did), "algorithm": "logreg", "n_trials": 5, "sampler": "random", "pruner": "none",
            "space": {"C": {"low": 0.01, "high": 5}}}  # fmt: skip
    assert c.post("/api/v1/ml/studies", json=body, headers=login(c, "gerencia@radar.local")).status_code == 403
    h = login(c, "analista@radar.local")
    assert c.post("/api/v1/ml/studies", json=body | {"space": {"C": {"low": 5, "high": 1}}}, headers=h).status_code == 422
    assert c.post("/api/v1/ml/studies", json=body | {"sampler": "cmaes"}, headers=h).status_code == 422
    r = c.post("/api/v1/ml/studies", json=body, headers=h)
    assert r.status_code == 202, r.text
    job = wait_job(c, h, r.json()["job_id"], timeout=120)
    assert job["status"] == "done", job["message"]
    st = c.get(f"/api/v1/ml/studies/{r.json()['study_id']}", headers=login(c, "gerencia@radar.local")).json()
    assert st["status"] == "done" and len(st["trials"]) == 5 and st["best_params"] and st["summary"]["reading"]
    assert all(0.01 <= t["params"]["C"] <= 5 for t in st["trials"]) and st["space"][0]["low"] == 0.01
    assert c.post(f"/api/v1/ml/studies/{st['id']}/stop", headers=h).status_code == 409  # ya terminó
    lst = c.get("/api/v1/ml/studies", params={"dataset_id": str(did)}, headers=h).json()
    assert [x["id"] for x in lst] == [st["id"]] and "trials" not in lst[0] and lst[0]["n_done"] == 5
    algos = {a["key"]: a for a in c.get("/api/v1/ml/algorithms", headers=h).json()}
    assert algos["logreg"]["limits"]["C"] == {"low": 1e-5, "high": 100.0}


def test_stop_request_ends_the_study_early(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    path = tmp_path / "ds.csv.gz"
    synthetic(rows=300).to_csv(path, index=False, compression="gzip")
    did = uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="sintético", status="ready", file_path=str(path), params={},
                         stats={"by_split": {"desarrollo": {"snapshots": 14}}}, sources=[], tags=[]))  # fmt: skip
        db.commit()
    h = login(c, "analista@radar.local")
    r = c.post("/api/v1/ml/studies", json={"dataset_id": str(did), "algorithm": "logreg", "n_trials": 200, "sampler": "random"}, headers=h)
    sid = r.json()["study_id"]
    deadline = time.time() + 60
    while c.get(f"/api/v1/ml/studies/{sid}", headers=h).json()["n_done"] < 1 and time.time() < deadline:
        time.sleep(0.2)
    assert c.post(f"/api/v1/ml/studies/{sid}/stop", headers=h).status_code == 200
    wait_job(c, h, r.json()["job_id"], timeout=120)
    st = c.get(f"/api/v1/ml/studies/{sid}", headers=h).json()
    assert st["status"] == "stopped" and 1 <= len(st["trials"]) < 200 and st["summary"]["n_trials"] == len(st["trials"])


def test_training_accepts_a_custom_space(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    path = tmp_path / "ds.csv.gz"
    synthetic(rows=150).to_csv(path, index=False, compression="gzip")
    did = uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="sintético", status="ready", file_path=str(path), params={"horizon_days": 90},
                         stats={"by_split": {"desarrollo": {"snapshots": 14}}}, sources=[], tags=[]))  # fmt: skip
        db.commit()
    h = login(c, "analista@radar.local")
    body = {"dataset_id": str(did), "algorithm": "logreg", "n_trials": 2, "space": {"C": {"low": 0.05, "high": 0.2}}}
    assert c.post("/api/v1/ml/models", json=body | {"space": {"C": {"low": 0, "high": 1}}}, headers=h).status_code == 422
    r = c.post("/api/v1/ml/models", json=body, headers=h)
    assert r.status_code == 202, r.text
    assert wait_job(c, h, r.json()["job_id"], timeout=120)["status"] == "done"
    mod = c.get(f"/api/v1/ml/models/{r.json()['model_id']}", headers=h).json()
    assert mod["name"].endswith("espacio propio") and mod["config"]["space"][0]["high"] == 0.2
    assert all(0.05 <= t["params"]["C"] <= 0.2 for t in mod["trials"])
