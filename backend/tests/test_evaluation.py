from datetime import date

import pandas as pd
import pytest

from app.services.descriptive import COLUMNS
from app.services.evaluation import auc, auc_ci, confusion, curves, cve_frame, evaluate
from app.services.scoring import ScoringParams, risk_score
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env, seeded

P = ScoringParams()
TODAY = date(2026, 11, 19)


def row(cve: str, cvss: float | None, epss: float | None, kev: bool, crit: int = 3, asset: str = "a1") -> tuple[object, ...]:
    return (cve, cvss, 50.0, crit, "prod", kev, epss, asset, False, TODAY, 0.5)


def test_auc_perfect_inverse_and_ties() -> None:
    assert auc([0.9, 0.8, 0.3, 0.1], [True, True, False, False]) == 1.0
    assert auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert auc([1.0, 1.0], [True, False]) == 0.5
    assert auc([1.0, 2.0], [True, True]) is None
    lo1, hi1 = auc_ci(1.0, 5, 5)  # AUC perfecto con pocos casos: el intervalo no puede tener ancho 0
    assert hi1 == 1.0 and 0.9 < lo1 < 1.0
    assert auc_ci(1.0, 50, 50)[0] > lo1  # más casos, intervalo más estrecho
    lo, hi = auc_ci(0.75, 10, 10)
    assert lo < 0.75 < hi <= 1.0


def test_curves_group_ties_and_average_precision() -> None:
    roc, pr, ap = curves([3, 2, 2, 1], [True, False, True, False])
    assert roc[0] == {"fpr": 0.0, "tpr": 0.0}
    assert [(p["fpr"], p["tpr"]) for p in roc[1:]] == [(0.0, 0.5), (0.5, 1.0), (1.0, 1.0)]
    assert [p["precision"] for p in pr] == [1.0, 0.6667, 0.5]
    assert ap == pytest.approx(0.5 * 1 + 0.5 * 2 / 3, abs=1e-3)


def test_confusion_rule() -> None:
    c = confusion([3, 2, 2, 1], [True, False, True, False], 2)
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (2, 1, 0, 1)
    assert c["coverage"] == 100.0 and c["efficiency"] == 66.7 and c["effort"] == 75.0


def test_cve_frame_counts_each_cve_once_and_matches_the_real_score_without_kev() -> None:
    df = pd.DataFrame([row("CVE-A", 9.8, 50.0, True, 2, "a1"), row("CVE-A", 9.8, 50.0, True, 4, "a2"), row("CVE-B", None, None, False)],
                      columns=COLUMNS)  # fmt: skip
    c = cve_frame(df, P).set_index("cve_id")
    assert len(c) == 2 and c.loc["CVE-B", "cvss"] == 0.0  # el dato ausente cuenta 0, como en el score
    expected = risk_score(P, in_kev=False, epss=0.5, percentile=0.5, cvss=9.8, criticality=4)  # el activo más crítico
    assert c.loc["CVE-A", "base"] == pytest.approx(expected, abs=0.01)


def test_evaluate_shows_epss_beating_cvss_and_never_uses_the_full_score() -> None:
    kev = [row(f"CVE-K{i}", 6.5 + (i % 3) * 0.5, 60.0 + i * 5, True) for i in range(6)]
    rest = [row(f"CVE-N{i}", 7.0 + (i % 3) * 0.6, 0.1 * (i + 1), False) for i in range(6)]
    r = evaluate(pd.DataFrame(kev + rest, columns=COLUMNS), P)
    assert r["n"] == 12 and r["positives"] == 6 and r["reliable"] and r["prevalence"] == 50.0
    by = {p["key"]: p for p in r["predictors"]}
    assert set(by) == {"cvss", "epss", "base"}  # el score completo incluye KEV: no se evalúa
    assert by["epss"]["auc"] == 1.0 and by["cvss"]["auc"] < 0.5
    text = " ".join(r["interpretation"])
    assert "supera a CVSS" in text and "no es del todo" in text and "~5 %" in text
    rules = {x["key"]: x for x in r["rules"]}
    assert rules["epss_10"]["coverage"] == 100.0 and rules["epss_10"]["effort"] == 50.0
    assert rules["cvss_7"]["fp"] == 6


def test_evaluate_without_both_classes_or_data() -> None:
    only = evaluate(pd.DataFrame([row("CVE-1", 9.0, 5.0, True)], columns=COLUMNS), P)
    assert only["predictors"] == [] and "todos" in only["interpretation"][0]
    empty = evaluate(pd.DataFrame([], columns=COLUMNS), P)
    assert empty["n"] == 0 and "nada que evaluar" in empty["interpretation"][0]
    small = evaluate(pd.DataFrame([row("CVE-1", 9.0, 50.0, True), row("CVE-2", 5.0, 1.0, False)], columns=COLUMNS), P)
    assert not small["reliable"] and "orientativos" in small["interpretation"][-1]


def test_evaluation_endpoint_and_rbac(env: Env) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    r = c.get("/api/v1/dashboard/evaluation", headers=login(c, "gerencia@radar.local"))
    assert r.status_code == 200
    d = r.json()
    assert d["n"] >= 1 and "how_to_read" in d
    assert c.get("/api/v1/dashboard/evaluation").status_code == 401
