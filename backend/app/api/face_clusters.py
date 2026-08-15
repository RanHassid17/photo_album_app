from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FaceCluster, FaceEmbedding, Photo
from app.services.face_thumbs import get_or_create_face_thumb

router = APIRouter(prefix="/api/face-clusters", tags=["face_clusters"])


class FaceClusterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    representative_photo_id: uuid.UUID | None
    face_count: int


class FaceClusterUpdate(BaseModel):
    # Empty string clears the name and falls back to the generated label.
    name: str | None = Field(default=None, max_length=128)


@router.get("", response_model=list[FaceClusterRead])
def list_clusters(db: Session = Depends(get_db)) -> list[FaceCluster]:
    stmt = select(FaceCluster).order_by(FaceCluster.face_count.desc())
    return list(db.scalars(stmt).all())


@router.patch("/{cluster_id}", response_model=FaceClusterRead)
def rename_cluster(
    cluster_id: uuid.UUID,
    body: FaceClusterUpdate,
    db: Session = Depends(get_db),
) -> FaceCluster:
    """Give a person a name.

    Clusters are global rather than per-album, so a name set here is reused by every
    future album without any extra work.
    """
    cluster = db.get(FaceCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="face cluster not found")
    name = (body.name or "").strip()
    cluster.name = name or None
    db.commit()
    db.refresh(cluster)
    return cluster


# How many candidate faces to weigh when choosing the one to show.
_REPRESENTATIVE_SAMPLE = 60


def _face_area(face: FaceEmbedding) -> int:
    bbox = face.bbox or {}
    return int(bbox.get("w", 0) or 0) * int(bbox.get("h", 0) or 0)


def _representative_face(db: Session, cluster: FaceCluster) -> tuple[Photo, dict]:
    """Pick the best face to show for a cluster.

    Previously this took whichever row came back first, which is why people showed up
    in profile or half-turned. A detector's box is largest when the subject is closest
    to the camera and facing it, so the biggest box is a good cheap proxy for "a clear,
    front-on face" without running a second model.
    """
    faces = list(
        db.scalars(
            select(FaceEmbedding)
            .where(FaceEmbedding.cluster_id == cluster.id)
            .limit(_REPRESENTATIVE_SAMPLE)
        ).all()
    )
    if not faces:
        raise HTTPException(status_code=404, detail="cluster has no faces")

    face = max(
        faces,
        key=lambda f: (
            _face_area(f),
            f.photo_id == cluster.representative_photo_id,
        ),
    )
    photo = db.get(Photo, face.photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    return photo, face.bbox


@router.get("/{cluster_id}/thumb")
def cluster_thumbnail(
    cluster_id: uuid.UUID, db: Session = Depends(get_db)
) -> FileResponse:
    cluster = db.get(FaceCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="face cluster not found")

    photo, bbox = _representative_face(db, cluster)
    source = Path(photo.stored_path)
    if not source.exists():
        raise HTTPException(status_code=410, detail="photo file missing on disk")

    try:
        thumb = get_or_create_face_thumb(cluster_id, photo.id, source, bbox)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return FileResponse(
        thumb,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )
