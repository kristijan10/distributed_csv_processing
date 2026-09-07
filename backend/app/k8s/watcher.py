import asyncio
import logging
import threading
from typing import Any

from kubernetes import watch as k8s_watch
from kubernetes.client.exceptions import ApiException

from app.core.config import Settings
from app.core.db import SessionLocal
from app.k8s.client import batch_v1_api
from app.k8s.job_builder import JOB_ID_LABEL, JOB_LABEL_SELECTOR

logger = logging.getLogger(__name__)

# How long a single watch connection is allowed to stay open before the
# apiserver closes it and _stream_events() reconnects. Bounds how long a
# stale connection (e.g. after the apiserver silently drops it) can go
# unnoticed, and doubles as the interval at which shutdown is noticed.
_WATCH_TIMEOUT_SECONDS = 60

# Backoff before reconnecting after the stream ends with an error (a clean,
# timed-out stream reconnects immediately instead).
_RECONNECT_DELAY_SECONDS = 5


def _job_id_from_k8s_job(k8s_job: Any) -> str | None:
    labels = k8s_job.metadata.labels or {}
    return labels.get(JOB_ID_LABEL)


def _handle_event(settings: Settings, event: dict) -> None:
    from app.services.job_service import reconcile_from_k8s_job

    k8s_job = event["object"]
    job_id = _job_id_from_k8s_job(k8s_job)
    if job_id is None:
        return

    db = SessionLocal()
    try:
        reconcile_from_k8s_job(db, settings, job_id, k8s_job)
    finally:
        db.close()


def _stream_events(settings: Settings, stop_event: threading.Event) -> bool:
    """Run one watch connection to completion. Returns True if it ended
    cleanly (timeout or requested stop) and False if it ended on an error,
    so the caller knows whether to reconnect immediately or back off.
    """
    api = batch_v1_api()
    watch = k8s_watch.Watch()
    try:
        for event in watch.stream(
            api.list_namespaced_job,
            namespace=settings.kube_namespace,
            label_selector=JOB_LABEL_SELECTOR,
            timeout_seconds=_WATCH_TIMEOUT_SECONDS,
        ):
            if stop_event.is_set():
                break
            try:
                _handle_event(settings, event)
            except Exception:
                logger.exception("Failed to process Kubernetes Job watch event: %r", event)
        return True
    except ApiException as exc:
        logger.warning("Kubernetes Job watch stream ended with API error: %s", exc)
        return False
    except Exception:
        logger.exception("Kubernetes Job watch stream failed")
        return False
    finally:
        watch.stop()


async def run_job_watcher(settings: Settings, stop_event: threading.Event) -> None:
    """Background task started at app startup (see app.main's lifespan).

    Keeps our DB's Running jobs in sync with Kubernetes by watching Job
    resources instead of relying solely on job_service.reconcile_status
    being pulled by a GET /api/jobs poll. watch.Watch().stream() is a
    blocking call, so each connection's iteration runs on a worker thread
    via asyncio.to_thread while this coroutine just supervises and
    reconnects it - that's what makes this a "background asyncio task"
    around a synchronous, thread-based client.

    reconcile_status is left in place as a pull-based fallback: a watch
    connection only reports changes from the moment it's opened, so a Job
    that already reached a terminal state before this task started (e.g.
    right after a backend restart) would otherwise never be reconciled.
    """
    while not stop_event.is_set():
        clean = await asyncio.to_thread(_stream_events, settings, stop_event)
        if stop_event.is_set():
            break
        if not clean:
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
