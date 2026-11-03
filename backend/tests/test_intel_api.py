import gzip
from collections.abc import Iterator
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.inventory import Asset, Vulnerability
from tests.conftest import client_for, isolated_schema, login
from tests.test_correlation import CATALOG, kev_item

KEY = {"X-Service-Key": "test-service-key"}


@pytest.fixture
def env() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    from app.core.ratelimit import limiter
    from app.main import app

    limiter.enabled = False
    with isolated_schema() as m:
        yield client_for(m), m
    app.dependency_overrides.clear()


def add_inventory(m: sessionmaker[Session]) -> None:
    with m() as db:
        a = Asset(hostname="srv-a", criticality=4, environment="prod")
        db.add(a)
        db.flush()
        db.add_all([Vulnerability(asset_id=a.id, cve_id="CVE-2021-44228", cvss_score=10),
                    Vulnerability(asset_id=a.id, cve_id="CVE-2022-0778", cvss_score=7.5)])  # fmt: skip
        db.commit()


def test_service_key_required_and_constant_time(env: tuple[TestClient, Any]) -> None:
    c, _ = env
    assert get_settings().radar_service_key.get_secret_value() == "test-service-key"
    for path in ("/api/v1/internal/inventory/cves",):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"X-Service-Key": "otra"}).status_code == 401
        assert c.get(path, headers=KEY).status_code == 200
    # una sesión de usuario normal no sirve en los endpoints internos
    h = login(c, "admin@radar.local")
    assert c.get("/api/v1/internal/inventory/cves", headers=h).status_code == 401
    assert "/internal" not in str(c.get("/openapi.json").json()["paths"])  # no aparecen en Swagger


def test_full_daily_flow_and_idempotent_second_run(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    add_inventory(m)
    run = c.post("/api/v1/internal/runs/start", headers=KEY, json={"trigger": "cron"}).json()
    rid = run["run_id"]
    assert run["skipped"] is False
    inv = c.get("/api/v1/internal/inventory/cves", headers=KEY).json()
    assert inv["cves"] == ["CVE-2021-44228", "CVE-2022-0778"]

    kev = c.post(f"/api/v1/internal/kev/ingest?run_id={rid}", headers=KEY, json=CATALOG).json()
    assert kev["new_entries"] == 2
    epss = c.post("/api/v1/internal/epss/ingest", headers=KEY, json={"run_id": rid, "items": [
        {"cve": "CVE-2021-44228", "epss": "0.97", "percentile": "0.999"}]}).json()  # fmt: skip
    assert epss["scored"] == 1
    cor = c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": rid}).json()
    assert cor["in_kev"] == 1 and len(cor["new_matches"]) == 1
    assert cor["new_matches"][0]["hostname"] == "srv-a"
    assert c.post(f"/api/v1/internal/runs/{rid}/finish", headers=KEY).json() == {"status": "success"}

    # misma jornada: no se repite la ejecución y, aun forzándola, no hay coincidencias nuevas
    again = c.post("/api/v1/internal/runs/start", headers=KEY, json={"trigger": "cron"}).json()
    assert again["skipped"] is True
    forced = c.post("/api/v1/internal/runs/start", headers=KEY, json={"trigger": "manual", "force": True}).json()
    cor2 = c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": forced["run_id"]}).json()
    assert cor2["new_matches"] == []

    h = login(c, "auditor@radar.local")
    runs = c.get("/api/v1/workflow-runs", headers=h).json()
    assert runs["total"] == 2 and runs["items"][-1]["kev_catalog_version"] == "2026.10.30"
    with m() as db:
        actors = {r.actor for r in db.execute(select(AuditLog).where(AuditLog.module == "workflow")).scalars()}
        assert actors == {"system:n8n"}


def test_invalid_kev_marks_run_failed_flow_with_error_recorded(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    r = c.post(f"/api/v1/internal/kev/ingest?run_id={rid}", headers=KEY, json={"catalogVersion": "x", "vulnerabilities": []})
    assert r.status_code == 422
    c.post(f"/api/v1/internal/runs/{rid}/fail", headers=KEY, json={"node": "HTTP KEV", "message": "timeout"})
    h = login(c, "auditor@radar.local")
    run = c.get("/api/v1/workflow-runs", headers=h).json()["items"][0]
    assert run["status"] == "failed" and [e["node"] for e in run["errors"]] == ["kev_ingest", "HTTP KEV"]
    with m() as db:
        fail = db.execute(select(AuditLog).where(AuditLog.action == "run_fail")).scalar_one()
        assert fail.result == "failure"


@respx.mock
def test_epss_fallback_uses_csv_when_api_is_down(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    add_inventory(m)
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    csv = gzip.compress(
        b"#model_version:v2026.06.15,score_date:2026-11-03T12:00:27Z\ncve,epss,percentile\n"
        b"CVE-2021-44228,0.97,0.999\nCVE-1999-0001,0.04,0.9\n"
    )
    respx.get(get_settings().epss_csv_url).mock(return_value=Response(200, content=csv))
    out = c.post("/api/v1/internal/epss/fallback", headers=KEY, json={"run_id": rid}).json()
    assert out["scored"] == 1 and out["source"] == "csv"
    c.post(f"/api/v1/internal/runs/{rid}/finish", headers=KEY)
    h = login(c, "auditor@radar.local")
    run = c.get("/api/v1/workflow-runs", headers=h).json()["items"][0]
    assert run["status"] == "partial" and run["errors"][0]["node"] == "epss_api"


@respx.mock
def test_epss_fallback_reports_502_when_both_sources_fail(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    from app.services import feeds

    c, _ = env
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    respx.get(get_settings().epss_csv_url).mock(return_value=Response(503))
    feeds.time.sleep = lambda _s: None  # type: ignore[assignment]  # sin esperas en el test
    assert c.post("/api/v1/internal/epss/fallback", headers=KEY, json={"run_id": rid}).status_code == 502


def populate(c: TestClient, m: sessionmaker[Session]) -> None:
    add_inventory(m)
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    c.post("/api/v1/internal/kev/ingest", headers=KEY, json=CATALOG)
    c.post("/api/v1/internal/epss/ingest", headers=KEY, json={"run_id": rid, "items": [
        {"cve": "CVE-2021-44228", "epss": "0.97", "percentile": "0.999"}]})  # fmt: skip
    c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": rid})


def test_kev_catalog_api_filters_detail_and_rbac(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    populate(c, m)
    mgr = login(c, "gerencia@radar.local")  # Gerencia puede ver el catálogo
    lst = c.get("/api/v1/kev", headers=mgr).json()
    assert lst["total"] == 2 and lst["catalog_version"] == "2026.10.30" and lst["in_environment"] == 1
    assert c.get("/api/v1/kev", headers=mgr, params={"in_environment": True}).json()["total"] == 1
    assert c.get("/api/v1/kev", headers=mgr, params={"ransomware": True}).json()["total"] == 1
    assert c.get("/api/v1/kev", headers=mgr, params={"q": "4966"}).json()["items"][0]["cve_id"] == "CVE-2023-4966"
    assert c.get("/api/v1/kev", headers=mgr, params={"sort": "evil; drop"}).status_code == 422
    d = c.get("/api/v1/kev/CVE-2021-44228", headers=mgr).json()
    assert d["epss"] == 0.97 and d["affected"][0]["hostname"] == "srv-a" and d["affected"][0]["risk_score"] == 100.0
    assert c.get("/api/v1/kev/CVE-2022-0778", headers=mgr).status_code == 404
    assert "Apache" in c.get("/api/v1/kev/vendors", headers=mgr).json()
    assert c.get("/api/v1/kev").status_code == 401


def test_vulnerabilities_expose_kev_epss_and_sla_and_filters(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    populate(c, m)
    h = login(c, "analista@radar.local")
    items = c.get("/api/v1/vulnerabilities", headers=h).json()["items"]
    assert items[0]["cve_id"] == "CVE-2021-44228"  # ordenado por riesgo
    top = items[0]
    assert top["in_kev"] and top["ransomware"] and top["epss"] == 0.97 and top["risk_band"] == "critical"
    assert top["sla_state"] in ("en_plazo", "por_vencer", "vencido")
    other = items[1]
    assert other["in_kev"] is False and other["epss"] is None and other["risk_score"] < 70
    assert c.get("/api/v1/vulnerabilities", headers=h, params={"kev": True}).json()["total"] == 1
    assert c.get("/api/v1/vulnerabilities", headers=h, params={"band": "critical"}).json()["total"] == 1
    assert c.get("/api/v1/vulnerabilities", headers=h, params={"band": "inventada"}).status_code == 422


def test_scoring_config_is_versioned_validated_recomputed_and_audited(
    env: tuple[TestClient, sessionmaker[Session]],
) -> None:
    c, m = env
    populate(c, m)
    adm = login(c, "admin@radar.local")
    cur = c.get("/api/v1/settings/scoring", headers=adm).json()
    assert cur["version"] == 1 and "KEV domina" in cur["formula"]
    bad = {**cur["params"], "w_epss": 0.9}
    assert c.put("/api/v1/settings/scoring", headers=adm, json=bad).status_code == 422
    new = {**cur["params"], "w_epss": 0.15, "w_asset": 0.45}
    r = c.put("/api/v1/settings/scoring", headers=adm, json=new)
    assert r.status_code == 200 and r.json()["version"] == 2
    vul = c.get("/api/v1/vulnerabilities", headers=adm, params={"q": "0778"}).json()["items"][0]
    assert vul["risk_score"] != 0 and vul["in_kev"] is False
    with m() as db:
        ev = db.execute(select(AuditLog).where(AuditLog.action == "scoring_update")).scalar_one()
        assert ev.detail["to_version"] == 2 and "w_epss" in ev.detail["changes"]
    # el analista puede ver pero no editar; el simulador no escribe nada
    ana = login(c, "analista@radar.local")
    assert c.get("/api/v1/settings/scoring", headers=ana).status_code == 200
    assert c.put("/api/v1/settings/scoring", headers=ana, json=new).status_code == 403
    pv = c.post("/api/v1/settings/scoring/preview", headers=ana, json={"params": new,
        "sample": {"in_kev": True, "epss": 1, "percentile": 1, "cvss": 10, "criticality": 4, "ransomware": True}}).json()  # fmt: skip
    assert pv["score"] == 100 and pv["band"] == "critical"
    assert c.get("/api/v1/settings/scoring", headers=ana).json()["version"] == 2


def test_recompute_after_config_change_does_not_consume_new_matches(env: tuple[TestClient, sessionmaker[Session]]) -> None:
    c, m = env
    add_inventory(m)
    c.post("/api/v1/internal/kev/ingest", headers=KEY, json=CATALOG)
    adm = login(c, "admin@radar.local")
    cur = c.get("/api/v1/settings/scoring", headers=adm).json()["params"]
    assert c.put("/api/v1/settings/scoring", headers=adm, json={**cur, "kev_floor": 75}).status_code == 200
    rid = c.post("/api/v1/internal/runs/start", headers=KEY, json={}).json()["run_id"]
    cor = c.post("/api/v1/internal/correlate", headers=KEY, json={"run_id": rid}).json()
    assert len(cor["new_matches"]) == 1  # el cambio de fórmula no "gastó" la coincidencia nueva


def test_kev_item_helper_is_valid() -> None:
    assert kev_item("CVE-2021-44228", "2021-12-10", "2021-12-24")["cveID"] == "CVE-2021-44228"
