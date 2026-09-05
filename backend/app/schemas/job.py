from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_serializer

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
    finished_at: datetime | None

    @field_serializer("created_at", "updated_at", "finished_at")
    def _serialize_as_utc(self, value: datetime | None) -> str | None:
        # Values read back from SQLite are naive (tzinfo stripped on write),
        # but every datetime the app stores is UTC (see Job._utcnow). Mark it
        # explicitly so clients don't mistake it for local time.
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()


class WorkerStatus(BaseModel):
    index: int | None
    pod_name: str | None
    phase: str
    reason: str | None
    message: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None
