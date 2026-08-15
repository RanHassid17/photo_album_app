from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AlbumStyle, CommentPosition


class LayoutPosition(BaseModel):
    """Position of one item on a page in normalized 0..1 coordinates.

    (0,0) is the page's start-top corner (logical, RTL-aware on render).
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)
    rotation_deg: float = Field(default=0.0, ge=-45.0, le=45.0)


class LayoutItem(BaseModel):
    photo_id: uuid.UUID
    position: LayoutPosition
    # 'hero' marks the dominant photo on a page. Persisted inside the position JSONB so
    # the renderer can treat it specially without a schema migration.
    emphasis: Literal["hero", "normal"] = "normal"
    comment: Annotated[str | None, Field(default=None, max_length=200)] = None
    comment_position: CommentPosition = CommentPosition.NONE


class LayoutGrid(BaseModel):
    rows: int = Field(ge=1, le=6)
    cols: int = Field(ge=1, le=6)
    gap: float = Field(default=0.02, ge=0.0, le=0.1)


class LayoutPage(BaseModel):
    grid: LayoutGrid
    items: list[LayoutItem]


class LayoutPlan(BaseModel):
    pages: list[LayoutPage]


class SuggestLayoutRequest(BaseModel):
    photo_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=500)]
    page_count: Annotated[int, Field(ge=1, le=50)]
    style: AlbumStyle = AlbumStyle.MODERN
    name: Annotated[str | None, Field(default=None, max_length=200)] = None


class SuggestLayoutResponse(BaseModel):
    album_id: uuid.UUID
    layout: LayoutPlan
    used_fallback: bool
    model: str | None


# --- Read models for GET /api/albums/{id} ---


class AlbumItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    photo_id: uuid.UUID
    position_index: int
    position: dict
    comment: str | None
    comment_position: CommentPosition


class AlbumPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    index: int
    layout_json: dict
    items: list[AlbumItemRead]


class AlbumRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    style: AlbumStyle
    page_count: int
    used_fallback: bool
    model: str | None
    pages: list[AlbumPageRead]


class AlbumSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    style: AlbumStyle
    page_count: int
    used_fallback: bool
