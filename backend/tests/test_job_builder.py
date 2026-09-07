from types import SimpleNamespace

from app.k8s.job_builder import _active_deadline_seconds, build_job_manifest


def make_job(row_count, worker_count):
    return SimpleNamespace(id="job-1", row_count=row_count, worker_count=worker_count)


def test_deadline_grows_with_rows_per_worker(settings):
    small = _active_deadline_seconds(make_job(row_count=10, worker_count=1), settings)
    large = _active_deadline_seconds(make_job(row_count=10_000, worker_count=1), settings)
    assert large > small


def test_deadline_shrinks_as_worker_count_increases_for_fixed_rows(settings):
    few_workers = _active_deadline_seconds(make_job(row_count=1000, worker_count=1), settings)
    many_workers = _active_deadline_seconds(make_job(row_count=1000, worker_count=10), settings)
    assert many_workers < few_workers


def test_deadline_never_below_base(settings):
    deadline = _active_deadline_seconds(make_job(row_count=1, worker_count=1), settings)
    assert deadline >= settings.job_deadline_base_seconds


def test_build_job_manifest_sets_computed_deadline(settings):
    job = make_job(row_count=100, worker_count=4)
    manifest = build_job_manifest(job, settings)
    assert manifest.spec.active_deadline_seconds == _active_deadline_seconds(job, settings)
