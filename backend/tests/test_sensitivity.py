from datetime import date

import pandas as pd
import pytest

from app.services.descriptive import COLUMNS
from app.services.scoring import ScoringParams, risk_score
from app.services.sensitivity import WEIGHTS, _sample, run, scores
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env, seeded

P = ScoringParams()
TODAY = date(2026, 11, 19)


def frame() -> pd.DataFrame:
    rows = []
    for i in range(24):
        kev = i % 3 == 0
        rows.append((f"CVE-2024-{i:04d}", 4.0 + (i % 7) * 0.9 if i % 5 else None, 0.0, 1 + i % 4, "prod", kev,
                     (i * 4.1) % 100 if i % 6 else None, f"a{i % 8}", False, TODAY, ((i * 0.037) % 1), kev and i % 2 == 0))  # fmt: skip
    return pd.DataFrame(rows, columns=COLUMNS)


def test_vectorized_scores_match_the_real_formula() -> None:
    df = frame()
    w = {k: float(getattr(P, k)) for k in WEIGHTS}
    full, nokev = scores(df, w, P)
    for i, r in enumerate(df.itertuples(index=False)):
        expected = risk_score(P, in_kev=r.in_kev, epss=None if pd.isna(r.epss) else r.epss / 100,
                              percentile=r.percentile, cvss=None if pd.isna(r.cvss) else r.cvss,
                              criticality=r.criticality, ransomware=r.ransomware)  # fmt: skip
        assert full[i] == pytest.approx(expected, abs=0.01), r.cve_id
        assert nokev[i] == pytest.approx(risk_score(P, in_kev=False, epss=None if pd.isna(r.epss) else r.epss / 100,
                                                    percentile=r.percentile, cvss=None if pd.isna(r.cvss) else r.cvss,
                                                    criticality=r.criticality), abs=0.01)  # fmt: skip


def test_samples_sum_to_one_respect_bounds_and_are_reproducible() -> None:
    bounds = {"w_epss": (0.2, 0.6), "w_percentile": (0.0, 0.3), "w_cvss": (0.1, 0.5), "w_asset": (0.0, 0.4)}
    a = _sample(150, 3, bounds)
    assert a == _sample(150, 3, bounds) and a != _sample(150, 4, bounds) and len(a) == 150
    for w in a:
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)
        assert ScoringParams(**w)  # se puede guardar tal cual en la configuración
        assert all(bounds[k][0] - 0.002 <= w[k] <= bounds[k][1] + 0.002 for k in WEIGHTS)
    with pytest.raises(ValueError, match="ninguna combinación suma 1"):
        _sample(10, 1, {k: (0.5, 1.0) for k in WEIGHTS})


def test_run_compares_against_the_current_config() -> None:
    r = run(frame(), P, n_trials=120, seed=7)
    cur = r["current"]
    assert cur["current"] and cur["spearman"] == 1.0 and cur["top_overlap"] == 10 and cur["band_changes"] == 0
    assert len(r["trials"]) == 121 and all(0 <= t["top_overlap"] <= 10 for t in r["trials"])
    assert sum(x["pct"] for x in r["importance"]) == pytest.approx(100, abs=0.5) and len(r["importance"]) == 4
    assert all(b["top_overlap"] >= 8 for b in r["best"])
    text = " ".join(r["interpretation"])
    assert "Se probaron 120 combinaciones de pesos sobre 24 hallazgos" in text and "orientativo" in text


def test_run_with_too_few_findings() -> None:
    r = run(frame().head(2), P)
    assert r["trials"] == [] and "al menos 3" in r["interpretation"][0]


def test_sensitivity_endpoint_permissions_and_validation(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    url = "/api/v1/settings/scoring/sensitivity"
    assert c.post(url, json={}).status_code == 401
    assert c.post(url, json={}, headers=login(c, "gerencia@radar.local")).status_code == 403
    assert c.post(url, json={"n_trials": 5}, headers=login(c, "auditor@radar.local")).status_code == 422
    assert c.post(url, json={"bounds": {"w_otro": [0, 1]}}, headers=login(c, "auditor@radar.local")).status_code == 422
    r = c.post(url, json={"n_trials": 50, "seed": 1}, headers=login(c, "auditor@radar.local"))
    assert r.status_code == 200, r.text
    assert r.json()["config"]["n_trials"] == 50
