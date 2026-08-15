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


class SizeRecommendation(BaseModel):
    photo_id: str
    # Largest standard print size the original fills at a true 300 DPI. None means even
    # the smallest size would require upscaling.
    recommended_size: str | None


class ExportQualityResponse(BaseModel):
    album_id: uuid.UUID
    low_resolution_warnings: list[LowResWarning]
    recommended_sizes: list[SizeRecommendation] = []
