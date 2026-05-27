from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, Field


class SuggestRequest(BaseModel):
    photo_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=500)]
    target_count: Annotated[int, Field(ge=1, le=100)]
    criteria: str | None = Field(default=None, max_length=300)


class PickRead(BaseModel):
    photo_id: uuid.UUID
    score: float
    reason: str


class SuggestResponse(BaseModel):
    picks: list[PickRead]
    used_fallback: bool
    model: str | None
