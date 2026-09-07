"""Tests for the watch.Watch()-based background job watcher. Kubernetes
itself is mocked out here, same as test_job_service.py - these exercise
app.k8s.watcher's event handling and its integration with
job_service.reconcile_from_k8s_job in isolation from a real cluster.
"""

import asyncio
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from app.k8s import watcher
from app.models.job import JobStatus
from app.services import job_service
from tests.test_job_service import make_condition, make_job, make_k8s_job, make_pod, write_results

# --- _job_id_from_k8s_job ---


def test_job_id_from_k8s_job_reads_label():
    k8s_job = MagicMock(metadata=MagicMock(labels={"app": "batch-worker", "job-id": "abc123"}))
    assert watcher._job_id_from_k8s_job(k8s_job) == "abc123"


def test_job_id_from_k8s_job_missing_label_returns_none():
    k8s_job = MagicMock(metadata=MagicMock(labels={"app": "batch-worker"}))
    assert watcher._job_id_from_k8s_job(k8s_job) is None


def test_job_id_from_k8s_job_handles_none_labels():
    k8s_job = MagicMock(metadata=MagicMock(labels=None))
    assert watcher._job_id_from_k8s_job(k8s_job) is None


# --- _handle_event ---


def test_handle_event_skips_object_without_job_id_label(settings):
    k8s_job = MagicMock(metadata=MagicMock(labels={}))
    with patch("app.services.job_service.reconcile_from_k8s_job") as mock_reconcile:
        watcher._handle_event(settings, {"type": "MODIFIED", "object": k8s_job})
    mock_reconcile.assert_not_called()


def test_handle_event_reconciles_matching_job(settings):
    k8s_job = MagicMock(metadata=MagicMock(labels={"job-id": "job-42"}))
    with patch("app.services.job_service.reconcile_from_k8s_job") as mock_reconcile:
        watcher._handle_event(settings, {"type": "MODIFIED", "object": k8s_job})
    assert mock_reconcile.call_count == 1
    args = mock_reconcile.call_args.args
    assert args[2] == "job-42"
    assert args[3] is k8s_job


def test_handle_event_end_to_end_transitions_job_to_completed(db_session, settings):
    # No mocking of reconcile_from_k8s_job here - a real watch event for a
    # real Running job should drive it all the way to Completed, exactly
    # like a reconcile_status poll would.
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    write_results(job, rows_per_worker=2)

    fake_k8s_job = make_k8s_job([make_condition("Complete")])
    fake_k8s_job.metadata = MagicMock(labels={"app": "batch-worker", "job-id": job.id})
    fake_pods = [make_pod(0, phase="Succeeded"), make_pod(1, phase="Succeeded")]

    with (
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
        patch("app.services.job_service.list_worker_pods", return_value=fake_pods),
    ):
        watcher._handle_event(settings, {"type": "MODIFIED", "object": fake_k8s_job})

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.result_path is not None
    mock_delete.assert_called_once()


# --- job_service.reconcile_from_k8s_job ---


def test_reconcile_from_k8s_job_unknown_job_id_is_noop(db_session, settings):
    fake_k8s_job = make_k8s_job([make_condition("Complete")])
    result = job_service.reconcile_from_k8s_job(db_session, settings, "does-not-exist", fake_k8s_job)
    assert result is None


def test_reconcile_from_k8s_job_skips_non_running_job(db_session, settings):
    job = make_job(db_session, settings)  # still Pending
    fake_k8s_job = make_k8s_job([make_condition("Complete")])
    result = job_service.reconcile_from_k8s_job(db_session, settings, job.id, fake_k8s_job)
    assert result.status == JobStatus.PENDING


def test_reconcile_from_k8s_job_transitions_to_failed(db_session, settings):
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    job_service.chunks_dir(job).mkdir(parents=True, exist_ok=True)

    fake_k8s_job = make_k8s_job([make_condition("Failed", message="deadline exceeded")])
    fake_pods = [make_pod(0, phase="Failed", reason="Error", exit_code=1), make_pod(1, phase="Succeeded")]
    with (
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
        patch("app.services.job_service.list_worker_pods", return_value=fake_pods),
    ):
        result = job_service.reconcile_from_k8s_job(db_session, settings, job.id, fake_k8s_job)

    assert result.status == JobStatus.FAILED
    assert result.error_message == "deadline exceeded"
    mock_delete.assert_called_once()


def test_reconcile_from_k8s_job_does_not_double_apply_when_already_terminal(db_session, settings):
    # Simulates a watch event racing an in-flight reconcile_status poll for
    # the same job: by the time the watcher's turn comes, the job has
    # already been driven to a terminal state and torn down once - it must
    # not aggregate/clean up a second time.
    job = make_job(db_session, settings, worker_count=2)
    job.status = JobStatus.RUNNING
    db_session.commit()
    write_results(job, rows_per_worker=2)

    fake_k8s_job = make_k8s_job([make_condition("Complete")])
    with (
        patch("app.services.job_service.delete_k8s_job") as mock_delete,
        patch("app.services.job_service.list_worker_pods", return_value=[]),
    ):
        first = job_service.reconcile_from_k8s_job(db_session, settings, job.id, fake_k8s_job)
        assert first.status == JobStatus.COMPLETED
        assert mock_delete.call_count == 1

        second = job_service.reconcile_from_k8s_job(db_session, settings, job.id, fake_k8s_job)
        assert second.status == JobStatus.COMPLETED
        assert mock_delete.call_count == 1  # not called again


# --- _stream_events ---


def test_stream_events_dispatches_each_event_to_handle_event(settings):
    fake_events = [{"type": "MODIFIED", "object": MagicMock()} for _ in range(3)]
    fake_watch = MagicMock()
    fake_watch.stream.return_value = iter(fake_events)

    with (
        patch("app.k8s.watcher.batch_v1_api", return_value=MagicMock()),
        patch("app.k8s.watcher.k8s_watch.Watch", return_value=fake_watch),
        patch("app.k8s.watcher._handle_event") as mock_handle,
    ):
        clean = watcher._stream_events(settings, threading.Event())

    assert clean is True
    assert mock_handle.call_args_list == [call(settings, e) for e in fake_events]
    fake_watch.stop.assert_called_once()  # always stopped in finally, even on a clean end


def test_stream_events_stops_early_when_stop_event_set(settings):
    fake_events = [{"type": "MODIFIED", "object": MagicMock()} for _ in range(5)]
    fake_watch = MagicMock()
    fake_watch.stream.return_value = iter(fake_events)
    stop_event = threading.Event()

    def handle_and_stop_after_first(_settings, _event):
        stop_event.set()

    with (
        patch("app.k8s.watcher.batch_v1_api", return_value=MagicMock()),
        patch("app.k8s.watcher.k8s_watch.Watch", return_value=fake_watch),
        patch("app.k8s.watcher._handle_event", side_effect=handle_and_stop_after_first) as mock_handle,
    ):
        clean = watcher._stream_events(settings, stop_event)

    assert clean is True
    assert mock_handle.call_count == 1  # stopped after the first event, not all 5
    fake_watch.stop.assert_called_once()


def test_stream_events_one_bad_event_does_not_abort_the_others(settings):
    fake_events = [{"type": "MODIFIED", "object": MagicMock()} for _ in range(3)]
    fake_watch = MagicMock()
    fake_watch.stream.return_value = iter(fake_events)

    with (
        patch("app.k8s.watcher.batch_v1_api", return_value=MagicMock()),
        patch("app.k8s.watcher.k8s_watch.Watch", return_value=fake_watch),
        patch("app.k8s.watcher._handle_event", side_effect=[RuntimeError("boom"), None, None]) as mock_handle,
    ):
        clean = watcher._stream_events(settings, threading.Event())

    assert clean is True
    assert mock_handle.call_count == 3


def test_stream_events_connection_error_returns_false(settings):
    fake_watch = MagicMock()
    fake_watch.stream.side_effect = RuntimeError("connection refused")

    with (
        patch("app.k8s.watcher.batch_v1_api", return_value=MagicMock()),
        patch("app.k8s.watcher.k8s_watch.Watch", return_value=fake_watch),
    ):
        clean = watcher._stream_events(settings, threading.Event())

    assert clean is False
    fake_watch.stop.assert_called_once()


# --- run_job_watcher ---


def test_run_job_watcher_returns_immediately_when_already_stopped(settings):
    stop_event = threading.Event()
    stop_event.set()

    with patch("app.k8s.watcher._stream_events") as mock_stream:
        asyncio.run(watcher.run_job_watcher(settings, stop_event))

    mock_stream.assert_not_called()


def test_run_job_watcher_reconnects_without_delay_after_clean_stream_end(settings):
    stop_event = threading.Event()
    call_count = 0

    def fake_stream(_settings, _stop_event):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return True  # clean end each time

    with (
        patch("app.k8s.watcher._stream_events", side_effect=fake_stream),
        patch("app.k8s.watcher.asyncio.sleep") as mock_sleep,
    ):
        asyncio.run(watcher.run_job_watcher(settings, stop_event))

    assert call_count == 2
    mock_sleep.assert_not_called()  # clean ends reconnect immediately, no backoff


def test_run_job_watcher_backs_off_after_error(settings):
    stop_event = threading.Event()
    call_count = 0

    def fake_stream(_settings, _stop_event):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return False  # errored each time

    async def fake_sleep(_seconds):
        return None

    with (
        patch("app.k8s.watcher._stream_events", side_effect=fake_stream),
        patch("app.k8s.watcher.asyncio.sleep", side_effect=fake_sleep) as mock_sleep,
    ):
        asyncio.run(watcher.run_job_watcher(settings, stop_event))

    # the 2nd error also sets stop_event before returning, so the loop
    # breaks on the post-stream stop check before it would sleep again
    assert call_count == 2
    mock_sleep.assert_called_once_with(watcher._RECONNECT_DELAY_SECONDS)
