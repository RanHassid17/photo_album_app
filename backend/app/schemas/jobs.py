from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import JobKind, JobStatus


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    progress: int
    payload: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class JobCreated(BaseModel):
    job_id: uuid.UUID
