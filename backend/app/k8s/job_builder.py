import math

from kubernetes import client

from app.core.config import Settings
from app.models.job import Job

JOB_COMPLETION_INDEX_ANNOTATION = "batch.kubernetes.io/job-completion-index"

# Labels every Job we create carries, and the selector that finds them all
# back - shared with k8s/orchestrator.py (batched status listing) and
# k8s/watcher.py (the watch stream) so all three stay in lockstep.
JOB_ID_LABEL = "job-id"
JOB_LABEL_SELECTOR = "app=batch-worker"


def k8s_job_name(job: Job) -> str:
    return f"batch-job-{job.id}"


def _active_deadline_seconds(job: Job, settings: Settings) -> int:
    """Scale the deadline with how much work each worker actually has, so a
    large-but-healthy job isn't force-failed at the same threshold as a
    genuinely stuck one, and a small job still fails fast. See
    Settings.job_deadline_base_seconds / job_deadline_seconds_per_row.
    """
    rows_per_worker = math.ceil(job.row_count / job.worker_count)
    return settings.job_deadline_base_seconds + math.ceil(rows_per_worker * settings.job_deadline_seconds_per_row)


def build_job_manifest(job: Job, settings: Settings) -> client.V1Job:
    labels = {"app": "batch-worker", JOB_ID_LABEL: job.id}

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
        client.V1EnvVar(name="NOOP_TRANSFORM", value="1" if settings.noop_transform else "0"),
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
        active_deadline_seconds=_active_deadline_seconds(job, settings),
        template=pod_template,
    )

    return client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=k8s_job_name(job), labels=labels),
        spec=job_spec,
    )
