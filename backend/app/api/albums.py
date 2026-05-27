from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Album
from app.schemas.layouts import AlbumRead, AlbumSummary

router = APIRouter(prefix="/api/albums", tags=["albums"])


@router.get("", response_model=list[AlbumSummary])
def list_albums(db: Session = Depends(get_db)) -> list[Album]:
    stmt = select(Album).order_by(Album.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/{album_id}", response_model=AlbumRead)
def get_album(album_id: uuid.UUID, db: Session = Depends(get_db)) -> Album:
    stmt = (
        select(Album)
        .where(Album.id == album_id)
        .options(selectinload(Album.pages).selectinload(Album.pages.property.mapper.class_.items))
    )
    album = db.scalar(stmt)
    if album is None:
        raise HTTPException(status_code=404, detail="album not found")
    return album
