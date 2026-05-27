from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PhotoLabel

router = APIRouter(prefix="/api/labels", tags=["labels"])


class LabelCount(BaseModel):
    label: str
    photo_count: int


@router.get("", response_model=list[LabelCount])
def list_labels(db: Session = Depends(get_db)) -> list[LabelCount]:
    stmt = (
        select(PhotoLabel.label, func.count(func.distinct(PhotoLabel.photo_id)))
        .group_by(PhotoLabel.label)
        .order_by(func.count(func.distinct(PhotoLabel.photo_id)).desc())
    )
    rows = db.execute(stmt).all()
    return [LabelCount(label=row[0], photo_count=row[1]) for row in rows]
