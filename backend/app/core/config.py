from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Distributed Batch Processing Platform"
    api_prefix: str = "/api"

    # Local Kubernetes cluster context (minikube/kind). None = use kubeconfig default context.
    kube_context: str | None = None
    kube_namespace: str = "default"

    # Where uploaded CSVs, partitioned chunks, and results are stored on the backend host.
    storage_dir: str = "./storage"

    # Job metadata persistence.
    database_url: str = "sqlite:///./app.db"

    # Sanity bound on user-chosen worker count (not a resource/CPU/RAM config).
    max_workers_per_job: int = 32

    # Worker container image (built and `minikube image load`-ed locally; see worker/).
    worker_image: str = "batch-worker:latest"

    # Path where storage_dir is made visible inside the cluster, via
    # `minikube mount <storage_dir>:<data_mount_path>` for local dev.
    data_mount_path: str = "/data"

    # Upper bound on how long a Job may run before Kubernetes force-fails it.
    # Without this, a Job whose pods never reach a terminal phase (e.g. stuck
    # in ImagePullBackOff or Pending) has no Failed condition to reconcile on
    # and stays Running forever.
    job_active_deadline_seconds: int = 300

    # Temporary experiment switch: when true, workers skip the per-row
    # transform and echo their chunk back unchanged, to isolate I/O time
    # from compute time in the worker-count sweep.
    noop_transform: bool = False

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
