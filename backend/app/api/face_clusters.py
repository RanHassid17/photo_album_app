from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FaceCluster, FaceEmbedding, Photo
from app.services.face_thumbs import face_display_rank, get_or_create_face_thumb

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


# How many candidate faces to weigh when choosing the one to show. Ordering by size
# first means the sample is the cluster's most promising faces, not an arbitrary slice.
_REPRESENTATIVE_SAMPLE = 60


def _representative_face(db: Session, cluster: FaceCluster) -> tuple[Photo, dict]:
    """Pick the clearest, most front-on face to show for a cluster.

    Box size alone was the previous proxy for this, and it is a bad one: the biggest
    box in a cluster is often a blurred face close to the lens, a head turned to the
    side, or someone half out of frame. Sharpness and eye separation are measured per
    face at index time (see app.workers.models._face_quality), so the choice can be
    made on what the face actually looks like.
    """
    faces = list(
        db.scalars(
            select(FaceEmbedding)
            .where(FaceEmbedding.cluster_id == cluster.id)
            .order_by(
                (
                    FaceEmbedding.bbox["w"].astext.cast(Integer)
                    * FaceEmbedding.bbox["h"].astext.cast(Integer)
                ).desc()
            )
            .limit(_REPRESENTATIVE_SAMPLE)
        ).all()
    )
    if not faces:
        raise HTTPException(status_code=404, detail="cluster has no faces")

    photos = {
        p.id: p
        for p in db.scalars(
            select(Photo).where(Photo.id.in_({f.photo_id for f in faces}))
        ).all()
    }

    def rank(face: FaceEmbedding) -> tuple[int, float]:
        photo = photos.get(face.photo_id)
        return face_display_rank(
            face.bbox or {},
            face.sharpness,
            face.frontality,
            photo.width if photo else None,
            photo.height if photo else None,
        )

    face = max(faces, key=rank)
    photo = photos.get(face.photo_id)
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
