import csv
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.job import Job, JobStatus
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


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(db: Session) -> list[Job]:
    return list(db.scalars(select(Job).order_by(Job.created_at.desc())))


def chunks_dir(job: Job) -> Path:
    return Path(job.input_path).parent / "chunks"


def partition_job(job: Job) -> list[Path]:
    """Split a job's uploaded CSV into per-worker chunk files. Chunk i is
    the input for worker i; the Kubernetes orchestration step (next
    milestone) hands each pod its corresponding chunk path.
    """
    return partition_csv(job.input_path, chunks_dir(job), job.worker_count)
