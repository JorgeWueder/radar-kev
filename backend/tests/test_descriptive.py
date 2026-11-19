import pandas as pd
import pytest

from app.services.descriptive import distribution, profile, summarize
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env, seeded


def frame() -> pd.DataFrame:
    rows = [
        # cve, cvss, score, criticidad, entorno, kev, epss (%)
        ("CVE-1", 9.8, 98.0, 4, "prod", True, 94.0),
        ("CVE-2", 9.1, 92.0, 4, "prod", True, 60.0),
        ("CVE-3", 7.5, 35.0, 3, "prod", False, 0.4),
        ("CVE-4", 9.8, 30.0, 2, "staging", False, 0.2),
        ("CVE-5", 5.3, 12.0, 2, "dev", False, 0.1),
        ("CVE-6", None, 8.0, 1, "dev", False, None),
    ]
    return pd.DataFrame(rows, columns=["cve_id", "cvss", "risk_score", "criticality", "environment", "in_kev", "epss"])


def test_summarize_matches_pandas_and_counts_missing() -> None:
    s = frame()["epss"]
    st = summarize(s)
    assert st["n"] == 5 and st["missing"] == 1
    assert st["median"] == pytest.approx(0.4) and st["max"] == 94.0 and st["mean"] == pytest.approx(s.mean(), abs=0.01)
    assert st["p25"] <= st["median"] <= st["p75"] <= st["p90"] <= st["max"]
    empty = summarize(pd.Series([None, None], dtype=float))
    assert empty["n"] == 0 and empty["median"] is None


def test_distribution_bins_cover_every_value_including_the_top_edge() -> None:
    s = pd.Series([0.0, 9.99, 10.0, 55.0, 100.0])
    d = distribution(s, [0, 10, 50, 100])
    assert [b["count"] for b in d] == [2, 1, 2] and sum(b["count"] for b in d) == len(s)
    assert d[0]["label"] == "0 a 10"


def test_profile_explains_skew_groups_and_kev_vs_rest() -> None:
    p = profile(frame())
    assert p["n"] == 6 and p["kev"] == 2 and "33 %" in p["interpretation"][0]
    epss = next(v for v in p["variables"] if v["key"] == "epss")
    text = " ".join(epss["interpretation"])
    assert "supera a la mediana" in text  # media muy por encima de la mediana: sesgo a la derecha
    assert "menor a 1 %" in text and "1 de 6" in text and "no se inventa" in text
    cvss = next(v for v in p["variables"] if v["key"] == "cvss")
    assert [b["label"] for b in cvss["distribution"]][-1] == "Crítica (≥ 9)" and cvss["distribution"][-1]["count"] == 3
    crit = p["groups"][0]
    assert [r["label"] for r in crit["rows"]] == ["Crítica", "Alta", "Media", "Baja"]
    assert crit["rows"][0]["kev_pct"] == 100.0 and crit["rows"][0]["median_score"] == 95.0
    assert any("Crítica concentra 2 de los 2" in t for t in crit["interpretation"])
    assert any("orientativas" in t for t in crit["interpretation"])
    kv = p["kev_vs_rest"]
    assert kv["kev_median_epss"] == 77.0 and "misma dirección" in kv["interpretation"][0]


def test_profile_of_empty_inventory() -> None:
    p = profile(frame().iloc[0:0])
    assert p["n"] == 0 and p["variables"] == [] and "nada que describir" in p["interpretation"][0]


def test_descriptive_endpoint_and_rbac(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    r = c.get("/api/v1/dashboard/descriptive", headers=login(c, "gerencia@radar.local"))
    assert r.status_code == 200
    d = r.json()
    assert d["n"] >= 1 and d["kev"] == 1 and {v["key"] for v in d["variables"]} == {"risk_score", "epss", "cvss"}
    for v in d["variables"]:
        assert sum(b["count"] for b in v["distribution"]) == v["summary"]["n"]
    assert c.get("/api/v1/dashboard/descriptive").status_code == 401
