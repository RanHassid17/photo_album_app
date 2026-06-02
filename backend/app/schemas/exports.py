from __future__ import annotations

import uuid

from pydantic import BaseModel


class LowResWarning(BaseModel):
    photo_id: str
    original_w: int | None
    original_h: int | None
    size: str
    required_w: int
    required_h: int


class ExportQualityResponse(BaseModel):
    album_id: uuid.UUID
    low_resolution_warnings: list[LowResWarning]
