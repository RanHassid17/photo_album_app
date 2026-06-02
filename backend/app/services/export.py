from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.exporters import (
    PdfExportError,
    build_print_zip,
    quality_report,
    render_album_pdf,
)
from app.exporters.print_zip import QualityReport
from app.models import Album, Photo


class AlbumNotFoundError(Exception):
    pass


@dataclass(slots=True)
class ExportBundle:
    filename: str
    media_type: str
    data: bytes


def _load_album(db: Session, album_id: uuid.UUID) -> Album:
    stmt = (
        select(Album)
        .where(Album.id == album_id)
        .options(selectinload(Album.pages).selectinload(Album.pages.property.mapper.class_.items))
    )
    album = db.scalar(stmt)
    if album is None:
        raise AlbumNotFoundError(str(album_id))
    return album


def _load_photos_for_album(db: Session, album: Album) -> list[Photo]:
    photo_ids = {it.photo_id for page in album.pages for it in page.items}
    if not photo_ids:
        return []
    return list(db.scalars(select(Photo).where(Photo.id.in_(photo_ids))).all())


def _safe_filename(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name.strip())
    return cleaned or fallback


def export_album_pdf(db: Session, album_id: uuid.UUID) -> ExportBundle:
    album = _load_album(db, album_id)
    photos = _load_photos_for_album(db, album)
    try:
        data = render_album_pdf(album, photos)
    except PdfExportError as exc:
        raise ValueError(str(exc)) from exc
    base = _safe_filename(album.name, f"album-{album.id}")
    return ExportBundle(filename=f"{base}.pdf", media_type="application/pdf", data=data)


def export_album_print_zip(db: Session, album_id: uuid.UUID) -> ExportBundle:
    album = _load_album(db, album_id)
    photos = _load_photos_for_album(db, album)
    data = build_print_zip(album, photos)
    base = _safe_filename(album.name, f"album-{album.id}")
    return ExportBundle(filename=f"{base}-print.zip", media_type="application/zip", data=data)


def album_quality_report(db: Session, album_id: uuid.UUID) -> QualityReport:
    album = _load_album(db, album_id)
    photos = _load_photos_for_album(db, album)
    return quality_report(album, photos)
