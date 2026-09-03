from app.core.config import Settings
from app.k8s.client import batch_v1_api
from app.k8s.job_builder import build_job_manifest, k8s_job_name
from app.models.job import Job


def submit_job(job: Job, settings: Settings) -> str:
    api = batch_v1_api()
    manifest = build_job_manifest(job, settings)
    api.create_namespaced_job(namespace=settings.kube_namespace, body=manifest)
    return k8s_job_name(job)
