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

    # Upper bound on how long a Job may run before Kubernetes force-fails it,
    # computed per-job as job_deadline_base_seconds + ceil(row_count /
    # worker_count) * job_deadline_seconds_per_row (see k8s/job_builder.py).
    # Without a deadline at all, a Job whose pods never reach a terminal
    # phase (e.g. stuck in ImagePullBackOff or Pending) has no Failed
    # condition to reconcile on and stays Running forever; a flat deadline
    # instead force-fails legitimately slow large jobs at the same threshold
    # as a genuinely stuck tiny one, so it scales with the rows each worker
    # has to get through.
    job_deadline_base_seconds: int = 60
    job_deadline_seconds_per_row: float = 0.5

    # Temporary experiment switch: when true, workers skip the per-row
    # transform and echo their chunk back unchanged, to isolate I/O time
    # from compute time in the worker-count sweep.
    noop_transform: bool = False

    # Simulated per-row "work" for the baseline (non-noop) transform:
    # workers sleep(compute_fixed_s + compute_per_row_s * rows_in_chunk)
    # instead of a flat constant, modeling a fixed per-pod setup cost (e.g.
    # a model/connection load) plus a cost that scales with how many rows
    # land in that worker's chunk - so, unlike a flat sleep, compute time
    # actually shrinks as worker_count grows and chunks get smaller. See
    # worker/main.py.
    compute_fixed_s: float = 0.3
    compute_per_row_s: float = 0.000001

    # Where scripts/worker_sweep.py writes its {mode}_sweep.csv results, and
    # where the /api/metrics/sweep endpoints read them back from.
    sweep_results_dir: str = "./scripts/sweep_results"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
