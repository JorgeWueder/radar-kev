"""Inventario de demostración con CVEs reales: unos están en CISA KEV y otros no (verificado el 2026-11-03),
para mostrar el cruce. Idempotente: no duplica lo que ya existe."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.inventory import Asset, Vulnerability

# hostname, ip, tipo, SO, criticidad (1-4), entorno
ASSETS = [
    ("web-prod-01", "10.10.1.21", "server", "Ubuntu 22.04", 4, "prod"),
    ("web-prod-02", "10.10.1.22", "server", "Ubuntu 22.04", 4, "prod"),
    ("vpn-gw-01", "10.10.0.5", "network", "PAN-OS 10.2", 4, "prod"),
    ("fw-edge-01", "10.10.0.1", "network", "FortiOS 7.2", 4, "prod"),
    ("sw-core-01", "10.10.0.2", "network", "Cisco IOS XE 17.6", 4, "prod"),
    ("db-prod-01", "10.10.2.15", "database", "Windows Server 2019", 4, "prod"),
    ("mail-exch-01", "10.10.2.30", "server", "Windows Server 2016", 4, "prod"),
    ("dc-01", "10.10.2.5", "server", "Windows Server 2019", 4, "prod"),
    ("legacy-rdp-01", "10.10.3.8", "server", "Windows Server 2008 R2", 3, "prod"),
    ("file-srv-01", "10.10.3.20", "server", "Windows Server 2012 R2", 3, "prod"),
    ("jenkins-ci-01", "10.10.4.9", "application", "Ubuntu 20.04", 3, "prod"),
    ("wiki-conf-01", "10.10.4.12", "application", "CentOS 7", 2, "prod"),
    ("app-stg-01", "10.20.1.4", "server", "Debian 12", 2, "staging"),
    ("app-stg-02", "10.20.1.5", "server", "Debian 12", 2, "staging"),
    ("dev-box-07", "10.30.1.7", "workstation", "Ubuntu 20.04", 1, "dev"),
    ("dev-box-08", "10.30.1.8", "workstation", "Ubuntu 22.04", 1, "dev"),
]  # fmt: skip

# hostname, CVE, CVSS, días desde que se detectó
FINDINGS = [
    ("web-prod-01", "CVE-2021-44228", 10.0, 5), ("web-prod-01", "CVE-2022-22965", 9.8, 40),
    ("web-prod-01", "CVE-2022-0778", 7.5, 40),
    ("web-prod-02", "CVE-2022-22965", 9.8, 40), ("web-prod-02", "CVE-2023-38545", 9.8, 12),
    ("vpn-gw-01", "CVE-2024-3400", 10.0, 2), ("vpn-gw-01", "CVE-2023-4966", 9.4, 20),
    ("vpn-gw-01", "CVE-2019-11510", 10.0, 90),
    ("fw-edge-01", "CVE-2018-13379", 9.8, 90), ("fw-edge-01", "CVE-2023-27997", 9.8, 15),
    ("fw-edge-01", "CVE-2021-3449", 5.9, 15),
    ("sw-core-01", "CVE-2023-20198", 10.0, 3),
    ("db-prod-01", "CVE-2023-34362", 9.8, 8), ("db-prod-01", "CVE-2021-3449", 5.9, 8),
    ("db-prod-01", "CVE-2022-3602", 7.5, 8),
    ("mail-exch-01", "CVE-2021-26855", 9.8, 60), ("mail-exch-01", "CVE-2023-0286", 7.4, 60),
    ("dc-01", "CVE-2020-1472", 10.0, 25), ("dc-01", "CVE-2021-34527", 8.8, 25),
    ("legacy-rdp-01", "CVE-2019-0708", 9.8, 120), ("legacy-rdp-01", "CVE-2017-0144", 8.1, 120),
    ("file-srv-01", "CVE-2017-0144", 8.1, 45), ("file-srv-01", "CVE-2021-34527", 8.8, 45),
    ("file-srv-01", "CVE-2020-11022", 6.1, 45),
    ("jenkins-ci-01", "CVE-2021-3156", 7.8, 30), ("jenkins-ci-01", "CVE-2023-38545", 9.8, 30),
    ("wiki-conf-01", "CVE-2022-26134", 9.8, 75), ("wiki-conf-01", "CVE-2021-3156", 7.8, 75),
    ("app-stg-01", "CVE-2023-38545", 9.8, 10), ("app-stg-01", "CVE-2022-3602", 7.5, 10),
    ("app-stg-01", "CVE-2022-0778", 7.5, 10),
    ("app-stg-02", "CVE-2023-0286", 7.4, 10), ("app-stg-02", "CVE-2020-11022", 6.1, 10),
    ("dev-box-07", "CVE-2023-0286", 7.4, 4), ("dev-box-07", "CVE-2020-11022", 6.1, 4),
    ("dev-box-07", "CVE-2021-3156", 7.8, 4),
    ("dev-box-08", "CVE-2021-3156", 7.8, 4), ("dev-box-08", "CVE-2020-11022", 6.1, 4),
]  # fmt: skip


def seed_demo(db: Session) -> dict[str, int]:
    owner = db.execute(select(User).where(User.email == "analista@radar.local")).scalar_one_or_none()
    now = datetime.now(UTC)
    by_host: dict[str, Asset] = {}
    created_assets = 0
    for host, ip, kind, os_name, crit, env in ASSETS:
        a = db.execute(select(Asset).where(Asset.hostname == host)).scalars().first()
        if a is None:
            a = Asset(hostname=host)
            db.add(a)
            created_assets += 1
        a.ip, a.asset_type, a.os, a.criticality, a.environment = ip, kind, os_name, crit, env
        a.owner_id = owner.id if owner else None
        a.auto_created = False
        a.is_active = True
        by_host[host] = a
    db.flush()
    created = 0
    for host, cve, cvss, days in FINDINGS:
        asset = by_host[host]
        exists = db.execute(
            select(Vulnerability.id).where(Vulnerability.asset_id == asset.id, Vulnerability.cve_id == cve)
        ).first()
        if exists:
            continue
        seen = now - timedelta(days=days)
        db.add(Vulnerability(asset_id=asset.id, cve_id=cve, cvss_score=cvss, first_seen=seen, last_seen=now))
        created += 1
    db.flush()
    return {"assets": created_assets, "findings": created}
