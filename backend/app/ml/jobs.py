"""Trabajos en segundo plano del laboratorio (un hilo por trabajo, progreso en la tabla ml_jobs).

El backend corre en un solo proceso de uvicorn, así que basta un hilo. Si el contenedor se reinicia a mitad de un
trabajo, al arrancar se marca como fallido («interrumpido») para que la UI no lo muestre en curso para siempre."""

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.ml import MlJob

Maker = sessionmaker[Session]

MAX_LOG = 200
_lock = threading.Lock()


class JobBusy(RuntimeError):
    """Ya hay un trabajo del mismo tipo en curso."""


class Reporter:
    """Publica el avance de un trabajo (porcentaje + mensaje + bitácora corta) en su propia sesión."""

    def __init__(self, job_id: uuid.UUID, maker: Maker) -> None:
        self.job_id, self.maker = job_id, maker

    def __call__(self, pct: int, msg: str) -> None:
        with self.maker() as db:
            job = db.get(MlJob, self.job_id)
            if job is None:
                return
            job.progress, job.message = max(0, min(100, pct)), msg[:300]
            job.log = [*job.log, {"t": datetime.now(UTC).isoformat(), "pct": job.progress, "msg": msg[:300]}][-MAX_LOG:]
            db.commit()


def start(db: Session, kind: str, target_id: uuid.UUID | None, user_id: uuid.UUID | None,
          work: Callable[[Reporter, Maker], None], on_error: Callable[[str], None] | None = None) -> MlJob:  # fmt: skip
    """Crea el trabajo y lo lanza en un hilo. `work` recibe el reportero de progreso y una fábrica de sesiones ligada a
    la misma conexión que la petición (mismo esquema: en los tests, el temporal)."""
    maker: Maker = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with _lock:
        busy = db.execute(select(MlJob).where(MlJob.kind == kind, MlJob.status.in_(("queued", "running")))).scalars().first()
        if busy is not None:
            raise JobBusy(f"Ya hay un trabajo «{kind}» en curso ({busy.progress} %): espere a que termine")
        job = MlJob(kind=kind, status="running", target_id=target_id, created_by=user_id, message="Iniciando", log=[])
        db.add(job)
        db.commit()
        db.refresh(job)

    def run() -> None:
        rep = Reporter(job.id, maker)
        try:
            work(rep, maker)
            _finish(maker, job.id, "done", 100, "Terminado")
        except Exception as e:  # noqa: BLE001 (el error se informa en el trabajo, sin tumbar el proceso)
            msg = f"{e.__class__.__name__}: {e}"[:300]
            _finish(maker, job.id, "failed", None, msg)
            if on_error is not None:
                on_error(msg)

    threading.Thread(target=run, name=f"ml-{kind}-{job.id}", daemon=True).start()
    return job


def _finish(maker: Maker, job_id: uuid.UUID, status: str, pct: int | None, msg: str) -> None:
    with maker() as db:
        job = db.get(MlJob, job_id)
        if job is None:
            return
        job.status, job.message, job.finished_at = status, msg, datetime.now(UTC)
        if pct is not None:
            job.progress = pct
        job.log = [*job.log, {"t": datetime.now(UTC).isoformat(), "pct": job.progress, "msg": msg}][-MAX_LOG:]
        db.commit()


def recover_stale(db: Session) -> int:
    """Al arrancar: los trabajos que quedaron «en curso» se dan por interrumpidos."""
    res = db.execute(
        update(MlJob).where(MlJob.status.in_(("queued", "running")))
        .values(status="failed", message="Interrumpido por un reinicio del servicio", finished_at=datetime.now(UTC))
    )  # fmt: skip
    from app.models.ml import MlDataset

    db.execute(update(MlDataset).where(MlDataset.status == "building").values(status="failed"))
    return int(res.rowcount or 0)  # type: ignore[attr-defined]
