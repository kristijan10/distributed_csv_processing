import csv
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from kubernetes.client import V1Pod

from app.core.config import Settings
from app.k8s.job_builder import JOB_COMPLETION_INDEX_ANNOTATION
from app.k8s.orchestrator import (
    JobAlreadySubmittedError,
    KubernetesUnavailableError,
    delete_k8s_job,
    get_k8s_job,
    list_worker_pods,
    submit_job,
)
from app.models.job import Job, JobStatus, _utcnow
from app.services.aggregator import AggregationError, aggregate_csv
from app.services.partitioner import partition_csv

logger = logging.getLogger(__name__)


class JobValidationError(Exception):
    pass


# FastAPI runs sync path operations in a threadpool, and the frontend polls
# GET /api/jobs on a fixed interval - for a job whose aggregation takes
# longer than that interval, two overlapping polls can both see status
# RUNNING and race to aggregate/commit the same job's terminal state. One
# lock per job id serializes reconcile_status so only one poll ever drives
# a given job's RUNNING -> terminal transition.
_job_locks: dict[str, threading.Lock] = {}
_job_locks_guard = threading.Lock()


def _lock_for(job_id: str) -> threading.Lock:
    with _job_locks_guard:
        return _job_locks.setdefault(job_id, threading.Lock())


def _count_data_rows(csv_path: Path) -> int:
    with csv_path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return -1  # empty file, no header at all
        count = 0
        for line_num, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise JobValidationError(
                    f"Row {line_num} has {len(row)} columns, expected {len(header)} (based on the header)"
                )
            count += 1
        return count


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


def _wait_for_result_files(paths: list[Path], timeout: float = 15.0, interval: float = 0.2) -> None:
    """Poll for result files to appear before aggregating. `minikube mount`'s
    userspace 9p bridge can lag briefly between a worker pod exiting
    successfully and its output file becoming visible on the host side,
    especially under concurrent write load from many workers - so a file
    missing right after the Kubernetes Job reports Complete may just not
    have propagated through the bridge yet, not be truly absent.
    """
    deadline = time.monotonic() + timeout
    for path in paths:
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(interval)


def _pod_completion_index(pod: V1Pod) -> int | None:
    annotations = pod.metadata.annotations or {}
    value = annotations.get(JOB_COMPLETION_INDEX_ANNOTATION)
    return int(value) if value is not None else None


def _worker_status_from_pod(pod: V1Pod) -> dict:
    status = pod.status
    phase = (status.phase if status else None) or "Unknown"
    reason = None
    message = None
    exit_code = None
    started_at = status.start_time if status else None
    finished_at = None

    container_statuses = status.container_statuses if status else None
    if container_statuses:
        state = container_statuses[0].state
        if state.terminated:
            reason = state.terminated.reason
            message = state.terminated.message
            exit_code = state.terminated.exit_code
            started_at = state.terminated.started_at or started_at
            finished_at = state.terminated.finished_at
        elif state.waiting:
            reason = state.waiting.reason
            message = state.waiting.message
        elif state.running:
            reason = "Running"
            started_at = state.running.started_at or started_at

    return {
        "index": _pod_completion_index(pod),
        "pod_name": pod.metadata.name,
        "phase": phase,
        "reason": reason,
        "message": message,
        "exit_code": exit_code,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
    }


def _capture_worker_snapshot(job: Job, settings: Settings) -> list[dict] | None:
    """Best-effort snapshot of per-worker pod status, taken right before a
    finished job's Kubernetes Job (and its pods) get torn down by
    cleanup_job. Without this, per-worker outcomes would be unrecoverable
    once cleanup runs.
    """
    try:
        pods = list_worker_pods(job, settings)
    except KubernetesUnavailableError:
        logger.warning("Kubernetes unreachable while snapshotting workers for job %s", job.id)
        return None

    statuses = [_worker_status_from_pod(pod) for pod in pods]
    statuses.sort(key=lambda s: (s["index"] is None, s["index"]))
    return statuses


def get_job_workers(job: Job, settings: Settings) -> list[dict]:
    """Per-worker status for the job detail view. A Running job's pods are
    queried live; a finished job's pods have already been deleted by
    cleanup_job, so its persisted snapshot (captured just before teardown)
    is returned instead.
    """
    if job.status == JobStatus.PENDING:
        return []
    if job.status != JobStatus.RUNNING:
        return job.worker_snapshot or []

    try:
        pods = list_worker_pods(job, settings)
    except KubernetesUnavailableError:
        return job.worker_snapshot or []

    statuses = [_worker_status_from_pod(pod) for pod in pods]
    statuses.sort(key=lambda s: (s["index"] is None, s["index"]))
    return statuses


def aggregate_job(job: Job) -> Path:
    output_path = Path(job.input_path).parent / "output.csv"
    paths = result_paths(job)
    _wait_for_result_files(paths)
    return aggregate_csv(paths, output_path)


def cleanup_job(job: Job, settings: Settings) -> None:
    """Best-effort teardown for a finished job: delete its Kubernetes Job
    (cascading to Pods) and the intermediate chunk/result files. input.csv
    and output.csv are kept - the latter is what /result downloads.
    """
    try:
        delete_k8s_job(job, settings)
    except Exception:
        logger.exception("Failed to delete Kubernetes Job for job %s", job.id)

    shutil.rmtree(chunks_dir(job), ignore_errors=True)
    shutil.rmtree(results_dir(job), ignore_errors=True)


def run_job(db: Session, settings: Settings, job: Job) -> Job:
    if job.status != JobStatus.PENDING:
        raise JobValidationError(f"Job is not pending (status={job.status.value})")

    partition_job(job)
    try:
        submit_job(job, settings)
    except JobAlreadySubmittedError as exc:
        raise JobValidationError("Job is already running") from exc

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

    with _lock_for(job.id):
        db.refresh(job)
        if job.status != JobStatus.RUNNING:
            # Another thread already drove this job to a terminal state
            # while we were waiting for the lock.
            return job
        return _reconcile_running_job(db, settings, job)


def reconcile_from_k8s_job(db: Session, settings: Settings, job_id: str, k8s_job) -> Job | None:
    """Entry point for app.k8s.watcher: apply a Kubernetes Job object received
    from a watch.Watch() event to our matching Job row, if any. Takes the
    same per-job lock as reconcile_status so a watch event racing an
    in-flight GET /api/jobs poll for the same job can't double-apply a
    Failed/Complete transition (double aggregation, double cleanup).
    """
    job = db.get(Job, job_id)
    if job is None:
        return None

    with _lock_for(job_id):
        db.refresh(job)
        if job.status != JobStatus.RUNNING:
            return job
        return apply_k8s_job_status(db, settings, job, k8s_job)


def _reconcile_running_job(db: Session, settings: Settings, job: Job) -> Job:
    try:
        k8s_job = get_k8s_job(job, settings)
    except KubernetesUnavailableError:
        # Don't let a temporarily-unreachable cluster break listing/reading
        # jobs - just report the last known status until it's reachable again.
        logger.warning("Kubernetes unreachable while checking job %s; leaving status unchanged", job.id)
        return job
    if k8s_job is None:
        return job
    return apply_k8s_job_status(db, settings, job, k8s_job)


def apply_k8s_job_status(db: Session, settings: Settings, job: Job, k8s_job) -> Job:
    """Advance a Running job to a terminal state from an already-fetched
    Kubernetes Job object. Shared by the pull path above (_reconcile_running_job,
    driven by GET /api/jobs polling) and the push path (app.k8s.watcher's
    watch.Watch() background task, driven by Kubernetes Job events) so both
    apply the exact same Failed/Complete handling.
    """
    if job.status != JobStatus.RUNNING or k8s_job.status is None:
        return job

    conditions = k8s_job.status.conditions or []
    failed = next((c for c in conditions if c.type == "Failed" and c.status == "True"), None)
    complete = next((c for c in conditions if c.type == "Complete" and c.status == "True"), None)

    if failed is not None:
        job.worker_snapshot = _capture_worker_snapshot(job, settings)
        job.status = JobStatus.FAILED
        job.error_message = failed.message or "One or more worker pods failed"
        job.finished_at = _utcnow()
        db.commit()
        db.refresh(job)
        cleanup_job(job, settings)
    elif complete is not None:
        job.worker_snapshot = _capture_worker_snapshot(job, settings)
        try:
            output_path = aggregate_job(job)
            job.result_path = str(output_path)
            job.status = JobStatus.COMPLETED
        except AggregationError as exc:
            job.status = JobStatus.FAILED
            job.error_message = f"Aggregation failed: {exc}"
        job.finished_at = _utcnow()
        db.commit()
        db.refresh(job)
        cleanup_job(job, settings)

    return job
