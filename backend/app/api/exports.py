from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.exports import (
    ExportQualityResponse,
    LowResWarning,
    SizeRecommendation,
)
from app.services.export import (
    AlbumNotFoundError,
    album_quality_report,
    export_album_pdf,
    export_album_print_zip,
)

router = APIRouter(prefix="/api/albums", tags=["exports"])


def _ascii_fallback(filename: str) -> str:
    """An ASCII-only version of `filename`, keeping the extension.

    HTTP headers are latin-1. The plain `filename=` parameter therefore cannot carry
    Hebrew, and every non-Latin character has to be replaced rather than passed through.
    """
    stem, _, ext = filename.rpartition(".")
    if not stem:  # no extension
        stem, ext = filename, ""
    cleaned = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "_" for c in stem)
    cleaned = cleaned.strip("_") or "album"
    return f"{cleaned}.{ext}" if ext else cleaned


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition header that survives a Hebrew album name.

    The previous version interpolated the raw name into the plain `filename=`
    parameter. Starlette encodes headers as latin-1, so any album with a Hebrew name
    raised UnicodeEncodeError and the whole export 500'd — which is why exporting
    "sometimes" worked: it depended entirely on whether the album had been named.
    Modern clients read `filename*`; `filename=` is only the legacy fallback and must
    stay ASCII.
    """
    return (
        f'attachment; filename="{_ascii_fallback(filename)}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )


@router.get("/{album_id}/export/quality", response_model=ExportQualityResponse)
def get_quality(album_id: uuid.UUID, db: Session = Depends(get_db)) -> ExportQualityResponse:
    try:
        report = album_quality_report(db, album_id)
    except AlbumNotFoundError as exc:
        raise HTTPException(status_code=404, detail="album not found") from exc
    return ExportQualityResponse(
        album_id=album_id,
        low_resolution_warnings=[LowResWarning(**w) for w in report.to_jsonable()],
        recommended_sizes=[
            SizeRecommendation(**r) for r in report.recommendations_jsonable()
        ],
    )


@router.post("/{album_id}/export/pdf")
def export_pdf(album_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    try:
        bundle = export_album_pdf(db, album_id)
    except AlbumNotFoundError as exc:
        raise HTTPException(status_code=404, detail="album not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=bundle.data,
        media_type=bundle.media_type,
        headers={"Content-Disposition": _content_disposition(bundle.filename)},
    )


@router.post("/{album_id}/export/print")
def export_print(album_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    try:
        bundle = export_album_print_zip(db, album_id)
    except AlbumNotFoundError as exc:
        raise HTTPException(status_code=404, detail="album not found") from exc
    return Response(
        content=bundle.data,
        media_type=bundle.media_type,
        headers={"Content-Disposition": _content_disposition(bundle.filename)},
    )
