from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
