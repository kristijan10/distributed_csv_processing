from functools import lru_cache

from kubernetes import client, config

from app.core.config import get_settings


@lru_cache
def _load_kube_config() -> None:
    settings = get_settings()
    config.load_kube_config(context=settings.kube_context)


def batch_v1_api() -> client.BatchV1Api:
    _load_kube_config()
    return client.BatchV1Api()


def core_v1_api() -> client.CoreV1Api:
    _load_kube_config()
    return client.CoreV1Api()
