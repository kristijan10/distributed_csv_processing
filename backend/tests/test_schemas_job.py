from datetime import datetime, timedelta, timezone

from app.models.job import JobStatus
from app.schemas.job import JobRead


def make_job_read(*, started_at=None, finished_at=None, row_count=100):
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return JobRead(
        id="job-1",
        status=JobStatus.COMPLETED,
        worker_count=4,
        row_count=row_count,
        original_filename="input.csv",
        error_message=None,
        created_at=created_at,
        updated_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )


def test_computed_fields_none_when_job_never_started():
    job_read = make_job_read()
    assert job_read.execution_time_s is None
    assert job_read.queue_time_s is None
    assert job_read.throughput_rows_per_s is None


def test_computed_fields_none_while_still_running():
    started_at = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    job_read = make_job_read(started_at=started_at)
    assert job_read.execution_time_s is None
    assert job_read.throughput_rows_per_s is None
    assert job_read.queue_time_s == 5.0


def test_computed_fields_calculated_when_terminal():
    started_at = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(seconds=20)
    job_read = make_job_read(started_at=started_at, finished_at=finished_at, row_count=100)

    assert job_read.queue_time_s == 5.0
    assert job_read.execution_time_s == 20.0
    assert job_read.throughput_rows_per_s == 5.0
