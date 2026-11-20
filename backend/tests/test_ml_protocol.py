"""Protocolo de la Fase 2/3: embargo temporal, pliegues purgados, parada anticipada del boosting y estadística de comparación."""

import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.ml import algorithms as algs
from app.ml import assess, dataset, training
from app.models.ml import MlDataset
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_dataset import wait_job
from tests.test_ml_training import synthetic
from tests.test_reports import Env

H = 90


def months(start: date, n: int) -> list[date]:
    out, d = [], start
    for _ in range(n):
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def test_embargoed_split_never_lets_a_label_window_cross_a_boundary() -> None:
    shots = months(date(2023, 4, 1), 41)
    sp = dataset.embargoed_split(shots, H)
    blocks = {k: [s for s in shots if sp[s] == k] for k in ("desarrollo", "validacion", "prueba", "excluida")}
    assert [len(blocks[k]) for k in ("desarrollo", "validacion", "prueba", "excluida")] == [
        25,
        6,
        6,
        4,
    ]  # coincide con f2_layout.json
    assert max(blocks["desarrollo"]) + timedelta(days=H) <= min(blocks["validacion"])
    assert max(blocks["validacion"]) + timedelta(days=H) <= min(blocks["prueba"])
    # orden cronológico estricto entre bloques
    assert (
        max(blocks["desarrollo"])
        < min(blocks["validacion"])
        < max(blocks["validacion"])
        < min(blocks["prueba"])
    )
    # las excluidas son exactamente las que cruzan
    for s in blocks["excluida"]:
        nxt = min(b for k in ("validacion", "prueba") for b in blocks[k] if b > s)
        assert s + timedelta(days=H) > nxt


def test_embargoed_split_needs_enough_snapshots() -> None:
    with pytest.raises(ValueError, match="al menos 6"):
        dataset.embargoed_split(months(date(2025, 1, 1), 5), H)
    with pytest.raises(ValueError, match="No quedan"):
        dataset.embargoed_split(months(date(2025, 1, 1), 6), H)


def test_embargo_folds_exclude_snapshots_whose_label_reaches_the_validation_block() -> None:
    dev = months(date(2023, 4, 1), 25)
    folds = training.embargo_folds(dev, 4, 3, H)
    assert len(folds) == 4 and all(len(va) == 3 for _, va in folds)
    for tr, va in folds:
        assert max(tr) + timedelta(days=H) <= min(va)
    assert [len(tr) for tr, _ in folds] == [
        11,
        14,
        17,
        20,
    ]  # mismos números que f2_layout.json (4 pliegues de 3 fotos)
    assert training.feasible_embargo(dev, 4, 2, 3, 2, H) is None
    # con las 10 fotos de desarrollo del dataset antiguo el diseño no cabe y el motivo lo dice
    assert training.feasible_embargo(months(date(2025, 1, 1), 10), 4, 2, 3, 2, H) is not None


def test_train_with_embargo_runs_and_never_trains_across_the_boundary() -> None:
    df = synthetic(n_snaps=41, rows=120)
    sp = dataset.embargoed_split(sorted(df["snapshot"].unique()), H)
    df = df[df["snapshot"].map(sp) != "excluida"].assign(split=lambda d: d["snapshot"].map(sp))
    res = training.train(df, "logreg", 2, 4, 2, 1, lambda m, e: None, v_out=3, v_in=2, horizon=H)
    assert len(res["folds"]) == 4 and not res["aggregate"]["skipped_folds"]
    first = res["folds"][0]
    assert date.fromisoformat(first["train"][1]) + timedelta(days=H) <= date.fromisoformat(first["val"][0])
    assert set(res["preds"]["split"]) == {"validacion", "prueba"}


def test_hgb_temporal_early_stopping_picks_the_number_of_trees() -> None:
    df = synthetic(n_snaps=12, rows=400)
    dev = df[df["split"] == "desarrollo"]
    test = df[df["split"] == "prueba"]
    params = algs.defaults("hgb")
    assert (
        "max_iter" not in params and "class_weight" not in params
    )  # D3: sin class_weight; la parada decide los árboles
    model, s = training.fit_predict("hgb", params, 1, dev, test, horizon=H)
    assert 1 <= model.best_iter_ <= algs.FIXED["hgb"]["max_iter_cap"] and len(s) == len(test)
    fixed, _ = training.fit_predict("hgb", {**params, "max_iter": 7}, 1, dev, test)
    assert fixed.best_iter_ == 7  # un max_iter fijo (modelos heredados) no se toca


def test_new_search_spaces_have_no_class_weight_and_few_parameters() -> None:
    for algo, space in algs.SPACES.items():
        names = {p["name"] for p in space}
        assert "class_weight" not in names and len(names) <= 4, algo
    assert {p["name"]: p["high"] for p in algs.SPACES["logreg"]}["C"] == 1.0
    sp = {p["name"]: p for p in algs.custom_space("hgb", {"min_samples_leaf": {"low": 30, "high": 300}})}
    assert sp["min_samples_leaf"]["log"] is True and sp["min_samples_leaf"]["low"] == 30


def test_version_group_ablation_neutralises_epss_model_and_delta() -> None:
    df = synthetic(n_snaps=8, rows=50)
    x = algs.prepare(df, ("epss_version",))
    assert (x["epss_model"] == "desconocido").all() and (x["epss_delta"] == 0.0).all()
    assert x["epss"].nunique() > 1  # la probabilidad en sí no se toca


def test_holm_matches_the_textbook_example() -> None:
    assert assess.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    assert assess.holm([0.5]) == [0.5]


def test_wilcoxon_with_four_folds_can_never_reach_five_percent() -> None:
    r = assess.wilcoxon_paired([0.4, 0.5, 0.6, 0.7], [0.1, 0.1, 0.1, 0.1])
    assert r["min_possible_p"] == 0.125 and r["p"] >= 0.125


def test_cluster_bootstrap_resamples_whole_cves_and_detects_a_real_difference() -> None:
    rng = np.random.default_rng(0)
    n_cve = 400
    cve = np.repeat(np.arange(n_cve), 3)  # cada CVE en 3 fotos
    y = np.repeat((rng.random(n_cve) < 0.08).astype(int), 3)  # el evento se repite en las 3 filas
    w = np.where(y == 1, 1.0, 5.0)
    good = y + rng.normal(0, 0.3, len(y))
    noise = rng.normal(0, 1, len(y))
    r = assess.bootstrap_diff_cluster(y, w, good, noise, cve, n=200)
    assert r["clusters"] == n_cve and r["pr_auc"]["ci"][0] > 0 and r["pr_auc"]["diff"] > 0
    same = assess.bootstrap_diff_cluster(y, w, good, good, cve, n=100)
    assert same["pr_auc"]["diff"] == 0 and same["pr_auc"]["p"] == 1.0
    blocks = assess.bootstrap_diff_cluster(y, w, good, noise, np.arange(len(y)) // 30, n=100, stratify=False)
    assert blocks["n_boot"] > 0


def test_lift_and_relative_brier() -> None:
    y = np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 0] * 10)
    s = np.where(y == 1, 0.9, 0.1)
    w = np.ones(len(y))
    assert (
        assess.lift_at(y, s, w, 0.1) == 10.0
    )  # el 10 % superior son todos positivos: prevalencia 10 % -> lift 10
    b = assess.brier_relative(y, s, w)
    assert b["ratio"] < 0.2
    flat = assess.brier_relative(y, np.full(len(y), 0.1), w)
    assert abs(flat["ratio"] - 1.0) < 1e-6


def test_experiment_runner_writes_traceable_results_and_is_reproducible(tmp_path: Path) -> None:
    from app.ml import experiment

    df = synthetic(n_snaps=41, rows=100)
    sp = dataset.embargoed_split(sorted(df["snapshot"].unique()), H)
    df = df[df["snapshot"].map(sp) != "excluida"].assign(split=lambda d: d["snapshot"].map(sp))
    src = tmp_path / "ds.csv.gz"
    df.to_csv(src, index=False, compression="gzip")
    cfg = {
        "name": "exp",
        "dataset_path": str(src),
        "algorithm": "logreg",
        "out_dir": str(tmp_path / "out"),
        "n_trials": 2,
        "seed": 3,
    }
    a = experiment.run(cfg)
    b = experiment.run(cfg | {"name": "exp2"})
    assert (tmp_path / "out" / "exp.json").exists() and (tmp_path / "out" / "exp.preds.csv.gz").exists()
    assert (
        a["dataset"]["sha256"] == b["dataset"]["sha256"] and a["preds_sha256"] == b["preds_sha256"]
    )  # misma semilla, mismas predicciones
    assert a["best_params"] == b["best_params"] and a["environment"]["sklearn"]
    assert a["dataset"]["splits"]["prueba"]["events"] > 0
    with pytest.raises(ValueError, match="Faltan"):
        experiment.validate({"name": "x"})
    with pytest.raises(ValueError, match="ablación"):
        experiment.validate(cfg | {"drop": ["nada"]})


def test_calibrator_comparison_prefers_platt_without_enough_events_and_reports_drift() -> None:
    from app.ml import inference

    rng = np.random.default_rng(1)
    parts = []
    for i, sp in enumerate(["validacion"] * 6 + ["prueba"] * 3):
        n = 800
        score = rng.beta(0.5, 12, n)
        y = (rng.random(n) < np.clip(score * (0.5 if sp == "prueba" else 1.0), 0, 1)).astype(
            int
        )  # la prueba está desplazada
        parts.append(
            pd.DataFrame(
                {
                    "snapshot": date(2026, 1 + i, 1),
                    "cve": [f"C{i}-{j}" for j in range(n)],
                    "split": sp,
                    "label": y,
                    "weight": np.where(y == 1, 1.0, 5.0),
                    "score": score,
                }
            )
        )
    r = inference.compare_calibrators(pd.concat(parts, ignore_index=True))
    assert (
        set(r["test"]) == {"platt", "isotonic", "raw"}
        and r["drift"]["recalibrated_with_recent"]["oe"] is not None
    )
    assert r["validation_events"] < inference.MIN_EVENTS_ISOTONIC or r["choice"] in ("platt", "isotonic")
    few = pd.concat(parts, ignore_index=True)
    few.loc[few["split"] == "validacion", "label"] = 0
    few.loc[few.index[:4], "label"] = 1  # solo 4 eventos: no alcanza
    with pytest.raises(ValueError, match="al menos 5"):
        inference.compare_calibrators(few)


def test_snapshot_frame_used_by_tests_is_dataframe() -> None:
    assert isinstance(synthetic(n_snaps=6, rows=10), pd.DataFrame)


def test_train_endpoint_with_embargo_protocol_rejects_duplicates_and_infeasible_designs(
    env: Env,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    df = synthetic(n_snaps=41, rows=100)
    sp = dataset.embargoed_split(sorted(df["snapshot"].unique()), H)
    df = df[df["snapshot"].map(sp) != "excluida"].assign(split=lambda d: d["snapshot"].map(sp))
    path = tmp_path / "ds.csv.gz"
    df.to_csv(path, index=False, compression="gzip")
    snaps = {
        k: [d.isoformat() for d, v in sp.items() if v == k]
        for k in ("desarrollo", "validacion", "prueba", "excluida")
    }
    did, short = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="con embargo", status="ready", file_path=str(path), sources=[], tags=[],
                         params={"horizon_days": 90, "embargo": True}, stats={"by_split": {"desarrollo": {"snapshots": 25}}, "split_snapshots": snaps}))  # fmt: skip
        db.add(MlDataset(id=short, name="corto", status="ready", file_path=str(path), sources=[], tags=[], params={"horizon_days": 90, "embargo": True},
                         stats={"by_split": {"desarrollo": {"snapshots": 10}}, "split_snapshots": {"desarrollo": snaps["desarrollo"][:10]}}))  # fmt: skip
        db.commit()
    h = login(c, "analista@radar.local")
    body = {"dataset_id": str(did), "algorithm": "logreg", "n_trials": 2, "drop": ["epss_version"]}
    bad = c.post("/api/v1/ml/models", json=body | {"dataset_id": str(short)}, headers=h)
    assert bad.status_code == 422 and "no caben" in bad.json()["detail"]
    r = c.post("/api/v1/ml/models", json=body, headers=h)
    assert r.status_code == 202, r.text
    assert wait_job(c, h, r.json()["job_id"], timeout=180)["status"] == "done"
    mod = c.get(f"/api/v1/ml/models/{r.json()['model_id']}", headers=h).json()
    assert mod["status"] == "ready" and len(mod["folds"]) == 4 and mod["config"]["embargo_days"] == 90
    assert (mod["config"]["k_out"], mod["config"]["k_in"], mod["config"]["v_out"], mod["config"]["v_in"]) == (
        4,
        2,
        3,
        2,
    )
    dup = c.post("/api/v1/ml/models", json=body, headers=h)
    assert dup.status_code == 409 and "misma configuración" in dup.json()["detail"]
    other = c.post("/api/v1/ml/models", json=body | {"seed": 8}, headers=h)  # otra semilla sí se permite
    assert other.status_code == 202
    assert wait_job(c, h, other.json()["job_id"], timeout=180)["status"] == "done"


def test_missing_epss_day_answered_with_403_falls_back_to_the_previous_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.ml import sources

    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "epss_csv_dated_url", "https://epss.test/epss_scores-{date}.csv.gz")
    real = httpx.Client

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403) if "2024-12-01" in str(req.url) else httpx.Response(200, content=b"x")

    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    path, day, _ = sources.epss_for(date(2024, 12, 1))
    assert day == date(2024, 11, 30) and path.name == "epss_2024-11-30.csv.gz"
