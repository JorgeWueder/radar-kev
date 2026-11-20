import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import joblib
import pytest
from docx import Document
from openpyxl import load_workbook
from threadpoolctl import threadpool_limits

from app.core.config import get_settings
from app.ml import assess, explain, profile, training
from app.ml import cache as mlcache
from app.models.ml import MlDataset, MlModel
from tests.conftest import login
from tests.test_intel_api import env  # noqa: F401
from tests.test_ml_training import synthetic
from tests.test_reports import Env, pdf_text


@pytest.fixture(autouse=True)
def _one_thread() -> Iterator[None]:
    with threadpool_limits(1):
        yield


def setup_lab(m: Any, tmp: Path, with_caches: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    df = synthetic(rows=300, seed=5)
    ds_path = tmp / "ds.csv.gz"
    df.to_csv(ds_path, index=False, compression="gzip")
    prof = profile.profile(df, 0.1)
    ds_path.with_suffix("").with_suffix(".profile.json").write_text(json.dumps(prof, ensure_ascii=False, default=str), encoding="utf-8")
    res = training.train(df, "logreg", 2, 5, 3, 1, lambda msg, e: None)
    model_path, preds_path = tmp / "m.joblib", tmp / "m.preds.csv.gz"
    joblib.dump({"pipeline": res["model"], "drop": []}, model_path)
    res["preds"].to_csv(preds_path, index=False, compression="gzip")
    did, mid = uuid.uuid4(), uuid.uuid4()
    with m() as db:
        db.add(MlDataset(id=did, name="Sintético", status="ready", file_path=str(ds_path), params={"start": "2025-01-01", "horizon_days": 90, "split": "temporal 70/15/15"},
                         stats={}, tags=[], sources=[{"kind": "epss", "name": "FIRST EPSS", "license": "Uso libre", "file": "epss.csv.gz", "bytes": 2_000_000, "sha256": "ab" * 32}]))  # fmt: skip
        db.flush()
        db.add(MlModel(id=mid, dataset_id=did, algorithm="logreg", name="Regresión logística", status="ready", seconds=12.0,
                       config={"n_trials": 2, "k_out": 5, "k_in": 3, "seed": 1, "metric": "PR-AUC", "cv": "anidada temporal", "target": "entra a KEV", "drop": []},
                       folds=res["folds"], aggregate=res["aggregate"], trials=res["trials"], best_params=res["best_params"], final_metrics=res["final_metrics"],
                       reading=["Lectura de prueba."], model_path=str(model_path), preds_path=str(preds_path)))  # fmt: skip
        db.commit()
    if with_caches:
        models = [{"id": str(mid), "name": "Regresión logística", "algorithm": "logreg", "drop": [], "folds": res["folds"], "preds": res["preds"]}]
        ev = assess.assess(models, 1.0) | {"models": [{"id": str(mid), "name": "Regresión logística", "algorithm": "logreg", "drop": []}]}
        mlcache.evaluation(did, [mid], 1).write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
        xp = explain.explain({"pipeline": res["model"], "drop": []}, df, res["preds"], repeats=1, pdp_rows=200, n_cases=2)
        mlcache.explanation(mid).write_text(json.dumps(xp, ensure_ascii=False), encoding="utf-8")
    return did, mid


def get(c: Any, h: dict[str, str], key: str, fmt: str, **params: Any) -> Any:
    return c.post(f"/api/v1/reports/{key}", params={"fmt": fmt, **params}, headers=h)


def test_lab_reports_in_every_format(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    did, mid = setup_lab(m, tmp_path)
    h = login(c, "analista@radar.local")
    cases = {
        "ml_dataset": ({"dataset_id": did}, ["Partición temporal 70/15/15", "Validación del dataset", "descartadas por fuga", "Fuentes y licencias", "Diccionario"]),
        "ml_training": ({"model_id": mid}, ["Configuración del entrenamiento", "Espacio de búsqueda", "Resultado por pliegue", "Pruebas de Optuna"]),
        "ml_evaluation": ({"dataset_id": did, "op": 1}, ["Métricas por modelo", "Matrices de confusión", "Friedman", "Estabilidad", "Curvas ROC"]),
        "ml_explain": ({"model_id": mid}, ["Equivalencias con el Promptuario", "Importancia por grupo", "Explicaciones caso por caso", "Dependencia parcial"]),
    }  # fmt: skip
    for key, (params, parts) in cases.items():
        pdf = get(c, h, key, "pdf", **params)
        assert pdf.status_code == 200, (key, pdf.text[:200])
        text = " ".join(pdf_text(pdf.content).split())
        for part in parts:
            assert part in text, (key, part)
        doc = Document(io.BytesIO(get(c, h, key, "docx", **params).content))
        assert len(doc.inline_shapes) >= 1, key  # figuras PNG a 600 DPI
        wb = load_workbook(io.BytesIO(get(c, h, key, "xlsx", **params).content))
        assert wb.sheetnames[0] == "Resumen" and any(ws._charts for ws in wb.worksheets), key
    assert len(c.get("/api/v1/reports/catalog", headers=h).json()) == 15


def test_lab_reports_explain_what_is_missing(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, m = env
    monkeypatch.setattr(get_settings(), "ml_data_dir", str(tmp_path))
    did, mid = setup_lab(m, tmp_path, with_caches=False)
    h = login(c, "analista@radar.local")
    r = get(c, h, "ml_evaluation", "pdf", dataset_id=did)
    assert r.status_code == 422 and "3 · Evaluación" in r.json()["detail"]
    r = get(c, h, "ml_explain", "pdf", model_id=mid)
    assert r.status_code == 422 and "4 · Explicabilidad" in r.json()["detail"]
    assert get(c, h, "ml_training", "pdf").status_code == 422  # falta el modelo
    assert get(c, h, "ml_dataset", "pdf", dataset_id=uuid.uuid4()).status_code == 422
    assert get(c, h, "ml_evaluation", "pdf", dataset_id=did, op=3).status_code == 422
