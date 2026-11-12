import pytest

from app.services.inference import mann_kendall, mann_whitney, two_proportions, wilson


def test_mann_whitney_detects_clear_shift() -> None:
    fast = [2, 3, 3, 4, 5, 4, 3, 2, 4, 5]
    slow = [12, 15, 14, 18, 16, 13, 17, 19, 15, 14]
    r = mann_whitney(fast, slow)
    assert r["verdict"] == "diferencia" and r["p_value"] < 0.001 and r["effect"] > 0.9
    assert "más lento" in r["interpretation"]


def test_mann_whitney_same_distribution_is_not_significant() -> None:
    a = [3, 5, 7, 9, 11, 4, 6, 8, 10, 12]
    r = mann_whitney(a, [x + 0.5 for x in reversed(a)])
    assert r["verdict"] == "sin_diferencia"


def test_small_samples_are_flagged_and_empty_is_handled() -> None:
    r = mann_whitney([1, 2, 3], [20, 21, 22])
    assert r["verdict"] in ("diferencia_debil", "sin_diferencia") and "pocos casos" in r["interpretation"]
    assert mann_whitney([], [1])["verdict"] == "sin_datos"


def test_two_proportions() -> None:
    r = two_proportions(30, 100, 70, 100)
    assert r["verdict"] == "diferencia" and "mejoró" in r["interpretation"]
    assert two_proportions(50, 100, 52, 100)["verdict"] == "sin_diferencia"
    assert two_proportions(0, 0, 3, 5)["verdict"] == "sin_datos"
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi and pytest.approx(0.2366, abs=0.01) == lo


def test_mann_kendall() -> None:
    up = mann_kendall([1, 2, 2, 3, 4, 5, 5, 6, 8, 9])
    assert up["trend"] == "sube" and up["slope_per_day"] > 0
    assert mann_kendall([5, 1, 6, 2, 5, 3, 6, 2, 5, 4])["trend"] == "sin_tendencia"
    assert mann_kendall([1, 2])["trend"] == "sin_datos"
    assert mann_kendall([4] * 8)["trend"] == "sin_tendencia"
