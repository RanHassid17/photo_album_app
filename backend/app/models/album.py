from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AlbumStyle(str, enum.Enum):
    MODERN = "modern"
    CLASSIC = "classic"
    KIDS = "kids"
    ROMANTIC = "romantic"
    MINIMALIST = "minimalist"


class CommentPosition(str, enum.Enum):
    ABOVE = "above"
    BELOW = "below"
    START = "start"  # logical 'left' in LTR / 'right' in RTL
    END = "end"
    NONE = "none"


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    style: Mapped[AlbumStyle] = mapped_column(
        Enum(AlbumStyle, name="album_style", native_enum=False, length=32),
        nullable=False,
        default=AlbumStyle.MODERN,
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    used_fallback: Mapped[bool] = mapped_column(default=False, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pages: Mapped[list["AlbumPage"]] = relationship(
        back_populates="album",
        cascade="all, delete-orphan",
        order_by="AlbumPage.index",
    )


class AlbumPage(Base):
    __tablename__ = "album_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    album_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("albums.id", ondelete="CASCADE"),
        nullable=False,
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Captures grid metadata (rows, cols, gap, etc.) + any per-page settings the agent emits.
    layout_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    album: Mapped[Album] = relationship(back_populates="pages")
    items: Mapped[list["AlbumItem"]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="AlbumItem.position_index",
    )

    __table_args__ = (
        UniqueConstraint("album_id", "index", name="uq_album_pages_album_id_index"),
        Index("ix_album_pages_album_id", "album_id"),
    )


class AlbumItem(Base):
    __tablename__ = "album_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("album_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("photos.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Position is a JSONB with x, y, w, h (0..1 floats relative to page), rotation_deg.
    position: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_position: Mapped[CommentPosition] = mapped_column(
        Enum(CommentPosition, name="comment_position", native_enum=False, length=16),
        nullable=False,
        default=CommentPosition.NONE,
    )

    page: Mapped[AlbumPage] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_album_items_page_id", "page_id"),
        Index("ix_album_items_photo_id", "photo_id"),
    )
