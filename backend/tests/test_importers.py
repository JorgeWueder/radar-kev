from pathlib import Path

import pytest

from app.services.importers import ImportRejected, parse_upload
from app.services.importers.csv_importer import parse_csv

DATA = Path(__file__).parent / "data"


def test_csv_sample_parses_all_rows() -> None:
    r = parse_upload("hallazgos_demo.csv", (DATA / "hallazgos_demo.csv").read_bytes())
    assert r.source == "csv" and len(r.rows) == 11 and r.total_errors == 0
    assert {x["hostname"] for x in r.rows} == {
        "web-prod-01", "vpn-gw-01", "db-prod-01", "legacy-rdp-01", "app-stg-01", "dev-box-07",
    }


def test_csv_accepts_aliases_semicolon_and_comma_decimal() -> None:
    data = "Host;IP Address;CVE_ID;CVSS Score\nsrv1;10.0.0.1;cve-2021-44228;9,8\n".replace("IP Address", "ip_address")
    r = parse_csv(data.replace("CVSS Score", "cvss_score").encode())
    assert r.rows[0]["cve_id"] == "CVE-2021-44228" and r.rows[0]["cvss_score"] == 9.8


def test_csv_reports_row_errors_without_aborting() -> None:
    data = (
        b"hostname,ip,cve,cvss\n"
        b"ok-1,10.0.0.1,CVE-2021-44228,9.8\n"
        b"bad host!,10.0.0.2,CVE-2021-44228,9.8\n"
        b"ok-2,999.1.1.1,CVE-2021-44228,9.8\n"
        b"ok-3,10.0.0.3,NOT-A-CVE,9.8\n"
        b"ok-4,10.0.0.4,CVE-2021-44228,11\n"
        b"ok-5,10.0.0.5,CVE-2022-0778,abc\n"
    )
    r = parse_csv(data)
    assert len(r.rows) == 1 and r.total_errors == 5
    assert [e["row"] for e in r.errors] == [3, 4, 5, 6, 7]


def test_csv_dedupes_same_host_cve_keeping_highest_cvss() -> None:
    r = parse_csv(b"hostname,cve,cvss\nh1,CVE-2021-44228,5.0\nh1,CVE-2021-44228,9.0\n")
    assert len(r.rows) == 1 and r.rows[0]["cvss_score"] == 9.0


def test_csv_missing_required_columns_is_rejected() -> None:
    with pytest.raises(ImportRejected, match="columnas obligatorias"):
        parse_csv(b"foo,bar\n1,2\n")


def test_nessus_sample_parses_hosts_cves_and_prefers_cvss3() -> None:
    r = parse_upload("demo.nessus", (DATA / "demo.nessus").read_bytes())
    assert r.source == "nessus" and len(r.rows) == 6 and r.total_errors == 0
    log4j = next(x for x in r.rows if x["cve_id"] == "CVE-2021-44228")
    assert log4j["hostname"] == "web-prod-01.corp.example.com"
    assert log4j["cvss_score"] == 10.0 and log4j["cvss_vector"].startswith("CVSS:3.0")
    bluekeep = next(x for x in r.rows if x["cve_id"] == "CVE-2019-0708")
    assert bluekeep["cvss_score"] == 10.0 and bluekeep["ip"] == "10.10.3.8"
    # un ReportItem con dos <cve> produce dos hallazgos; los de severidad 0 sin CVE se ignoran
    assert {x["cve_id"] for x in r.rows if x["hostname"] == "vpn-gw-01"} == {
        "CVE-2024-3400", "CVE-2023-4966", "CVE-2023-4967",
    }


def test_nessus_blocks_xxe_and_entity_expansion() -> None:
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b"<NessusClientData_v2><Report><ReportHost name='h'>&e;</ReportHost></Report></NessusClientData_v2>"
    )
    with pytest.raises(ImportRejected, match="no permitidas"):
        parse_upload("x.nessus", xxe)
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        b"<NessusClientData_v2>&b;</NessusClientData_v2>"
    )
    with pytest.raises(ImportRejected):
        parse_upload("x.nessus", bomb)


@pytest.mark.parametrize(
    ("name", "data", "msg"),
    [
        ("virus.exe", b"MZ....", "no permitido"),
        ("vacio.csv", b"", "vacío"),
        ("falso.nessus", b"hostname,cve\nh,CVE-2021-44228", "no coincide"),
        ("falso.csv", b"<html><body>hola</body></html>", "extensión"),
        ("binario.csv", b"hostname,cve\n\x00\x01\x02", "texto"),
        ("otro.nessus", b"<?xml version='1.0'?><otra_cosa/>", "no es un reporte Nessus"),
        ("grande.csv", b"a" * (10 * 1024 * 1024 + 1), "máximo"),
    ],
)
def test_upload_rejections(name: str, data: bytes, msg: str) -> None:
    with pytest.raises(ImportRejected, match=msg):
        parse_upload(name, data)
