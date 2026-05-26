from __future__ import annotations

from pydantic import BaseModel, Field


class LocalFolderIngestRequest(BaseModel):
    path: str = Field(..., min_length=1, description="Absolute path to a folder on the host.")
