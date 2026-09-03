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

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
