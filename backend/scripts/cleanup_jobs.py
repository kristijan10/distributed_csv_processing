#!/usr/bin/env python3
"""Delete finished or never-started jobs: their DB row, input/output CSVs,
and any leftover chunks/results directories, plus a safety-net delete of
the Kubernetes Job in case the automatic post-reconciliation cleanup
(job_service.cleanup_job) failed or was skipped. Running jobs are never
touched.

timings/ is never touched - backend/scripts/worker_sweep.py reads it for
benchmark analysis and must survive this script.

Run from backend/ with the venv active:

    python scripts/cleanup_jobs.py [--job-id ID ...] [--dry-run] [-y]

With no --job-id, targets every job with status Pending, Completed, or Failed.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.k8s.orchestrator import KubernetesUnavailableError, get_k8s_job, delete_k8s_job
from app.models.job import Job, JobStatus
from app.services.job_service import chunks_dir, results_dir

CLEANABLE_STATUSES = (JobStatus.PENDING, JobStatus.COMPLETED, JobStatus.FAILED)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-id", action="append", dest="job_ids", help="Target only this job id (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted and exit")
    parser.add_argument("-y", "--yes", action="store_true", help="Don't prompt for confirmation")
    return parser.parse_args()


def select_jobs(db, job_ids: list[str] | None) -> list[Job]:
    if not job_ids:
        return list(db.query(Job).filter(Job.status.in_(CLEANABLE_STATUSES)).order_by(Job.created_at).all())

    jobs = []
    for job_id in job_ids:
        job = db.get(Job, job_id)
        if job is None:
            sys.exit(f"error: no job with id {job_id}")
        if job.status not in CLEANABLE_STATUSES:
            sys.exit(f"error: job {job_id} is running (status={job.status.value}), refusing to clean it up")
        jobs.append(job)
    return jobs


def k8s_job_present(job: Job, settings) -> bool:
    try:
        return get_k8s_job(job, settings) is not None
    except KubernetesUnavailableError:
        return False


def describe(job: Job, settings) -> str:
    files = [Path(job.input_path)]
    if job.result_path:
        files.append(Path(job.result_path))
    existing = [str(p) for p in files if p.exists()]
    k8s_note = "k8s Job still present" if k8s_job_present(job, settings) else "no k8s Job"
    return f"  {job.id}  {job.original_filename}  {job.status.value}  ({k8s_note})\n" + "\n".join(
        f"    - {p}" for p in existing
    )


def cleanup_one(db, job: Job, settings) -> None:
    try:
        delete_k8s_job(job, settings)
    except Exception:
        print(f"  warning: failed to delete Kubernetes Job for {job.id}", file=sys.stderr)

    shutil.rmtree(chunks_dir(job), ignore_errors=True)
    shutil.rmtree(results_dir(job), ignore_errors=True)

    job_dir = Path(job.input_path).parent
    Path(job.input_path).unlink(missing_ok=True)
    if job.result_path:
        Path(job.result_path).unlink(missing_ok=True)

    try:
        job_dir.rmdir()  # only succeeds if empty, i.e. no timings/ was ever written
    except OSError:
        pass

    db.delete(job)
    db.commit()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    db = SessionLocal()

    try:
        jobs = select_jobs(db, args.job_ids)
        if not jobs:
            print("No jobs to clean up.")
            return

        print(f"{'Would delete' if args.dry_run else 'Will delete'} {len(jobs)} job(s):")
        for job in jobs:
            print(describe(job, settings))

        if args.dry_run:
            return

        if not args.yes:
            answer = input(f"\nDelete these {len(jobs)} job(s)? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return

        cleaned = 0
        for job in jobs:
            try:
                cleanup_one(db, job, settings)
                cleaned += 1
            except Exception as exc:
                print(f"  error: failed to clean up job {job.id}: {exc}", file=sys.stderr)

        print(f"Cleaned up {cleaned} job(s); skipped {len(jobs) - cleaned}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
