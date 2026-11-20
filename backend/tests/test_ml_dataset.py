import gzip
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.ml import dataset as ds
from app.ml import nvd, sources
from app.models.audit import AuditLog
from app.models.intel import KevEntry
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_reports import Env

S = date(2025, 3, 1)


# --------------------------------------------------------------------------- archivos sintéticos (sin red)
def nvd_record(cve: str, published: str, cna: str = "secure@microsoft.com", cvss_cna: float | None = 9.8,
               cvss_nvd: float | None = None, ssvc: tuple[str, str] | None = None, rejected: bool = False) -> dict[str, Any]:  # fmt: skip
    metrics: dict[str, Any] = {"cvssMetricV31": []}
    if cvss_nvd is not None:
        metrics["cvssMetricV31"].append({"source": "nvd@nist.gov", "type": "Primary", "cvssData": {"baseScore": cvss_nvd, "attackVector": "LOCAL"}})
        metrics["cvssMetricV31"].append({"source": "134c704f-cisa-adp", "type": "Secondary", "cvssData": {"baseScore": 9.9}})
    if cvss_cna is not None:
        metrics["cvssMetricV31"].append({"source": cna, "type": "Secondary", "cvssData": {
            "baseScore": cvss_cna, "attackVector": "NETWORK", "attackComplexity": "LOW", "privilegesRequired": "NONE",
            "userInteraction": "NONE", "scope": "UNCHANGED", "confidentialityImpact": "HIGH", "integrityImpact": "HIGH",
            "availabilityImpact": "HIGH"}})  # fmt: skip
    if ssvc:
        metrics["ssvcV203"] = [{"source": "cisa", "ssvcData": {"timestamp": ssvc[1] + "T10:00:00Z", "options": [
            {"exploitation": ssvc[0]}, {"automatable": "yes"}, {"technicalImpact": "total"}]}}]  # fmt: skip
    return {"cve": {"id": cve, "sourceIdentifier": cna, "published": published + "T10:00:00.000",
                    "vulnStatus": "Rejected" if rejected else "Analyzed", "metrics": metrics,
                    "weaknesses": [{"source": cna, "description": [{"value": "CWE-787"}]},
                                   {"source": "nvd@nist.gov", "description": [{"value": "CWE-20"}]}],
                    "references": [{"url": "u"}] * 3}}  # fmt: skip


def write_nvd(path: Path, records: list[dict[str, Any]]) -> Path:
    payload = {"resultsPerPage": len(records), "format": "NVD_CVE", "vulnerabilities": records}
    path.write_bytes(gzip.compress(json.dumps(payload, indent=1).encode()))
    return path


def write_epss(path: Path, day: date, rows: list[tuple[str, float]], model: str = "v2025.03.14") -> Path:
    body = "cve,epss,percentile\n" + "".join(f"{c},{e},{min(0.99999, e * 1.5)}\n" for c, e in rows)
    path.write_bytes(gzip.compress(f"#model_version:{model},score_date:{day.isoformat()}T00:00:00Z\n{body}".encode()))
    return path


def test_nvd_streaming_parser_prefers_cna_cvss_and_skips_rejected(tmp_path: Path) -> None:
    p = write_nvd(tmp_path / "n.json.gz", [
        nvd_record("CVE-2024-0001", "2024-01-10", cvss_cna=8.1, cvss_nvd=5.0, ssvc=("active", "2024-02-01")),
        nvd_record("CVE-2024-0002", "2024-01-11", cvss_cna=None, cvss_nvd=6.5),
        nvd_record("CVE-2024-0003", "2024-01-12", rejected=True),
    ])  # fmt: skip
    assert [c["id"] for c in nvd.iter_cves(p)] == ["CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"]
    t = nvd.table([p]).set_index("cve")
    assert "CVE-2024-0003" not in t.index
    assert (t.loc["CVE-2024-0001", "cvss"], t.loc["CVE-2024-0001", "cvss_src"], t.loc["CVE-2024-0001", "av"]) == (8.1, "cna", "NETWORK")
    # Solo el NVD (Primary) y CISA ADP (Secondary de otra fuente) tienen puntaje: llegaron después, no se usa.
    assert pd.isna(t.loc["CVE-2024-0002", "cvss"]) and t.loc["CVE-2024-0002", "cvss_src"] == "posterior"
    assert t.loc["CVE-2024-0001", "ssvc_exploitation"] == "active" and t.loc["CVE-2024-0001", "ssvc_ts"] == date(2024, 2, 1)
    assert t.loc["CVE-2024-0001", "cwe"] == "CWE-787"  # el de la CNA, no el CWE-20 que agregó el NVD


def test_snapshots_and_temporal_split() -> None:
    shots = ds.snapshots(date(2025, 1, 15), date(2026, 11, 18), 90)
    assert shots[0] == date(2025, 1, 1) and shots[-1] == date(2026, 8, 1) and len(shots) == 20
    sp = ds.split_of(20)
    assert sp.count("desarrollo") == 14 and sp.count("validacion") == 3 and sp.count("prueba") == 3
    assert sp == sorted(sp, key=["desarrollo", "validacion", "prueba"].index)  # nunca se mezclan en el tiempo
    with pytest.raises(ValueError):
        ds.split_of(2)


def test_snapshot_rows_use_only_information_available_at_the_snapshot() -> None:
    epss = pd.DataFrame({"cve": ["CVE-A", "CVE-B", "CVE-C", "CVE-D", "CVE-E"], "epss": [0.9, 0.2, 0.01, 0.5, 0.3],
                         "percentile": [0.99, 0.9, 0.5, 0.95, 0.92]})  # fmt: skip
    prev = pd.DataFrame({"cve": ["CVE-A", "CVE-B"], "epss": [0.5, 0.25]})
    kev = pd.DataFrame({"cve": ["CVE-OLD", "CVE-D", "CVE-A", "CVE-B", "CVE-X"],
                        "date_added": [S - timedelta(days=200), S - timedelta(days=1), S + timedelta(days=10), S + timedelta(days=120),
                                       S - timedelta(days=5)]})  # fmt: skip
    nvd_t = pd.DataFrame([
        {"cve": "CVE-A", "published": date(2025, 1, 1), "cna": "ms", "cvss": 9.8, "cvss_src": "cna", "ssvc_exploitation": "active",
         "ssvc_automatable": "yes", "ssvc_ts": S - timedelta(days=3)},
        {"cve": "CVE-B", "published": date(2025, 4, 1), "cna": "ms", "cvss": 7.0, "cvss_src": "cna", "ssvc_exploitation": "active",
         "ssvc_automatable": "yes", "ssvc_ts": S + timedelta(days=3)},
        {"cve": "CVE-X", "published": date(2024, 1, 1), "cna": "ms"}, {"cve": "CVE-OLD", "published": date(2020, 1, 1), "cna": "ms"},
    ]).reindex(columns=nvd.COLUMNS)  # fmt: skip
    edb = pd.DataFrame({"cve": ["CVE-A", "CVE-A", "CVE-B"], "date_added": [S - timedelta(days=9), S + timedelta(days=2), S + timedelta(days=1)]})
    r = ds.snapshot_rows(S, 90, epss, prev, "v1", kev, nvd_t, edb, 1.0, np.random.default_rng(0)).set_index("cve")
    assert "CVE-D" not in r.index  # ya estaba en KEV en la foto
    assert r.loc["CVE-A", "label"] == 1 and r.loc["CVE-B", "label"] == 0  # B entra a KEV después de la ventana de 90 días
    assert r.loc["CVE-A", "epss_delta"] == pytest.approx(0.4) and np.isnan(r.loc["CVE-C", "epss_delta"])
    assert not {"ssvc_exploitation", "ssvc_automatable", "n_refs"} & set(ds.FEATURE_NAMES)  # descartadas por fuga
    assert {e["name"].split(" ")[0] for e in ds.EXCLUDED} >= {"ssvc_exploitation", "n_refs"}
    assert r.loc["CVE-A", "edb_exploits"] == 1 and r.loc["CVE-B", "edb_exploits"] == 0  # exploits posteriores no cuentan
    assert r.loc["CVE-A", "cna_kev_prior"] == 2  # CVE-OLD y CVE-X (ms) antes de S; CVE-A y CVE-B aún no
    assert np.isnan(r.loc["CVE-B", "days_published"])  # publicado después de la foto
    assert r.loc["CVE-A", "days_published"] == (S - date(2025, 1, 1)).days
    assert r.loc["CVE-C", "cna"] == "desconocido" and set(r["weight"]) == {1.0}


def test_negative_sampling_is_reproducible_and_weighted() -> None:
    epss = pd.DataFrame({"cve": [f"CVE-{i}" for i in range(5000)], "epss": 0.1, "percentile": 0.5})
    kev = pd.DataFrame({"cve": ["CVE-7"], "date_added": [S + timedelta(days=5)]})
    nvd_t = pd.DataFrame(columns=nvd.COLUMNS)
    edb = pd.DataFrame(columns=["cve", "date_added"])

    def rows(seed: int) -> pd.DataFrame:
        return ds.snapshot_rows(S, 90, epss, None, None, kev, nvd_t, edb, 0.1, np.random.default_rng(seed))

    a, b = rows(1), rows(1)
    assert a["cve"].tolist() == b["cve"].tolist() and a["cve"].tolist() != rows(2)["cve"].tolist()
    assert "CVE-7" in set(a["cve"]) and a.loc[a["cve"] == "CVE-7", "weight"].iloc[0] == 1.0  # todos los positivos se quedan
    neg = a[a["label"] == 0]
    assert 400 < len(neg) < 600 and set(neg["weight"]) == {10.0}


# --------------------------------------------------------------------------- de punta a punta por la API
@pytest.fixture
def fake_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    raw = sources.data_dir() / "raw"
    rng = np.random.default_rng(3)
    universe = [f"CVE-2024-{i:04d}" for i in range(600)]
    nvd_file = write_nvd(raw / "nvd.json.gz", [nvd_record(c, "2024-06-01", cna="ms" if i % 3 else "gh",
                                                          ssvc=("active", "2024-12-01") if i < 30 else None)
                                               for i, c in enumerate(universe)])  # fmt: skip
    empty = write_nvd(raw / "nvd_empty.json.gz", [])
    edb = raw / "edb.csv"
    edb.write_text("id,codes,date_added\n1,CVE-2024-0001;OSVDB-1,2024-12-15\n2,CVE-2024-0002,2026-01-01\n", encoding="utf-8")

    def epss_for(day: date) -> tuple[Path, date, dict[str, Any]]:
        rows = [(c, round(0.3 + 0.6 * (i < 30) * rng.random() if i < 30 else 0.001 + 0.05 * rng.random(), 5)) for i, c in enumerate(universe)]
        p = write_epss(raw / f"epss_{day}.csv.gz", day, rows, model="v2025.03.14" if day < date(2025, 7, 1) else "v2026.06.15")
        return p, day, {"kind": "epss", "file": p.name, "date": day.isoformat()}

    monkeypatch.setattr(sources, "epss_for", epss_for)
    monkeypatch.setattr(sources, "nvd_year", lambda y: (nvd_file if y == 2024 else empty, {"kind": "nvd", "year": y}))
    monkeypatch.setattr(sources, "exploitdb", lambda: (edb, {"kind": "exploitdb"}))
    return tmp_path


def wait_job(c: Any, h: dict[str, str], job_id: str, timeout: float = 60) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/v1/ml/jobs/{job_id}", headers=h).json()
        if j["status"] in ("done", "failed"):
            return dict(j)
        time.sleep(0.3)
    raise AssertionError("el trabajo no terminó")


def test_build_dataset_end_to_end_with_profile_metadata_and_rbac(env: Env, fake_sources: Path) -> None:  # noqa: F811
    c, m = env
    with m() as db:  # 30 CVE «activos» entran a KEV a lo largo de 2025; uno ya estaba antes de empezar
        for i in range(30):
            db.add(KevEntry(cve_id=f"CVE-2024-{i:04d}", date_added=date(2025, 1, 20) + timedelta(days=9 * i), due_date=date(2026, 1, 1)))
        db.add(KevEntry(cve_id="CVE-2024-0599", date_added=date(2024, 10, 1), due_date=date(2025, 1, 1)))
        db.commit()
    url = "/api/v1/ml/datasets"
    body = {"name": "KEV 30 días", "start": "2025-01-01", "horizon_days": 30, "neg_rate": 0.5, "seed": 1}
    assert c.post(url, json=body, headers=login(c, "gerencia@radar.local")).status_code == 403
    assert c.post(url, json=body | {"start": "2025-09-01"}, headers=login(c, "analista@radar.local")).status_code == 422
    h = login(c, "analista@radar.local")
    r = c.post(url, json=body, headers=h)
    assert r.status_code == 202, r.text
    job = wait_job(c, h, r.json()["job_id"])
    assert job["status"] == "done", job["message"]
    assert job["progress"] == 100 and any("Foto" in e["msg"] for e in job["log"])  # monitoreo del avance

    d = c.get(f"{url}/{r.json()['dataset_id']}", headers=login(c, "gerencia@radar.local")).json()
    assert d["status"] == "ready" and d["params"]["split"] == "temporal 70/15/15 con embargo" and d["stats"]["embargo_days"] == 30 and "excluida" in d["stats"]["split_snapshots"] and len(d["features"]) == len(ds.FEATURES)
    assert {s["kind"] for s in d["sources"]} >= {"kev", "epss", "nvd", "exploitdb"}
    st = d["stats"]
    assert st["positives"] > 0 and set(st["by_split"]) == {"desarrollo", "validacion", "prueba"}

    p = c.get(f"{url}/{d['id']}/profile", headers=h).json()
    keys = {k["key"]: k for k in p["checks"]}
    assert keys["temporal"]["status"] == "ok" and keys["label_leak"]["status"] == "ok" and keys["duplicates"]["status"] == "ok"
    assert keys["missing_leak"]["status"] == "ok" and len(p["excluded"]) == 5
    assert keys["epss_model"]["status"] == "info" and "desarrollo ya incluye" in keys["epss_model"]["detail"]
    assert p["overview"]["universe_estimate"] > p["overview"]["rows"] and p["overview"]["prevalence_pct"] > 0
    epss_row = next(x for x in p["numeric"] if x["name"] == "epss")
    assert epss_row["auc"] > 0.9 and epss_row["median_pos"] > epss_row["median_neg"]
    assert any("PR-AUC" in t for t in p["interpretation"])

    rows = c.get(f"{url}/{d['id']}/sample", params={"label": 1, "limit": 5}, headers=h).json()
    assert len(rows) == 5 and all(x["label"] == 1 and x["kev_date"] > x["snapshot"] for x in rows)

    assert c.patch(f"{url}/{d['id']}", json={"notes": "x"}, headers=login(c, "auditor@radar.local")).status_code == 403
    e = c.patch(f"{url}/{d['id']}", json={"description": "Fotos 2025", "notes": "Revisado", "tags": ["kev", " kev ", "tesis"]}, headers=h)
    assert e.status_code == 200 and e.json()["tags"] == ["kev", "tesis"] and e.json()["notes"] == "Revisado"
    with m() as db:
        acts = {a.action for a in db.execute(select(AuditLog).where(AuditLog.module == "ml")).scalars()}
    assert acts == {"dataset_create", "dataset_edit", "access_denied"}  # los intentos sin permiso también quedan


def test_failed_build_marks_dataset_and_job(env: Env, fake_sources: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    with m() as db:
        for i in range(5):
            db.add(KevEntry(cve_id=f"CVE-2024-{i:04d}", date_added=date(2025, 6, 1) + timedelta(days=i), due_date=date(2026, 1, 1)))
        db.commit()

    def down() -> tuple[Path, dict[str, Any]]:
        raise sources.SourceError("Exploit-DB (OffSec) no disponible")

    monkeypatch.setattr(sources, "exploitdb", down)
    h = login(c, "admin@radar.local")
    r = c.post("/api/v1/ml/datasets", json={"name": "Falla", "start": "2025-01-01", "horizon_days": 30, "embargo": False}, headers=h)
    job = wait_job(c, h, r.json()["job_id"])
    assert job["status"] == "failed" and "no disponible" in job["message"]
    d = c.get(f"/api/v1/ml/datasets/{r.json()['dataset_id']}", headers=h).json()
    assert d["status"] == "failed" and "no disponible" in d["stats"]["error"]
    assert c.get(f"/api/v1/ml/datasets/{d['id']}/profile", headers=h).status_code == 409
