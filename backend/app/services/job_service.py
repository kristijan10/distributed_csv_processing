import csv
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.k8s.orchestrator import get_k8s_job, submit_job
from app.models.job import Job, JobStatus
from app.services.aggregator import AggregationError, aggregate_csv
from app.services.partitioner import partition_csv


class JobValidationError(Exception):
    pass


def _count_data_rows(csv_path: Path) -> int:
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # header
        except StopIteration:
            return -1  # empty file, no header at all
        return sum(1 for _ in reader)


def create_job(db: Session, settings: Settings, file: UploadFile, worker_count: int) -> Job:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise JobValidationError("Only .csv files are supported")

    if worker_count < 1:
        raise JobValidationError("worker_count must be at least 1")
    if worker_count > settings.max_workers_per_job:
        raise JobValidationError(f"worker_count must be at most {settings.max_workers_per_job}")

    job_id = uuid.uuid4().hex
    job_dir = Path(settings.storage_dir) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / "input.csv"

    try:
        with input_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        row_count = _count_data_rows(input_path)
        if row_count < 0:
            raise JobValidationError("CSV file is empty")
        if row_count == 0:
            raise JobValidationError("CSV file has a header but no data rows")
        if worker_count > row_count:
            raise JobValidationError(
                f"worker_count ({worker_count}) cannot exceed the number of data rows ({row_count})"
            )
    except JobValidationError:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        worker_count=worker_count,
        row_count=row_count,
        original_filename=file.filename,
        input_path=str(input_path),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, settings: Settings, job_id: str) -> Job | None:
    job = db.get(Job, job_id)
    if job is not None:
        job = reconcile_status(db, settings, job)
    return job


def list_jobs(db: Session, settings: Settings) -> list[Job]:
    jobs = list(db.scalars(select(Job).order_by(Job.created_at.desc())))
    return [reconcile_status(db, settings, job) for job in jobs]


def chunks_dir(job: Job) -> Path:
    return Path(job.input_path).parent / "chunks"


def results_dir(job: Job) -> Path:
    return Path(job.input_path).parent / "results"


def partition_job(job: Job) -> list[Path]:
    """Split a job's uploaded CSV into per-worker chunk files. Chunk i is
    the input for worker i; the Kubernetes orchestration step hands each
    pod its corresponding chunk path.
    """
    return partition_csv(job.input_path, chunks_dir(job), job.worker_count)


def result_paths(job: Job) -> list[Path]:
    d = results_dir(job)
    return [d / f"result_{i:03d}.csv" for i in range(job.worker_count)]


def aggregate_job(job: Job) -> Path:
    output_path = Path(job.input_path).parent / "output.csv"
    return aggregate_csv(result_paths(job), output_path)


def run_job(db: Session, settings: Settings, job: Job) -> Job:
    if job.status != JobStatus.PENDING:
        raise JobValidationError(f"Job is not pending (status={job.status.value})")

    partition_job(job)
    submit_job(job, settings)

    job.status = JobStatus.RUNNING
    db.commit()
    db.refresh(job)
    return job


def reconcile_status(db: Session, settings: Settings, job: Job) -> Job:
    """Refresh a Running job's status from the live Kubernetes Job state.
    Pending/Completed/Failed jobs are terminal from our side and skipped -
    a Completed/Failed job's Kubernetes Job may since have been cleaned up.
    """
    if job.status != JobStatus.RUNNING:
        return job

    k8s_job = get_k8s_job(job, settings)
    if k8s_job is None or k8s_job.status is None:
        return job

    conditions = k8s_job.status.conditions or []
    failed = next((c for c in conditions if c.type == "Failed" and c.status == "True"), None)
    complete = next((c for c in conditions if c.type == "Complete" and c.status == "True"), None)

    if failed is not None:
        job.status = JobStatus.FAILED
        job.error_message = failed.message or "One or more worker pods failed"
        db.commit()
        db.refresh(job)
    elif complete is not None:
        try:
            output_path = aggregate_job(job)
            job.result_path = str(output_path)
            job.status = JobStatus.COMPLETED
        except AggregationError as exc:
            job.status = JobStatus.FAILED
            job.error_message = f"Aggregation failed: {exc}"
        db.commit()
        db.refresh(job)

    return job
