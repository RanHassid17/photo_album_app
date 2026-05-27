from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Photo
from app.schemas.photos import PhotoSearchRequest, PhotoSearchResponse, PhotoSummary
from app.services.filter import search_photos
from app.services.thumbnails import get_or_create_thumbnail

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.post("/search", response_model=PhotoSearchResponse)
def search(
    body: PhotoSearchRequest, db: Session = Depends(get_db)
) -> PhotoSearchResponse:
    result = search_photos(db, body)
    return PhotoSearchResponse(
        total=result.total,
        items=[PhotoSummary.model_validate(p) for p in result.items],
        limit=body.limit,
        offset=body.offset,
    )


def _load_photo_and_file(db: Session, photo_id: uuid.UUID) -> tuple[Photo, Path]:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    path = Path(photo.stored_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="photo file missing on disk")
    return photo, path


@router.get("/{photo_id}/thumb")
def thumbnail(photo_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    _, source = _load_photo_and_file(db, photo_id)
    thumb = get_or_create_thumbnail(photo_id, source)
    return FileResponse(
        thumb, media_type="image/webp", headers={"Cache-Control": "public, max-age=86400"}
    )


@router.get("/{photo_id}/file")
def original(photo_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    _, source = _load_photo_and_file(db, photo_id)
    # Best-effort content type; FastAPI will sniff if we leave it None.
    return FileResponse(source)
