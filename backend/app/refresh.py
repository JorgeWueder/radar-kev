"""Actualización manual: descarga KEV y EPSS reales, ingesta y cruza. `python -m app.refresh`.
Útil en desarrollo y como respaldo; el flujo diario normal lo orquesta n8n con los mismos servicios."""

import json

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.models.inventory import Vulnerability
from app.services import feeds
from app.services.correlation import correlate
from app.services.intel import ingest_epss, ingest_kev, parse_epss_csv


def run() -> dict[str, object]:
    out: dict[str, object] = {}
    with get_sessionmaker()() as db:
        out["kev"] = ingest_kev(db, feeds.fetch_kev())
        db.commit()
        cves = sorted(set(db.execute(select(Vulnerability.cve_id)).scalars()))
        try:
            out["epss"] = ingest_epss(db, feeds.fetch_epss(cves))
        except RuntimeError as e:  # respaldo: CSV diario completo, filtrado al inventario
            items, sdate, version = parse_epss_csv(feeds.fetch_epss_csv(), set(cves))
            out["epss"] = {**ingest_epss(db, items, sdate, version), "fallback": "csv", "reason": str(e)}
        db.commit()
        res = correlate(db)
        db.commit()
        out["correlation"] = {"total": res.total, "in_kev": res.in_kev, "new_matches": len(res.new_matches),
                              "epss_missing": res.epss_missing}  # fmt: skip
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
