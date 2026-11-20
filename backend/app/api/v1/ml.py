"""Laboratorio de modelos (experimental). Fase 1: datasets. Nada de esto toca la detección ni el score."""

import json
import uuid
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import audit, require
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.ml import cache as mlcache
from app.ml import dataset as ds
from app.ml import jobs, profile, sources
from app.models.auth import User
from app.models.intel import KevEntry
from app.models.ml import MlDataset, MlJob, MlModel

router = APIRouter(prefix="/ml", tags=["laboratorio"])


class DatasetIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field("", max_length=2000)
    start: date = date(2025, 1, 1)
    horizon_days: Literal[30, 90, 180] = 90
    neg_rate: float = Field(0.05, ge=0.005, le=0.5)
    seed: int = Field(7, ge=0, le=1_000_000)


class DatasetPatch(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=120)
    description: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=10000)
    tags: list[str] | None = Field(None, max_length=20)


def _out(d: MlDataset) -> dict[str, Any]:
    return {"id": str(d.id), "name": d.name, "description": d.description, "notes": d.notes, "tags": d.tags,
            "status": d.status, "params": d.params, "sources": d.sources, "stats": d.stats,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}  # fmt: skip


def _job_out(j: MlJob) -> dict[str, Any]:
    return {"id": str(j.id), "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
            "log": j.log[-60:], "target_id": str(j.target_id) if j.target_id else None, "started_at": j.started_at.isoformat(),
            "finished_at": j.finished_at.isoformat() if j.finished_at else None}  # fmt: skip


def _get(db: Session, dataset_id: uuid.UUID) -> MlDataset:
    d = db.get(MlDataset, dataset_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado")
    return d


def _ready(d: MlDataset) -> Path:
    if d.status != "ready" or not d.file_path or not Path(d.file_path).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "El dataset aún no está listo")
    return Path(d.file_path)


@router.get("/features")
def features(_: User = Depends(require("ml", "view"))) -> list[dict[str, str]]:
    """Diccionario de variables: qué es cada una, de qué fuente sale y cómo se evita usar datos del futuro."""
    return ds.FEATURES


@router.get("/datasets")
def list_datasets(_: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(MlDataset).order_by(MlDataset.created_at.desc())).scalars().all()
    return [_out(d) for d in rows]


@router.post("/datasets", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("6/hour")
def create_dataset(request: Request, body: DatasetIn, actor: User = Depends(require("ml", "create")),
                   db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Construye un dataset en segundo plano (descarga EPSS, NVD y Exploit-DB; minutos la primera vez)."""
    kev_rows = db.execute(select(KevEntry.cve_id, KevEntry.date_added)).all()
    if not kev_rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El catálogo KEV está vacío: ejecute primero el flujo diario")
    kev = pd.DataFrame(kev_rows, columns=["cve", "date_added"])
    until = min(max(kev["date_added"]), date.today())
    shots = ds.snapshots(body.start, until, body.horizon_days)
    if len(shots) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Con esa fecha de inicio y horizonte hay menos de 3 fotos mensuales: adelante la fecha de inicio")  # fmt: skip
    d = MlDataset(name=body.name, description=body.description, status="building", created_by=actor.id, tags=[], sources=[],
                  params={"start": body.start.isoformat(), "until": until.isoformat(), "horizon_days": body.horizon_days,
                          "neg_rate": body.neg_rate, "seed": body.seed, "snapshots": len(shots), "split": "temporal 70/15/15"},
                  stats={})  # fmt: skip
    db.add(d)
    db.commit()
    db.refresh(d)
    dataset_id = d.id
    out_path = sources.data_dir() / "datasets" / f"{dataset_id}.csv.gz"

    def work(rep: jobs.Reporter, maker: jobs.Maker) -> None:
        res = ds.build(kev, body.start, until, body.horizon_days, body.neg_rate, body.seed, out_path, rep)
        rep(98, "Calculando el perfil (estadística y validación)")
        prof = profile.profile(ds.load(out_path), body.neg_rate)
        out_path.with_suffix("").with_suffix(".profile.json").write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        with maker() as s:
            row = s.get(MlDataset, dataset_id)
            assert row is not None
            row.status, row.sources, row.stats, row.file_path = "ready", res["sources"], res["stats"], str(out_path)
            s.commit()

    bind = db.get_bind()

    def failed(msg: str) -> None:
        with sessionmaker(bind=bind)() as s:
            row = s.get(MlDataset, dataset_id)
            if row is not None:
                row.status = "failed"
                row.stats = {"error": msg}
                s.commit()

    try:
        job = jobs.start(db, "dataset", dataset_id, actor.id, work, failed)
    except jobs.JobBusy as e:
        db.delete(d)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    audit(db, request, "ml", "dataset_create", user=actor, detail={"dataset": str(dataset_id), **d.params})
    db.commit()
    return {"dataset_id": str(dataset_id), "job_id": str(job.id)}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(_get(db, dataset_id)) | {"features": ds.FEATURES, "excluded": ds.EXCLUDED}


@router.patch("/datasets/{dataset_id}")
def edit_dataset(request: Request, dataset_id: uuid.UUID, body: DatasetPatch, actor: User = Depends(require("ml", "edit")),
                 db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Editor de metadata: nombre, descripción, notas y etiquetas (las fuentes y estadísticas no se editan)."""
    d = _get(db, dataset_id)
    changes = body.model_dump(exclude_none=True)
    if "tags" in changes:
        changes["tags"] = sorted({t.strip()[:40] for t in changes["tags"] if t.strip()})
    for k, v in changes.items():
        setattr(d, k, v)
    audit(db, request, "ml", "dataset_edit", user=actor, detail={"dataset": str(dataset_id), "fields": sorted(changes)})
    db.commit()
    db.refresh(d)
    return _out(d)


@router.get("/datasets/{dataset_id}/profile")
def dataset_profile(dataset_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    d = _get(db, dataset_id)
    path = _ready(d)
    cache = path.with_suffix("").with_suffix(".profile.json")
    if cache.exists():
        data: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return data
    prof = profile.profile(ds.load(path), float(d.params.get("neg_rate", 0.05)))  # type: ignore[arg-type]
    cache.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
    return prof


@router.get("/datasets/{dataset_id}/sample")
def dataset_sample(dataset_id: uuid.UUID, label: int | None = Query(None, ge=0, le=1), limit: int = Query(50, ge=1, le=200),
                   _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    return profile.sample(ds.load(_ready(_get(db, dataset_id))), limit, label)


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    j = db.get(MlJob, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trabajo no encontrado")
    return _job_out(j)


@router.get("/jobs")
def list_jobs(kind: str | None = None, limit: int = Query(20, ge=1, le=100), _: User = Depends(require("ml", "view")),
              db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    q = select(MlJob).order_by(MlJob.started_at.desc()).limit(limit)
    if kind:
        q = q.where(MlJob.kind == kind)
    return [_job_out(j) for j in db.execute(q).scalars().all()]


# --------------------------------------------------------------------------- Fase 2: entrenamiento
class TrainIn(BaseModel):
    dataset_id: uuid.UUID
    algorithm: Literal["logreg", "random_forest", "hgb"]
    name: str | None = Field(None, max_length=120)
    n_trials: int = Field(15, ge=2, le=60)
    seed: int = Field(7, ge=0, le=1_000_000)
    drop: list[Literal["cvss", "epss"]] = Field(default_factory=list, max_length=2)  # ablación de grupos de variables


def _model_out(m: MlModel, full: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"id": str(m.id), "dataset_id": str(m.dataset_id), "algorithm": m.algorithm, "name": m.name, "status": m.status,
           "config": m.config, "aggregate": m.aggregate, "best_params": m.best_params, "final_metrics": m.final_metrics,
           "reading": m.reading, "seconds": m.seconds, "error": m.error,
           "created_at": m.created_at.isoformat() if m.created_at else None,
           "finished_at": m.finished_at.isoformat() if m.finished_at else None}  # fmt: skip
    if full:
        out |= {"folds": m.folds, "trials": m.trials}
    return out


@router.get("/algorithms")
def algorithms(_: User = Depends(require("ml", "view"))) -> list[dict[str, Any]]:
    """Algoritmos con su descripción, hiperparámetros por defecto y espacio de búsqueda (Optuna)."""
    from app.ml import algorithms as algs

    return algs.catalog()


@router.get("/models")
def list_models(dataset_id: uuid.UUID | None = None, _: User = Depends(require("ml", "view")),
                db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    q = select(MlModel).order_by(MlModel.created_at.desc())
    if dataset_id:
        q = q.where(MlModel.dataset_id == dataset_id)
    return [_model_out(m, full=False) for m in db.execute(q).scalars().all()]


@router.get("/models/{model_id}")
def get_model(model_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    m = db.get(MlModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")
    return _model_out(m)


@router.post("/models", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("12/hour")
def train_model(request: Request, body: TrainIn, actor: User = Depends(require("ml", "create")),
                db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Entrena en segundo plano: CV anidada temporal 5×3 con Optuna en desarrollo y modelo final (ver /ml/jobs)."""
    import joblib
    import sklearn

    from app.ml import algorithms as algs
    from app.ml import training

    d = _get(db, body.dataset_id)
    path = _ready(d)
    by_split: Any = d.stats.get("by_split") or {}
    dev_snaps = int((by_split.get("desarrollo") or {}).get("snapshots", 0))
    k_out, k_in = 5, 3
    drop = tuple(sorted(set(body.drop)))
    problem = training.feasible(dev_snaps, k_out, k_in)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    m = MlModel(dataset_id=d.id, algorithm=body.algorithm, created_by=actor.id, status="training",
                name=body.name or (f"{algs.ALGORITHMS[body.algorithm]['label']} · {body.n_trials} pruebas"
                                   + (f" · sin {' ni '.join(algs.GROUPS[g]['label'] for g in drop)}" if drop else "")),
                config={"n_trials": body.n_trials, "k_out": k_out, "k_in": k_in, "seed": body.seed, "metric": "PR-AUC ponderada",
                        "cv": "anidada temporal (ventana creciente)", "target": f"entra a KEV en {d.params.get('horizon_days')} días",
                        "drop": list(drop)},
                folds=[], trials=[], aggregate={}, best_params={}, final_metrics={}, reading=[])  # fmt: skip
    db.add(m)
    db.commit()
    db.refresh(m)
    model_id = m.id
    total = (k_out + 1) * body.n_trials
    bind = db.get_bind()

    def work(rep: jobs.Reporter, maker: jobs.Maker) -> None:
        done = {"n": 0}

        def report(msg: str, event: dict[str, Any] | None) -> None:
            with maker() as s:
                row = s.get(MlModel, model_id)
                assert row is not None
                if event and "trial" in event:
                    done["n"] += 1
                    row.trials = [*row.trials, event["trial"]]
                if event and "fold" in event:
                    row.folds = [*row.folds, event["fold"]]
                s.commit()
            rep(int(95 * done["n"] / total), msg)

        rep(1, "Cargando el dataset")
        res = training.train(ds.load(path), body.algorithm, body.n_trials, k_out, k_in, body.seed, report, drop)
        rep(97, "Guardando el modelo y las predicciones")
        base = sources.data_dir() / "models"
        base.mkdir(exist_ok=True)
        model_path, preds_path = base / f"{model_id}.joblib", base / f"{model_id}.preds.csv.gz"
        joblib.dump({"pipeline": res["model"], "algorithm": body.algorithm, "params": res["best_params"], "drop": list(drop),
                     "features": algs.NUM + algs.CAT, "sklearn": sklearn.__version__}, model_path)  # fmt: skip
        res["preds"].to_csv(preds_path, index=False, compression="gzip")
        with maker() as s:
            row = s.get(MlModel, model_id)
            assert row is not None
            row.status, row.aggregate, row.best_params = "ready", res["aggregate"], res["best_params"]
            row.final_metrics, row.seconds = res["final_metrics"], res["seconds"]
            row.reading = training.notes(body.algorithm, res["aggregate"], res["final_metrics"], k_out)
            row.model_path, row.preds_path = str(model_path), str(preds_path)
            from datetime import UTC, datetime

            row.finished_at = datetime.now(UTC)
            s.commit()

    def failed(msg: str) -> None:
        with sessionmaker(bind=bind)() as s:
            row = s.get(MlModel, model_id)
            if row is not None:
                row.status, row.error = "failed", msg
                s.commit()

    try:
        job = jobs.start(db, "train", model_id, actor.id, work, failed)
    except jobs.JobBusy as e:
        db.delete(m)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    audit(db, request, "ml", "model_train", user=actor,
          detail={"model": str(model_id), "dataset": str(d.id), "algorithm": body.algorithm, "n_trials": body.n_trials,
                  "drop": list(drop)})  # fmt: skip
    db.commit()
    return {"model_id": str(model_id), "job_id": str(job.id)}


# --------------------------------------------------------------------------- Fase 3: evaluación
@router.get("/datasets/{dataset_id}/evaluation")
def evaluation(dataset_id: uuid.UUID, op: int = Query(1, description="Punto de operación: revisar el 1 % o el 5 % del universo"), user: User = Depends(require("ml", "view")),
               db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Evalúa en PRUEBA todos los modelos listos del dataset frente a EPSS y CVSS (métricas, matrices, curvas, pruebas
    estadísticas y estabilidad mensual). Si está en caché se devuelve; si no, se calcula en segundo plano y se responde
    {"status": "computing", "job_id"} (el bootstrap tarda minutos). La caché cambia sola si se entrena un modelo nuevo."""
    from app.ml import assess

    if op not in (1, 5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El punto de operación debe ser 1 o 5 (% del universo)")
    d = _get(db, dataset_id)
    _ready(d)
    rows = db.execute(select(MlModel).where(MlModel.dataset_id == d.id, MlModel.status == "ready").order_by(MlModel.created_at)).scalars().all()
    rows = [m for m in rows if m.preds_path and Path(m.preds_path).exists()]
    if not rows:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aún no hay modelos entrenados en este dataset (fase 2)")
    cache = mlcache.evaluation(d.id, [m.id for m in rows], op)
    if cache.exists():
        cached: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return cached
    model_rows: list[dict[str, Any]] = [{"id": str(m.id), "name": m.name, "algorithm": m.algorithm, "drop": m.config.get("drop", []), "folds": m.folds,
                   "preds_path": str(m.preds_path)} for m in rows]  # fmt: skip
    profile_path = Path(str(d.file_path)).with_suffix("").with_suffix(".profile.json")

    def work(rep: jobs.Reporter, maker: jobs.Maker) -> None:
        rep(3, "Cargando las predicciones de validación y prueba")
        models = [m | {"preds": pd.read_csv(m["preds_path"], compression="gzip", dtype={"cve": str})} for m in model_rows]
        res = assess.assess(models, float(op), rep)
        if profile_path.exists():
            version = {x["snapshot"]: x["epss_model"] for x in json.loads(profile_path.read_text(encoding="utf-8"))["snapshots"]}
            for row in res["stability"]:
                row["epss_model"] = version.get(row["snapshot"])
        res["models"] = [{k: m[k] for k in ("id", "name", "algorithm", "drop")} for m in model_rows]
        cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    running = db.execute(select(MlJob).where(MlJob.kind == "evaluate", MlJob.status.in_(("queued", "running")))).scalars().first()
    if running is not None:  # ya se está calculando (esta u otra evaluación): se devuelve ese trabajo
        return {"status": "computing", "job_id": str(running.id)}
    job = jobs.start(db, "evaluate", d.id, user.id, work)
    return {"status": "computing", "job_id": str(job.id)}


# --------------------------------------------------------------------------- Fase 4: explicabilidad
@router.get("/models/{model_id}/explanation")
def explanation(model_id: uuid.UUID, user: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Importancia por permutación, dependencia parcial 1D/2D, atribución por oclusión de casos y coeficientes. Si no
    está en caché, se calcula en segundo plano y responde {"status": "computing", "job_id"}."""
    import joblib

    from app.ml import explain as xp

    m = db.get(MlModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")
    if m.status != "ready" or not m.model_path or not Path(m.model_path).exists() or not m.preds_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "El modelo aún no está listo")
    d = _get(db, m.dataset_id)
    data_path = _ready(d)
    cache = mlcache.explanation(m.id)
    if cache.exists():
        cached: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8"))
        return cached
    model_path, preds_path = str(m.model_path), str(m.preds_path)
    meta = {"model": {"id": str(m.id), "name": m.name, "algorithm": m.algorithm}}

    def work(rep: jobs.Reporter, maker: jobs.Maker) -> None:
        rep(2, "Cargando el modelo, el dataset y las predicciones")
        bundle = joblib.load(model_path)
        res = xp.explain(bundle, ds.load(data_path), pd.read_csv(preds_path, compression="gzip", dtype={"cve": str}), report=rep)
        cache.write_text(json.dumps(res | meta, ensure_ascii=False), encoding="utf-8")

    running = db.execute(select(MlJob).where(MlJob.kind == "explain", MlJob.status.in_(("queued", "running")))).scalars().first()
    if running is not None:
        return {"status": "computing", "job_id": str(running.id)}
    job = jobs.start(db, "explain", m.id, user.id, work)
    return {"status": "computing", "job_id": str(job.id)}


# ---- Fase 6: inferencia individual ----------------------------------------------------------------------------------

CVE_PREFIX = r"^CVE-\d{4}-\d{0,7}$"


@lru_cache(maxsize=1)
def _frame(path: str, mtime: float) -> pd.DataFrame:
    """Dataset en memoria (~1 s de lectura): la búsqueda y la predicción de un CVE no lo releen en cada petición."""
    return ds.load(path)


@lru_cache(maxsize=3)
def _bundle(path: str, mtime: float) -> dict[str, Any]:
    import joblib

    out: dict[str, Any] = joblib.load(path)
    return out


@lru_cache(maxsize=3)
def _preds(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path, compression="gzip", dtype={"cve": str})


@lru_cache(maxsize=6)
def _setup_file(path: str, mtime: float) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return out


def _ready_model(db: Session, model_id: uuid.UUID) -> MlModel:
    m = db.get(MlModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")
    if m.status != "ready" or not m.model_path or not Path(m.model_path).exists() or not m.preds_path or not Path(m.preds_path).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "El modelo aún no está listo")
    return m


def _dataset_frame(db: Session, m: MlModel) -> tuple[MlDataset, pd.DataFrame]:
    d = _get(db, m.dataset_id)
    path = _ready(d)
    return d, _frame(str(path), path.stat().st_mtime)


def _setup(db: Session, m: MlModel) -> dict[str, Any]:
    """Calibración en validación + verificación en prueba + valores típicos. Se calcula una vez (~5 s) y queda en caché."""
    from app.ml import explain as xp
    from app.ml import inference as inf

    cache = mlcache.inference(m.id)
    if not cache.exists():
        d, df = _dataset_frame(db, m)
        dev = df[df["split"] == "desarrollo"]
        preds_path = Path(str(m.preds_path))
        try:
            cal = inf.calibrate(_preds(str(preds_path), preds_path.stat().st_mtime))
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        base = {k: (round(v, 6) if isinstance(v, float) else str(v)) for k, v in xp.baseline_values(dev).items()}
        params: Any = d.params
        config: Any = m.config
        out = {"model": {"id": str(m.id), "name": m.name, "algorithm": m.algorithm}, "dataset": {"id": str(d.id), "name": d.name},
               "horizon_days": int(params.get("horizon_days") or 90), "drop": list(config.get("drop") or []),
               "calibration": cal, "baseline": base, "options": inf.options(dev), "bands": inf.BANDS,
               "features": ds.FEATURES, "how_to_read": inf.HOW_TO_READ}  # fmt: skip
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return _setup_file(str(cache), cache.stat().st_mtime)


@router.get("/models/{model_id}/inference")
def inference_setup(model_id: uuid.UUID, _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Calibración (Platt en validación), su verificación en prueba, bandas de severidad y valores del formulario."""
    s = _setup(db, _ready_model(db, model_id))
    cal = {k: v for k, v in s["calibration"].items() if k not in ("boot", "grid")}
    return s | {"calibration": cal}


@router.get("/models/{model_id}/cases")
def inference_cases(model_id: uuid.UUID, q: str = Query(..., min_length=9, max_length=16, pattern=CVE_PREFIX),
                    _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> list[dict[str, Any]]:  # fmt: skip
    """CVE del dataset que empiezan por `q` (cada foto en que aparece). Los negativos están muestreados: no están todos."""
    _d, df = _dataset_frame(db, _ready_model(db, model_id))
    hit = df[df["cve"].str.startswith(q.upper())].sort_values(["snapshot", "cve"], ascending=[False, True]).head(25)
    recs: list[Any] = hit.to_dict("records")
    return [{"cve": r["cve"], "snapshot": str(r["snapshot"]), "split": r["split"], "label": int(r["label"])} for r in recs]


@router.get("/models/{model_id}/ranking")
def inference_ranking(model_id: uuid.UUID, snapshot: date | None = None, limit: int = Query(20, ge=5, le=100),
                      _: User = Depends(require("ml", "view")), db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """CVE con mayor probabilidad en una foto de validación o prueba, con su banda y si entraron a KEV de verdad."""
    from app.ml import inference as inf

    m = _ready_model(db, model_id)
    s = _setup(db, m)
    path = Path(str(m.preds_path))
    p = _preds(str(path), path.stat().st_mtime)
    snaps = sorted(p["snapshot"].astype(str).unique())
    shot = str(snapshot) if snapshot else snaps[-1]
    if shot not in snaps:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Esa foto no está en validación ni en prueba")
    g = p[p["snapshot"].astype(str) == shot]
    top = g.nlargest(limit, "score")
    cal = s["calibration"]
    recs: list[Any] = top.to_dict("records")
    rows = [{"cve": r["cve"], "score": float(r["score"]), "probability": float(inf.apply(cal["params"], r["score"])[0]),
             "band": inf.band_of(cal["thresholds"], float(r["score"])), "label": int(r["label"]), "split": r["split"]} for r in recs]  # fmt: skip
    return {"snapshot": shot, "snapshots": snaps, "split": str(g["split"].iloc[0]), "rows": rows,
            "hits": int(top["label"].sum()), "positives": int(g["label"].sum())}  # fmt: skip


class FeaturesIn(BaseModel):
    """Valores a mano (escenario hipotético). Vacío (null) = dato ausente, como un CVE sin CVSS de la CNA."""

    epss: float | None = Field(None, ge=0, le=1)
    percentile: float | None = Field(None, ge=0, le=1)
    epss_delta: float | None = Field(None, ge=-1, le=1)
    epss_model: str | None = Field(None, max_length=80)
    cvss: float | None = Field(None, ge=0, le=10)
    av: str | None = Field(None, max_length=80)
    ac: str | None = Field(None, max_length=80)
    pr: str | None = Field(None, max_length=80)
    ui: str | None = Field(None, max_length=80)
    cwe: str | None = Field(None, max_length=80)
    cna: str | None = Field(None, max_length=80)
    days_published: float | None = Field(None, ge=0, le=20000)
    edb_exploits: float | None = Field(None, ge=0, le=1000)
    cna_kev_prior: float | None = Field(None, ge=0, le=10000)


class PredictIn(BaseModel):
    cve: str | None = Field(None, pattern=r"^CVE-\d{4}-\d{4,7}$")
    snapshot: date | None = None
    values: FeaturesIn | None = None


@router.post("/models/{model_id}/predict")
@limiter.limit("120/minute")
def inference_predict(request: Request, model_id: uuid.UUID, body: PredictIn, actor: User = Depends(require("ml", "view")),
                      db: Session = Depends(get_db)) -> dict[str, Any]:  # fmt: skip
    """Predicción individual: probabilidad calibrada con IC 90 %, severidad, posición en el universo y explicación."""
    from app.ml import algorithms as algs
    from app.ml import inference as inf

    if (body.cve is None) == (body.values is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indique un CVE del dataset o los valores a mano (uno de los dos)")
    m = _ready_model(db, model_id)
    s = _setup(db, m)
    bundle = _bundle(str(m.model_path), Path(str(m.model_path)).stat().st_mtime)
    case: dict[str, Any] | None = None
    if body.cve is not None:
        _, df = _dataset_frame(db, m)
        rows = df[df["cve"] == body.cve]
        if body.snapshot is not None:
            rows = rows[rows["snapshot"] == body.snapshot]
        if rows.empty:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese CVE no está en el dataset para esa foto (los negativos están muestreados)")
        r: Any = rows.sort_values("snapshot").iloc[-1].to_dict()
        kev = r["kev_date"] if pd.notna(r["kev_date"]) else None
        case = {"cve": r["cve"], "snapshot": str(r["snapshot"]), "split": r["split"], "label": int(r["label"]),
                "kev_date": str(kev) if kev else None, "days_to_kev": (kev - r["snapshot"]).days if kev else None}  # fmt: skip
        frame = inf.frame({c: (None if pd.isna(r[c]) else r[c]) for c in algs.NUM + algs.CAT})
    else:
        assert body.values is not None
        frame = inf.frame(body.values.model_dump())
    res = inf.predict(bundle, frame, s["calibration"], s["baseline"])
    first: Any = frame.iloc[0].to_dict()
    vals = {c: (None if pd.isna(first[c]) else (round(float(first[c]), 6) if c in algs.NUM else str(first[c]))) for c in algs.NUM + algs.CAT}
    audit(db, request, "ml", "model_predict", user=actor, detail={"model": str(m.id), "cve": body.cve or "manual"})
    db.commit()
    return {"result": res, "case": case, "values": vals, "reading": inf.reading(res, s["calibration"], s["horizon_days"], case)}
