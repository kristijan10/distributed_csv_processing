from kubernetes import client

from app.core.config import Settings
from app.models.job import Job

JOB_COMPLETION_INDEX_ANNOTATION = "batch.kubernetes.io/job-completion-index"


def k8s_job_name(job: Job) -> str:
    return f"batch-job-{job.id}"


def build_job_manifest(job: Job, settings: Settings) -> client.V1Job:
    labels = {"app": "batch-worker", "job-id": job.id}

    env = [
        client.V1EnvVar(name="JOB_ID", value=job.id),
        client.V1EnvVar(name="DATA_ROOT", value=settings.data_mount_path),
        client.V1EnvVar(
            name="JOB_COMPLETION_INDEX",
            value_from=client.V1EnvVarSource(
                field_ref=client.V1ObjectFieldSelector(
                    field_path=f"metadata.annotations['{JOB_COMPLETION_INDEX_ANNOTATION}']"
                )
            ),
        ),
    ]

    volume = client.V1Volume(
        name="shared-storage",
        host_path=client.V1HostPathVolumeSource(path=settings.data_mount_path, type="Directory"),
    )
    volume_mount = client.V1VolumeMount(name="shared-storage", mount_path=settings.data_mount_path)

    container = client.V1Container(
        name="worker",
        image=settings.worker_image,
        image_pull_policy="IfNotPresent",
        env=env,
        volume_mounts=[volume_mount],
    )

    pod_template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels=labels),
        spec=client.V1PodSpec(
            containers=[container],
            volumes=[volume],
            restart_policy="Never",
        ),
    )

    job_spec = client.V1JobSpec(
        completions=job.worker_count,
        parallelism=job.worker_count,
        completion_mode="Indexed",
        backoff_limit=0,
        active_deadline_seconds=settings.job_active_deadline_seconds,
        template=pod_template,
    )

    return client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=k8s_job_name(job), labels=labels),
        spec=job_spec,
    )
