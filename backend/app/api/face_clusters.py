from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FaceCluster

router = APIRouter(prefix="/api/face-clusters", tags=["face_clusters"])


class FaceClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    representative_photo_id: uuid.UUID | None
    face_count: int


@router.get("", response_model=list[FaceClusterRead])
def list_clusters(db: Session = Depends(get_db)) -> list[FaceCluster]:
    stmt = select(FaceCluster).order_by(FaceCluster.face_count.desc())
    return list(db.scalars(stmt).all())
