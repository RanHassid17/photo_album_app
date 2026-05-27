from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.schemas.selection import PickRead, SuggestRequest, SuggestResponse
from app.services.selection import suggest_selection

router = APIRouter(prefix="/api/selection", tags=["selection"])


@router.post("/suggest", response_model=SuggestResponse)
def suggest(body: SuggestRequest, db: Session = Depends(get_db)) -> SuggestResponse:
    settings = get_settings()
    result = suggest_selection(
        db,
        photo_ids=body.photo_ids,
        target_count=body.target_count,
        criteria=body.criteria,
        anthropic_model=settings.anthropic_model,
    )
    return SuggestResponse(
        picks=[
            PickRead(photo_id=p.photo_id, score=p.score, reason=p.reason)
            for p in result.picks
        ],
        used_fallback=result.used_fallback,
        model=result.model,
    )
