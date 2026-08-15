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
    # What to print: the size the album layout calls for, capped by what the pixels
    # support. None means even the smallest size would require upscaling.
    recommended_size: str | None
    # What the photo's prominence in the album alone would call for.
    layout_size: str
    # Largest size the original fills at a true 300 DPI.
    max_by_resolution: str | None
    # True when the pixels, not the design, decided the recommendation.
    limited_by_resolution: bool


class ExportQualityResponse(BaseModel):
    album_id: uuid.UUID
    low_resolution_warnings: list[LowResWarning]
    recommended_sizes: list[SizeRecommendation] = []
