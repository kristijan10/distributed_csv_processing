"""Job lifecycle tests with the Kubernetes API mocked out. These exercise
job_service's own logic (state transitions, race handling, cleanup) in
isolation from a real cluster - the real cluster path is covered by
scripts/e2e_demo.py instead.
"""

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.k8s.orchestrator import JobAlreadySubmittedError
from app.models.job import Job, JobStatus
from app.services import job_service
from app.services.job_service import JobValidationError
from tests.conftest import make_csv


def make_job(db_session, settings, worker_count=2, rows=4):
    job_id = uuid.uuid4().hex
    job_dir = Path(settings.storage_dir) / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / "input.csv"
    make_csv(input_path, ["id", "val"], [[i, i * 10] for i in range(1, rows + 1)])

    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        worker_count=worker_count,
        row_count=rows,
        original_filename="input.csv",
        input_path=str(input_path),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def make_condition(type_, status="True", message=None):
    return SimpleNamespace(type=type_, status=status, message=message)


def make_k8s_job(conditions):
    return SimpleNamespace(status=SimpleNamespace(conditions=conditions))


def write_results(job, rows_per_worker=2):
    results_dir = job_service.results_dir(job)
    results_dir.mkdir(parents=True, exist_ok=True)
    for i in range(job.worker_count):
        rows = [[i * 100 + r, r] for r in range(rows_per_worker)]
        make_csv(results_dir / f"result_{i:03d}.csv", ["id", "val"], rows)


# --- run_job ---


def test_run_job_transitions_to_running_and_partitions(db_session, settings):
    job = make_job(db_session, settings, worker_count=2, rows=4)
    with patch("app.services.job_service.submit_job") as mock_submit:
        result = job_service.run_job(db_session, settings, job)

    mock_submit.assert_called_once()
    assert result.status == JobStatus.RUNNING
    chunks = list(job_service.chunks_dir(job).glob("*.csv"))
    assert len(chunks) == 2


def test_run_job_rejects_non_pending_job(db_session, settings):
    job = make_job(db_session, settings)
    job.status = JobStatus.RUNNING
    db_session.commit()

    with pytest.raises(JobValidationError, match="not pending"):
        job_service.run_job(db_session, settings, job)


def test_run_job_translates_race_condition_cleanly(db_session, settings):
    job = make_job(db_session, settings)
    with patch("app.services.job_service.submit_job", side_effect=JobAlreadySubmittedError("boom")):
        with pytest.raises(JobValidationError, match="already running"):
            job_service.run_job(db_session, settings, job)

    # the losing request must not have corrupted the job's status
    db_session.refresh(job)
    assert job.status == JobStatus.PENDING


# --- reconcile_status ---


def test_reconcile_status_skips_non_running_jobs(db_session, settings):
    job = make_job(db_session, settings)  # still Pending
    with patch("app.services.job_service.get_k8s_job") as mock_get:
        result = job_service.reconcile_status(db_session, settings, job)

    mock_get.assert_not_called()
    assert result.status == JobStatus.PENDING


def test_reconcile_status_leaves_running_when_no_k8s_job_found(db_session, settings):
    job = make_job(db_session, settings)
    job.status = JobStatus.RUNNING
    db_session.commit()

    with patch("app.services.job_service.get_k8s_job", return_value=None):
        result = job_service.reconcile_status(db_session, settings, job)

    assert result.status == JobStatus.RUNNING


def test_reconcile_status_transitions_to_failed_and_cleans_up(db_session, settings):
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    job_service.chunks_dir(job).mkdir(parents=True, exist_ok=True)
    (job_service.chunks_dir(job) / "chunk_000.csv").write_text("id\n1\n")

    fake_job = make_k8s_job([make_condition("Failed", message="Job was active longer than specified deadline")])
    with (
        patch("app.services.job_service.get_k8s_job", return_value=fake_job),
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
    ):
        result = job_service.reconcile_status(db_session, settings, job)

    assert result.status == JobStatus.FAILED
    assert result.error_message == "Job was active longer than specified deadline"
    mock_delete.assert_called_once()
    assert not job_service.chunks_dir(job).exists()


def test_reconcile_status_transitions_to_completed_and_aggregates(db_session, settings):
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    write_results(job, rows_per_worker=2)

    fake_job = make_k8s_job([make_condition("Complete")])
    with (
        patch("app.services.job_service.get_k8s_job", return_value=fake_job),
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
    ):
        result = job_service.reconcile_status(db_session, settings, job)

    assert result.status == JobStatus.COMPLETED
    assert result.result_path is not None
    output_lines = Path(result.result_path).read_text().splitlines()
    assert output_lines[0] == "id,val"
    assert len(output_lines) == 1 + 2 * 2  # header + 2 workers * 2 rows each
    mock_delete.assert_called_once()
    assert not job_service.results_dir(job).exists()
    assert Path(result.result_path).exists()  # output.csv itself must survive cleanup


def test_reconcile_status_aggregation_failure_marks_job_failed(db_session, settings):
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    # deliberately don't write any result files -> aggregation must fail

    fake_job = make_k8s_job([make_condition("Complete")])
    with (
        patch("app.services.job_service.get_k8s_job", return_value=fake_job),
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
    ):
        result = job_service.reconcile_status(db_session, settings, job)

    assert result.status == JobStatus.FAILED
    assert "Aggregation failed" in result.error_message
    mock_delete.assert_called_once()  # cleanup still runs even when aggregation fails


# --- cleanup_job ---


def test_cleanup_job_survives_k8s_deletion_error(db_session, settings):
    job = make_job(db_session, settings, worker_count=1)
    job_service.chunks_dir(job).mkdir(parents=True, exist_ok=True)
    (job_service.chunks_dir(job) / "chunk_000.csv").write_text("id\n1\n")

    with patch("app.services.job_service.delete_k8s_job", side_effect=RuntimeError("cluster unreachable")):
        job_service.cleanup_job(job, settings)  # must not raise

    assert not job_service.chunks_dir(job).exists()
