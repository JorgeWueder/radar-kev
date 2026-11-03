import gzip
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.intel import ExposureSnapshot
from app.models.inventory import Asset, Vulnerability
from app.services.correlation import correlate
from app.services.intel import IntelError, ingest_epss, ingest_kev, parse_epss_csv
from tests.conftest import isolated_schema

TODAY = date(2026, 11, 3)


def kev_item(cve: str, added: str, due: str, ransomware: str = "Unknown", **extra: Any) -> dict[str, Any]:
    return {
        "cveID": cve, "vendorProject": "Apache", "product": "Log4j2", "vulnerabilityName": f"Falla {cve}",
        "dateAdded": added, "shortDescription": "desc", "requiredAction": "Aplicar parche del proveedor",
        "dueDate": due, "knownRansomwareCampaignUse": ransomware, "notes": "https://x", "cwes": ["CWE-20"],
        **extra,
    }  # fmt: skip


CATALOG = {
    "title": "CISA KEV", "catalogVersion": "2026.10.30", "count": 2,
    "vulnerabilities": [
        kev_item("CVE-2021-44228", "2021-12-10", "2021-12-24", "Known", forensicTriage="No", campoNuevo="x"),
        kev_item("CVE-2023-4966", "2023-10-19", "2023-11-08"),
    ],
}  # fmt: skip


@pytest.fixture
def sm() -> Iterator[sessionmaker[Session]]:
    with isolated_schema() as m:
        yield m


def seed(db: Session) -> dict[str, Asset]:
    a = Asset(hostname="srv-a", criticality=4, environment="prod")
    b = Asset(hostname="srv-b", criticality=1, environment="dev")
    db.add_all([a, b])
    db.flush()
    seen = datetime(2026, 10, 30, tzinfo=UTC)
    db.add_all(
        [
            Vulnerability(asset_id=a.id, cve_id="CVE-2021-44228", cvss_score=10, first_seen=seen),
            Vulnerability(asset_id=a.id, cve_id="CVE-2022-0778", cvss_score=7.5, first_seen=seen),
            Vulnerability(asset_id=b.id, cve_id="CVE-2021-44228", cvss_score=10, first_seen=seen),
            Vulnerability(asset_id=a.id, cve_id="CVE-2023-4966", cvss_score=9.4, first_seen=seen, status="mitigated"),
        ]
    )
    ingest_kev(db, CATALOG)
    ingest_epss(db, [
        {"cve": "CVE-2021-44228", "epss": "0.970000000", "percentile": "0.999000000"},
        {"cve": "CVE-2022-0778", "epss": "0.010000000", "percentile": "0.300000000"},
    ], TODAY)  # fmt: skip
    db.commit()
    return {"a": a, "b": b}


def vuln(db: Session, host: str, cve: str) -> Vulnerability:
    return db.execute(
        select(Vulnerability).join(Asset).where(Asset.hostname == host, Vulnerability.cve_id == cve)
    ).scalar_one()


def test_correlation_flags_only_active_kev_matches_and_scores(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        res = correlate(db, today=TODAY)
        db.commit()
        assert res.total == 4 and res.in_kev == 2
        assert sorted(m["hostname"] for m in res.new_matches) == ["srv-a", "srv-b"]
        assert res.new_matches[0]["hostname"] == "srv-a"  # ordenadas por riesgo desc
        assert all(m["cve_id"] == "CVE-2021-44228" and m["ransomware"] for m in res.new_matches)
        a44228 = vuln(db, "srv-a", "CVE-2021-44228")
        assert float(a44228.risk_score) == 100.0 and a44228.risk_band == "critical"  # type: ignore[arg-type]
        b44228 = vuln(db, "srv-b", "CVE-2021-44228")
        assert 98 < float(b44228.risk_score) < 100  # type: ignore[arg-type]
        non_kev = vuln(db, "srv-a", "CVE-2022-0778")
        assert float(non_kev.risk_score) < 70 and non_kev.kev_matched_at is None  # type: ignore[arg-type]
        # detectado en 2026-10-30, mucho después del dueDate de CISA: ventana de 14 días desde la detección
        assert a44228.sla_due_date == date(2026, 11, 13)
        assert vuln(db, "srv-a", "CVE-2023-4966").kev_matched_at is None  # mitigada: no genera coincidencia


def test_second_run_is_idempotent_no_new_matches(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        assert len(correlate(db, today=TODAY).new_matches) == 2
        db.commit()
        again = correlate(db, today=TODAY)
        db.commit()
        assert again.new_matches == [] and again.in_kev == 2
        again3 = correlate(db, today=TODAY)
        assert again3.new_matches == []


def test_recompute_without_marking_keeps_matches_pending(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        res = correlate(db, mark_matches=False, today=TODAY)
        assert res.new_matches == []
        assert vuln(db, "srv-a", "CVE-2021-44228").kev_matched_at is None
        assert len(correlate(db, today=TODAY).new_matches) == 2  # luego sí se detectan como nuevas


def test_reopened_vulnerability_becomes_a_new_match_later(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        correlate(db, today=TODAY)
        v = vuln(db, "srv-a", "CVE-2023-4966")
        v.status = "open"
        db.commit()
        res = correlate(db, today=TODAY)
        assert [m["cve_id"] for m in res.new_matches] == ["CVE-2023-4966"]


def test_snapshot_counts(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        correlate(db, today=TODAY)
        db.commit()
        snap = db.get(ExposureSnapshot, TODAY)
        assert snap is not None and snap.kev_open == 2 and snap.critical_assets_exposed == 1
        assert snap.sla_overdue == 0 and sum(snap.by_band.values()) == 3  # 3 activas (la mitigada no cuenta)


def test_overdue_sla_is_counted(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        seed(db)
        correlate(db, today=date(2026, 12, 1))  # pasada la ventana de 14 días
        db.commit()
        snap = db.get(ExposureSnapshot, date(2026, 12, 1))
        assert snap is not None and snap.sla_overdue >= 2


def test_empty_inventory_is_fine(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        res = correlate(db, today=TODAY)
        assert res.total == 0 and res.new_matches == []


def test_kev_ingest_upserts_keeps_first_seen_and_ignores_unknown_fields(sm: sessionmaker[Session]) -> None:
    from app.models.intel import KevEntry

    with sm() as db:
        first = ingest_kev(db, CATALOG)
        db.commit()
        assert first == {"catalog_version": "2026.10.30", "total": 2, "new_entries": 2}
        seen = db.get(KevEntry, "CVE-2021-44228").first_seen_at  # type: ignore[union-attr]
        newer = {**CATALOG, "catalogVersion": "2026.11.03",
                 "vulnerabilities": [*CATALOG["vulnerabilities"], kev_item("CVE-2024-3400", "2024-04-12", "2024-04-19")]}  # fmt: skip
        second = ingest_kev(db, newer)
        db.commit()
        assert second["new_entries"] == 1 and second["total"] == 3
        db.expire_all()
        row = db.get(KevEntry, "CVE-2021-44228")
        assert row is not None and row.first_seen_at == seen and row.catalog_version == "2026.11.03"
        assert row.forensic_triage == "No"


@pytest.mark.parametrize(
    "payload",
    [
        {"catalogVersion": "x", "vulnerabilities": []},  # vacío
        {"vulnerabilities": [kev_item("CVE-2021-44228", "2021-12-10", "2021-12-24")]},  # sin catalogVersion
        {"catalogVersion": "x", "vulnerabilities": [{"cveID": "no-es-cve"}]},
        {"catalogVersion": "x", "vulnerabilities": [kev_item("CVE-2021-44228", "10/12/2021", "2021-12-24")]},
    ],
)
def test_kev_schema_drift_is_rejected_not_stored(sm: sessionmaker[Session], payload: dict[str, Any]) -> None:
    with sm() as db, pytest.raises(IntelError):
        ingest_kev(db, payload)


def test_epss_ingest_parses_string_numbers_and_skips_invalid(sm: sessionmaker[Session]) -> None:
    with sm() as db:
        out = ingest_epss(db, [
            {"cve": "CVE-2021-44228", "epss": "0.999990000", "percentile": "1.000000000", "date": "2026-11-03"},
            {"cve": "CVE-2021-44228", "epss": "0.5", "percentile": "0.5", "date": "2026-11-03"},  # mismo día: actualiza
            {"cve": "basura", "epss": "0.1", "percentile": "0.1"},
            {"cve": "CVE-2022-0778", "epss": "1.7", "percentile": "0.1"},  # fuera de rango
        ])  # fmt: skip
        assert out == {"scored": 1, "invalid": 2}  # el duplicado se colapsa (gana el último)
        from app.models.intel import EpssScore

        assert float(db.execute(select(EpssScore.epss)).scalar_one()) == 0.5


def test_epss_csv_fallback_parsing_filters_to_inventory() -> None:
    raw = (
        b"#model_version:v2026.06.15,score_date:2026-11-03T12:00:27Z\n"
        b"cve,epss,percentile\nCVE-2021-44228,0.97,0.999\nCVE-1999-0001,0.04753,0.91894\nCVE-2022-0778,0.01,0.3\n"
    )
    items, sdate, version = parse_epss_csv(gzip.compress(raw), {"CVE-2021-44228", "CVE-2022-0778"})
    assert sdate == date(2026, 11, 3) and version == "v2026.06.15"
    assert {i["cve"] for i in items} == {"CVE-2021-44228", "CVE-2022-0778"}
    with pytest.raises(IntelError, match="metadatos"):
        parse_epss_csv(gzip.compress(b"cve,epss,percentile\nCVE-2021-44228,0.9,0.9\n"))
