from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit import AuditLog
from app.models.inventory import Asset, ImportBatch, Vulnerability
from tests.conftest import login

DATA = Path(__file__).parent / "data"
ASSET = {"hostname": "Web-Test-01", "ip": "10.1.1.1", "asset_type": "server", "criticality": 3, "environment": "prod"}


def test_asset_crud_validation_and_duplicates(client: TestClient) -> None:
    h = login(client, "analista@radar.local")
    r = client.post("/api/v1/assets", headers=h, json=ASSET)
    assert r.status_code == 201 and r.json()["hostname"] == "web-test-01"
    aid = r.json()["id"]
    assert client.post("/api/v1/assets", headers=h, json=ASSET).status_code == 409
    assert client.post("/api/v1/assets", headers=h, json={**ASSET, "environment": "dev"}).status_code == 201
    for bad in ({"hostname": "bad host!"}, {"ip": "999.1.1.1"}, {"criticality": 9}, {"environment": "x"}, {"asset_type": "x"}):
        assert client.post("/api/v1/assets", headers=h, json={**ASSET, "hostname": "otro", **bad}).status_code == 422, bad
    p = client.patch(f"/api/v1/assets/{aid}", headers=h, json={"criticality": 4, "os": "Ubuntu"})
    assert p.json()["criticality"] == 4
    lst = client.get("/api/v1/assets", headers=h, params={"q": "web-test", "criticality": 4}).json()
    assert lst["total"] == 1
    assert client.delete(f"/api/v1/assets/{aid}", headers=h).status_code == 403  # analista no elimina


def test_asset_delete_is_logical_and_audited(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "admin@radar.local")
    aid = client.post("/api/v1/assets", headers=h, json={**ASSET, "hostname": "borrar-01"}).json()["id"]
    assert client.delete(f"/api/v1/assets/{aid}", headers=h).status_code == 204
    assert client.get(f"/api/v1/assets/{aid}", headers=h).json()["is_active"] is False
    with maker() as s:
        assert s.execute(select(AuditLog).where(AuditLog.module == "assets", AuditLog.action == "delete")).first()


def test_asset_rbac(client: TestClient) -> None:
    assert client.get("/api/v1/assets", headers=login(client, "gerencia@radar.local")).status_code == 403
    aud = login(client, "auditor@radar.local")
    assert client.get("/api/v1/assets", headers=aud).status_code == 200
    assert client.post("/api/v1/assets", headers=aud, json=ASSET).status_code == 403
    assert client.get("/api/v1/assets/export", headers=aud).status_code == 403  # auditor: solo ver


def test_asset_export_formats(client: TestClient) -> None:
    h = login(client, "analista@radar.local")
    csv = client.get("/api/v1/assets/export", headers=h, params={"fmt": "csv"})
    assert csv.status_code == 200 and csv.text.startswith("hostname,ip")
    assert client.get("/api/v1/assets/export", headers=h, params={"fmt": "xlsx"}).content[:2] == b"PK"


def upload(c: TestClient, h: dict[str, str], name: str, data: bytes) -> object:
    return c.post("/api/v1/imports/preview", headers=h, files={"file": (name, data, "application/octet-stream")})


def test_preview_does_not_write_findings_and_commit_is_idempotent(
    client: TestClient, maker: sessionmaker[Session]
) -> None:
    h = login(client, "analista@radar.local")
    data = (DATA / "hallazgos_demo.csv").read_bytes()
    with maker() as s:
        before = s.execute(select(func.count()).select_from(Vulnerability)).scalar_one()
    pv = upload(client, h, "hallazgos_demo.csv", data)
    assert pv.status_code == 201  # type: ignore[attr-defined]
    body = pv.json()  # type: ignore[attr-defined]
    assert body["rows_ok"] == 11 and body["rows_error"] == 0 and body["hosts"] == 6 and len(body["sample"]) == 10
    with maker() as s:
        assert s.execute(select(func.count()).select_from(Vulnerability)).scalar_one() == before  # preview no escribe

    done = client.post(f"/api/v1/imports/{body['id']}/commit", headers=h).json()
    assert done["status"] == "committed"
    assert done["summary"]["created_vulnerabilities"] == 11 and done["summary"]["created_assets"] == 6
    assert client.post(f"/api/v1/imports/{body['id']}/commit", headers=h).status_code == 409  # no se aplica dos veces

    # Reimportar el mismo archivo no duplica activos ni hallazgos.
    again = upload(client, h, "hallazgos_demo.csv", data).json()  # type: ignore[attr-defined]
    summary = client.post(f"/api/v1/imports/{again['id']}/commit", headers=h).json()["summary"]
    assert summary["created_assets"] == 0 and summary["created_vulnerabilities"] == 0
    assert summary["updated_vulnerabilities"] == 11
    with maker() as s:
        assert s.execute(select(func.count()).select_from(Vulnerability)).scalar_one() == before + 11
        a = s.execute(select(Asset).where(Asset.hostname == "web-prod-01")).scalar_one()
        assert a.auto_created is True and a.criticality == 2 and str(a.ip) == "10.10.1.21"
        batch = s.get(ImportBatch, body["id"])
        assert batch is not None and batch.payload == []  # el contenido no se conserva tras aplicar


def test_nessus_import_and_reopen_mitigated(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "admin@radar.local")
    nessus = (DATA / "demo.nessus").read_bytes()
    b = upload(client, h, "demo.nessus", nessus).json()  # type: ignore[attr-defined]
    assert b["source"] == "nessus" and b["rows_ok"] == 6
    client.post(f"/api/v1/imports/{b['id']}/commit", headers=h)
    vulns = client.get("/api/v1/vulnerabilities", headers=h, params={"q": "CVE-2019-0708"}).json()["items"]
    assert len(vulns) >= 1
    vid = vulns[0]["id"]
    assert client.patch(f"/api/v1/vulnerabilities/{vid}", headers=h, json={"status": "mitigated"}).json()["status"] == "mitigated"
    b2 = upload(client, h, "demo.nessus", nessus).json()  # type: ignore[attr-defined]
    s2 = client.post(f"/api/v1/imports/{b2['id']}/commit", headers=h).json()["summary"]
    assert s2["reopened"] >= 1  # el escáner volvió a verla: se reabre
    assert client.get(f"/api/v1/vulnerabilities/{vid}", headers=h).json()["status"] == "open"


def test_import_matches_existing_asset_instead_of_duplicating(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "admin@radar.local")
    client.post("/api/v1/assets", headers=h, json={"hostname": "existente-01", "criticality": 4, "environment": "staging"})
    b = upload(client, h, "x.csv", b"hostname,cve,cvss\nexistente-01,CVE-2021-44228,9.8\n").json()  # type: ignore[attr-defined]
    s = client.post(f"/api/v1/imports/{b['id']}/commit", headers=h).json()["summary"]
    assert s["created_assets"] == 0 and s["created_vulnerabilities"] == 1
    with maker() as sess:
        a = sess.execute(select(Asset).where(Asset.hostname == "existente-01")).scalar_one()
        assert a.criticality == 4 and a.auto_created is False


@pytest.mark.parametrize(("name", "data"), [("x.exe", b"MZ"), ("x.csv", b""), ("x.nessus", b"hostname,cve")])
def test_rejected_upload_returns_422_and_is_audited(
    client: TestClient, maker: sessionmaker[Session], name: str, data: bytes
) -> None:
    h = login(client, "analista@radar.local")
    assert upload(client, h, name, data).status_code == 422  # type: ignore[attr-defined]
    with maker() as s:
        row = s.execute(select(AuditLog).where(AuditLog.action == "preview").order_by(AuditLog.id.desc())).scalars().first()
        assert row is not None and row.result == "failure"


def test_import_rbac_and_batch_ownership(client: TestClient) -> None:
    mgr = login(client, "gerencia@radar.local")
    assert upload(client, mgr, "x.csv", b"hostname,cve\nh,CVE-2021-44228").status_code == 403  # type: ignore[attr-defined]
    aud = login(client, "auditor@radar.local")
    assert upload(client, aud, "x.csv", b"hostname,cve\nh,CVE-2021-44228").status_code == 403  # type: ignore[attr-defined]
    assert client.get("/api/v1/imports", headers=aud).status_code == 200
    ana = login(client, "analista@radar.local")
    b = upload(client, ana, "x.csv", b"hostname,cve\nh1,CVE-2021-44228").json()  # type: ignore[attr-defined]
    adm = login(client, "admin@radar.local")
    assert client.post(f"/api/v1/imports/{b['id']}/commit", headers=adm).status_code == 404  # lote ajeno


def test_vulnerability_status_requires_edit_permission(client: TestClient) -> None:
    ana = login(client, "analista@radar.local")
    b = upload(client, ana, "v.csv", b"hostname,cve\nvuln-host,CVE-2021-44228").json()  # type: ignore[attr-defined]
    client.post(f"/api/v1/imports/{b['id']}/commit", headers=ana)
    vid = client.get("/api/v1/vulnerabilities", headers=ana, params={"q": "vuln-host"}).json()["items"][0]["id"]
    aud = login(client, "auditor@radar.local")
    assert client.patch(f"/api/v1/vulnerabilities/{vid}", headers=aud, json={"status": "accepted"}).status_code == 403
    assert client.patch(f"/api/v1/vulnerabilities/{vid}", headers=ana, json={"status": "nope"}).status_code == 422


def test_import_matches_fqdn_to_existing_short_name(client: TestClient, maker: sessionmaker[Session]) -> None:
    h = login(client, "admin@radar.local")
    client.post("/api/v1/assets", headers=h, json={"hostname": "srv-corto", "criticality": 3})
    b = upload(client, h, "f.csv", b"hostname,cve\nsrv-corto.corp.example.com,CVE-2021-44228\n").json()  # type: ignore[attr-defined]
    s = client.post(f"/api/v1/imports/{b['id']}/commit", headers=h).json()["summary"]
    assert s["created_assets"] == 0 and s["created_vulnerabilities"] == 1
    with maker() as sess:
        assert sess.execute(select(func.count()).select_from(Asset).where(Asset.hostname.like("srv-corto%"))).scalar_one() == 1
