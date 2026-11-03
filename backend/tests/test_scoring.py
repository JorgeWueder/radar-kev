from datetime import date

import pytest
from pydantic import ValidationError

from app.services.feeds import EPSS_BATCH, EPSS_MAX_CHARS, epss_batches
from app.services.scoring import ScoringParams, band_of, risk_score, sla_due, sla_state

P = ScoringParams()


def score(**kw: object) -> float:
    base: dict[str, object] = {"in_kev": True, "epss": 0.5, "percentile": 0.9, "cvss": 7.5, "criticality": 3}
    return risk_score(P, **{**base, **kw})  # type: ignore[arg-type]


def test_formula_matches_hand_calculation() -> None:
    # base = .35*.5 + .15*.9 + .25*.75 + .25*.75 = .175+.135+.1875+.1875 = .685
    assert score(in_kev=False) == pytest.approx(69 * 0.685, abs=0.01)
    assert score() == pytest.approx(70 + 30 * 0.685, abs=0.01)
    assert score(ransomware=True) == pytest.approx(70 + 30 * 0.685 + 5, abs=0.01)


def test_kev_always_outranks_non_kev_even_in_the_extremes() -> None:
    worst_kev = score(epss=0, percentile=0, cvss=0, criticality=1)
    best_non_kev = score(in_kev=False, epss=1, percentile=1, cvss=10, criticality=4)
    assert worst_kev >= P.kev_floor > best_non_kev
    assert score(epss=1, percentile=1, cvss=10, criticality=4, ransomware=True) == 100  # tope


@pytest.mark.parametrize("epss", [0.0, 0.25, 0.5, 1.0])
@pytest.mark.parametrize("crit", [1, 2, 3, 4])
def test_kev_dominance_property_grid(epss: float, crit: int) -> None:
    for cvss in (0, 5, 10):
        assert score(epss=epss, criticality=crit, cvss=cvss) > score(
            in_kev=False, epss=1, percentile=1, cvss=10, criticality=4
        ) - 0.0001 or score(epss=epss, criticality=crit, cvss=cvss) >= P.kev_floor


def test_missing_epss_and_cvss_count_as_zero_not_invented() -> None:
    assert score(in_kev=False, epss=None, percentile=None, cvss=None, criticality=4) == pytest.approx(69 * 0.25, abs=0.01)


def test_bands() -> None:
    assert [band_of(P, s) for s in (95, 85, 84.9, 70, 69.9, 40, 39.9)] == [
        "critical", "critical", "high", "high", "medium", "medium", "low",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [
        {"w_epss": 0.5},  # no suma 1
        {"band_high": 90},  # no es crítico > alto > medio
        {"kev_floor": 120},
        {"w_cvss": -0.1, "w_epss": 0.6},
    ],
)
def test_config_validation(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        ScoringParams(**bad)


def test_config_roundtrip_through_columns() -> None:
    p = ScoringParams(w_epss=0.4, w_percentile=0.1, kev_floor=75)
    assert ScoringParams.from_columns(*p.to_columns()) == p


def test_sla_kev_detected_before_due_date_uses_cisa_due_date() -> None:
    d = sla_due(P, band="critical", detected=date(2026, 10, 30),
                kev_date_added=date(2026, 10, 30), kev_due_date=date(2026, 11, 13))  # fmt: skip
    assert d == date(2026, 11, 13)


def test_sla_kev_detected_after_due_date_gets_same_window_from_detection() -> None:
    # CISA dio 14 días (2021-12-10 → 2021-12-24); detectado hoy: vence a los 14 días, no nace vencido
    d = sla_due(P, band="critical", detected=date(2026, 10, 30),
                kev_date_added=date(2021, 12, 10), kev_due_date=date(2021, 12, 24))  # fmt: skip
    assert d == date(2026, 11, 13)


def test_sla_non_kev_uses_band_days() -> None:
    assert sla_due(P, band="high", detected=date(2026, 1, 1)) == date(2026, 1, 31)
    assert sla_due(P, band="low", detected=date(2026, 1, 1)) == date(2026, 6, 30)


def test_sla_states() -> None:
    today = date(2026, 11, 3)
    assert sla_state(P, date(2026, 11, 2), today) == "vencido"
    assert sla_state(P, date(2026, 11, 3), today) == "por_vencer"
    assert sla_state(P, date(2026, 11, 10), today) == "por_vencer"
    assert sla_state(P, date(2026, 11, 11), today) == "en_plazo"
    assert sla_state(P, date(2026, 11, 2), today, active=False) == "no_aplica"
    assert sla_state(P, None, today) == "no_aplica"


def test_epss_batches_respect_cve_count_and_url_limits() -> None:
    cves = [f"CVE-2024-{n:05d}" for n in range(1, 1000)]
    batches = epss_batches(cves)
    assert sum(len(b) for b in batches) == len(cves)
    assert all(len(b) <= EPSS_BATCH for b in batches)
    assert all(len(",".join(b)) <= EPSS_MAX_CHARS for b in batches)
    long = [f"CVE-2024-{n:012d}" for n in range(200)]  # CVEs largos: manda el límite de caracteres
    assert all(len(",".join(b)) <= EPSS_MAX_CHARS for b in epss_batches(long))
