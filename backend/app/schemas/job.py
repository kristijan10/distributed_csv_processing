from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, computed_field, field_serializer

from app.models.job import JobStatus


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: JobStatus
    worker_count: int
    row_count: int
    original_filename: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @field_serializer("created_at", "updated_at", "started_at", "finished_at")
    def _serialize_as_utc(self, value: datetime | None) -> str | None:
        # Values read back from SQLite are naive (tzinfo stripped on write),
        # but every datetime the app stores is UTC (see Job._utcnow). Mark it
        # explicitly so clients don't mistake it for local time.
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    @computed_field
    @property
    def execution_time_s(self) -> float | None:
        # Wall time actually spent running (Running -> terminal), excluding
        # time the job spent queued in Pending.
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @computed_field
    @property
    def queue_time_s(self) -> float | None:
        if self.started_at is None:
            return None
        return (self.started_at - self.created_at).total_seconds()

    @computed_field
    @property
    def throughput_rows_per_s(self) -> float | None:
        exec_s = self.execution_time_s
        if not exec_s:
            return None
        return self.row_count / exec_s


class WorkerStatus(BaseModel):
    index: int | None
    pod_name: str | None
    phase: str
    reason: str | None
    message: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None
