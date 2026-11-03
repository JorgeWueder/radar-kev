from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory import Asset, ImportBatch, Vulnerability

REOPEN_FROM = {"mitigated"}  # el escáner lo vuelve a ver: la mitigación no se sostuvo


def _short(host: str) -> str:
    """Nombre corto de un FQDN (los escáneres y el inventario suelen mezclar ambos); las IP no se recortan."""
    return host if host.replace(".", "").isdigit() or ":" in host else host.split(".")[0]


def _find_asset(candidates: list[Asset], ip: str | None) -> Asset | None:
    active = [a for a in candidates if a.is_active]
    if not active:
        return None
    if ip:
        for a in active:
            if a.ip and str(a.ip) == ip:
                return a
    return active[0]


def commit_batch(db: Session, batch: ImportBatch) -> dict[str, Any]:
    """Aplica las filas validadas de la previsualización. Reimportar el mismo archivo no duplica."""
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = list(batch.payload)
    assets_by_host: dict[str, list[Asset]] = {}
    wanted = {r["hostname"] for r in rows} | {_short(r["hostname"]) for r in rows}
    for a in db.execute(select(Asset).where(func.lower(Asset.hostname).in_(wanted))).scalars():
        assets_by_host.setdefault(a.hostname.lower(), []).append(a)

    created_assets = created = updated = reopened = 0
    touched: dict[str, Asset] = {}
    for r in rows:
        asset = (
            touched.get(r["hostname"])
            or _find_asset(assets_by_host.get(r["hostname"], []), r["ip"])
            or _find_asset(assets_by_host.get(_short(r["hostname"]), []), r["ip"])
        )
        if asset is None:
            asset = Asset(
                hostname=r["hostname"],
                ip=r["ip"],
                os=r["os"],
                asset_type="other",
                criticality=2,
                environment="prod",
                auto_created=True,
            )
            db.add(asset)
            db.flush()
            assets_by_host.setdefault(r["hostname"], []).append(asset)
            created_assets += 1
        else:
            if r["ip"] and not asset.ip:
                asset.ip = r["ip"]
            if r["os"] and not asset.os:
                asset.os = r["os"]
        touched[r["hostname"]] = asset

        vuln = db.execute(
            select(Vulnerability).where(Vulnerability.asset_id == asset.id, Vulnerability.cve_id == r["cve_id"])
        ).scalar_one_or_none()
        if vuln is None:
            db.add(
                Vulnerability(
                    asset_id=asset.id,
                    cve_id=r["cve_id"],
                    cvss_score=r["cvss_score"],
                    cvss_vector=r["cvss_vector"],
                    import_batch_id=batch.id,
                    first_seen=now,
                    last_seen=now,
                )
            )
            created += 1
        else:
            vuln.last_seen = now
            if r["cvss_score"] is not None:
                vuln.cvss_score = r["cvss_score"]
                vuln.cvss_vector = r["cvss_vector"] or vuln.cvss_vector
            if vuln.status in REOPEN_FROM:
                vuln.status = "open"
                vuln.resolved_at = None
                reopened += 1
            updated += 1
    db.flush()
    summary: dict[str, Any] = {
        "created_assets": created_assets,
        "created_vulnerabilities": created,
        "updated_vulnerabilities": updated,
        "reopened": reopened,
    }
    batch.status = "committed"
    batch.committed_at = now
    batch.summary = summary
    batch.payload = []  # ya aplicado: no se conserva el contenido del archivo
    return summary
