from kubernetes.client import V1DeleteOptions, V1Job
from kubernetes.client.exceptions import ApiException

from app.core.config import Settings
from app.k8s.client import batch_v1_api
from app.k8s.job_builder import build_job_manifest, k8s_job_name
from app.models.job import Job


class JobAlreadySubmittedError(Exception):
    pass


def submit_job(job: Job, settings: Settings) -> str:
    api = batch_v1_api()
    manifest = build_job_manifest(job, settings)
    try:
        api.create_namespaced_job(namespace=settings.kube_namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            # Two concurrent /run calls on the same job raced past the
            # Pending check; the loser hits this instead of an unhandled 500.
            raise JobAlreadySubmittedError(f"Kubernetes Job {k8s_job_name(job)} already exists") from exc
        raise
    return k8s_job_name(job)


def get_k8s_job(job: Job, settings: Settings) -> V1Job | None:
    api = batch_v1_api()
    try:
        return api.read_namespaced_job(name=k8s_job_name(job), namespace=settings.kube_namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def delete_k8s_job(job: Job, settings: Settings) -> None:
    """Delete the Job, cascading to its Pods. No-op if already gone."""
    api = batch_v1_api()
    try:
        api.delete_namespaced_job(
            name=k8s_job_name(job),
            namespace=settings.kube_namespace,
            body=V1DeleteOptions(propagation_policy="Background"),
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
