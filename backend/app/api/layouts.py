from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.schemas.layouts import SuggestLayoutRequest, SuggestLayoutResponse
from app.services.layout import suggest_layout

router = APIRouter(prefix="/api/layouts", tags=["layouts"])


@router.post("/suggest", response_model=SuggestLayoutResponse, status_code=201)
def suggest(body: SuggestLayoutRequest, db: Session = Depends(get_db)) -> SuggestLayoutResponse:
    settings = get_settings()
    result = suggest_layout(
        db,
        photo_ids=body.photo_ids,
        page_count=body.page_count,
        style=body.style,
        name=body.name,
        anthropic_model=settings.anthropic_model,
    )
    return SuggestLayoutResponse(
        album_id=result.album.id,
        layout=result.plan,
        used_fallback=result.used_fallback,
        model=result.model,
    )
