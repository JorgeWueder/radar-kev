import gzip
from datetime import date, timedelta

import pandas as pd
import pytest

from app.services import feeds, universe
from app.services.universe import prospective
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env, seeded

AS_OF = date(2026, 8, 21)
UNTIL = date(2026, 11, 19)


def universe_frame(n: int = 2000, positives: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Universo sintético: los futuros KEV tienen EPSS alto (salvo 5 que se le escapan), el resto bajo; más 3 CVE que ya
    estaban en KEV y 2 que entran a KEV sin EPSS (publicados después)."""
    rows = [(f"CVE-2026-{i:05d}", 0.001 + (i % 50) / 10_000) for i in range(n)]
    fut = [(f"CVE-2025-{i:05d}", 0.6 if i < positives - 5 else 0.002) for i in range(positives)]
    old = [(f"CVE-2021-{i:05d}", 0.97) for i in range(3)]
    epss = pd.DataFrame(rows + fut + old, columns=["cve", "epss"])
    kev = pd.DataFrame(
        [(c, AS_OF + timedelta(days=10)) for c, _ in fut]
        + [(c, AS_OF - timedelta(days=400)) for c, _ in old]
        + [("CVE-2026-99998", AS_OF + timedelta(days=5)), ("CVE-2026-99999", AS_OF + timedelta(days=6))],
        columns=["cve", "date_added"],
    )
    return epss, kev


def test_prospective_excludes_known_kev_and_measures_future_entries() -> None:
    epss, kev = universe_frame()
    r = prospective(epss, kev, AS_OF, UNTIL)
    assert r["n"] == 2025 and r["excluded_known"] == 3 and r["positives"] == 25 and r["not_scored"] == 2
    assert r["auc"] > 0.75 and r["auc_ci"][0] <= r["auc"] <= r["auc_ci"][1]
    top1 = next(x for x in r["effort"] if x["share_pct"] == 1)
    assert top1["cves"] == 21 and top1["captured"] == 20 and top1["coverage_pct"] == 80.0 and top1["lift"] == 80.0
    rule10 = next(x for x in r["rules"] if x["threshold_pct"] == 10)
    assert rule10["marked"] == 20 and rule10["coverage_pct"] == 80.0  # los 3 conocidos (0,97) no cuentan
    text = " ".join(r["interpretation"])
    assert "2 025 CVE" in text and "80 veces" in text and "Prueba prospectiva" in text and "se publicaron después" in text
    assert "el 1,235 % del universo" in text  # 25 de 2025; la coma decimal se conserva


def test_curves_are_sampled_monotonic_and_keep_every_captured_positive() -> None:
    epss, kev = universe_frame(n=20_000)
    r = prospective(epss, kev, AS_OF, UNTIL)
    assert len(r["roc"]) <= universe.MAX_POINTS + 30 and r["roc"][0] == {"fpr": 0.0, "tpr": 0.0}
    tprs = [p["tpr"] for p in r["roc"]]
    assert tprs == sorted(tprs) and tprs[-1] == 1.0
    assert 0 < r["ap"] <= 1 and r["share_below_1pct"] > 90


def test_prospective_without_new_entries() -> None:
    epss, kev = universe_frame()
    r = prospective(epss, kev, UNTIL, UNTIL + timedelta(days=1))
    assert r["auc"] is None and "nada que anticipar" in r["interpretation"][0]


def _csv(epss: pd.DataFrame, day: date) -> bytes:
    body = epss.assign(percentile=0.5).to_csv(index=False)
    return gzip.compress(f"#model_version:v2025.03.14,score_date:{day.isoformat()}T00:00:00Z\n{body}".encode())


def test_compute_endpoint_falls_back_to_previous_day_caches_and_checks_permissions(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)
    epss, _ = universe_frame()
    asked: list[str] = []

    def fake(day: str) -> bytes | None:  # el día objetivo no existe; el anterior sí
        asked.append(day)
        return None if len(asked) == 1 else _csv(epss, date.fromisoformat(day))

    monkeypatch.setattr(feeds, "fetch_epss_csv_for", fake)
    assert c.get("/api/v1/dashboard/evaluation/universe", headers=login(c, "gerencia@radar.local")).json() is None
    assert c.post("/api/v1/dashboard/evaluation/universe", headers=login(c, "gerencia@radar.local")).status_code == 403
    assert c.post("/api/v1/dashboard/evaluation/universe", params={"horizon": 45}, headers=login(c, "analista@radar.local")).status_code == 422
    r = c.post("/api/v1/dashboard/evaluation/universe", params={"horizon": 30}, headers=login(c, "analista@radar.local"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(asked) == 2 and d["as_of"] == asked[1] and d["model_version"] == "v2025.03.14" and d["n"] > 2000
    cached = c.get("/api/v1/dashboard/evaluation/universe", headers=login(c, "gerencia@radar.local")).json()
    assert cached["as_of"] == d["as_of"] and cached["computed_at"]


def test_compute_reports_unavailable_source_as_502(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    seeded(c, m)

    def down(day: str) -> bytes | None:
        raise RuntimeError("Fuente no disponible tras 3 intentos")

    monkeypatch.setattr(feeds, "fetch_epss_csv_for", down)
    r = c.post("/api/v1/dashboard/evaluation/universe", headers=login(c, "admin@radar.local"))
    assert r.status_code == 502 and "no disponible" in r.json()["detail"]


def test_universe_report_needs_a_saved_result_and_criteria_report_points_to_it(env: Env) -> None:  # noqa: F811
    import io

    from docx import Document
    from openpyxl import load_workbook

    from app.models.intel import UniverseEvaluation
    from tests.test_reports import get, pdf_text

    c, m = env
    seeded(c, m)
    r = c.post("/api/v1/reports/epss_universe", params={"fmt": "pdf"}, headers=login(c, "analista@radar.local"))
    assert r.status_code == 422 and "Calcular" in r.json()["detail"]
    assert "calcule la prueba sobre todo el universo" in pdf_text(get(c, "analista@radar.local", "criteria_evaluation", "pdf").content)

    epss, kev = universe_frame()
    with m() as db:
        db.add(UniverseEvaluation(as_of=AS_OF, until=UNTIL, horizon_days=90, model_version="v2026.06.15",
                                  result=prospective(epss, kev, AS_OF, UNTIL) | {"how_to_read": {"effort": "texto viejo"}}))  # fmt: skip
        db.commit()
    crit = " ".join(pdf_text(get(c, "analista@radar.local", "criteria_evaluation", "pdf").content).split())
    assert "anticipó las nuevas entradas a KEV con AUC" in crit and "«Prueba prospectiva de EPSS»" in crit
    text = pdf_text(get(c, "analista@radar.local", "epss_universe", "pdf").content)
    for part in ("Prueba prospectiva de EPSS", "EPSS del 21/08/2026", "modelo EPSS v2026.06.15", "Esfuerzo frente a cobertura",
                 "Reglas por umbral de EPSS", "Curva ROC (AUC", "Lectura de los resultados", "Veces mejor que el azar"):  # fmt: skip
        assert part in text, part
    assert "texto viejo" not in text  # «Cómo leerla» sale del código, no del resultado guardado
    assert len(Document(io.BytesIO(get(c, "analista@radar.local", "epss_universe", "docx").content)).inline_shapes) == 1
    wb = load_workbook(io.BytesIO(get(c, "analista@radar.local", "epss_universe", "xlsx").content))
    assert "Esfuerzo frente a cobertura" in wb.sheetnames and wb["Gráfico"]._charts
