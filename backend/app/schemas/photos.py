from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GpsBoundingBox(BaseModel):
    min_lat: float = Field(..., ge=-90, le=90)
    max_lat: float = Field(..., ge=-90, le=90)
    min_lng: float = Field(..., ge=-180, le=180)
    max_lng: float = Field(..., ge=-180, le=180)

    @model_validator(mode="after")
    def _ordered(self) -> GpsBoundingBox:
        if self.min_lat > self.max_lat:
            raise ValueError("min_lat must be <= max_lat")
        if self.min_lng > self.max_lng:
            raise ValueError("min_lng must be <= max_lng")
        return self


class PhotoSearchRequest(BaseModel):
    person_cluster_ids: list[uuid.UUID] | None = None
    animal_labels: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    gps_bbox: GpsBoundingBox | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 60
    offset: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def _dates_ordered(self) -> PhotoSearchRequest:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self


class PhotoSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    taken_at: datetime | None
    gps_lat: float | None
    gps_lng: float | None
    width: int | None
    height: int | None
    blur_score: float | None
    indexed_at: datetime | None


class PhotoSearchResponse(BaseModel):
    total: int
    items: list[PhotoSummary]
    limit: int
    offset: int
