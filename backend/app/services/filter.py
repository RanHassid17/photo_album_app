from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models import FaceEmbedding, Photo, PhotoLabel
from app.schemas.photos import PhotoSearchRequest


@dataclass(slots=True)
class FilterResult:
    total: int
    items: list[Photo]


def search_photos(db: Session, req: PhotoSearchRequest) -> FilterResult:
    """Run the filter described by `req`, returning paginated photos + total count.

    Filter dimensions combine with AND.
    - `person_cluster_ids`: photo has at least one face_embedding whose cluster is
      in the requested set (OR among requested clusters).
    - `animal_labels`: photo has at least one photo_label in the requested set
      (OR among requested labels).
    - `date_from` / `date_to`: range on `photos.taken_at`.
    - `gps_bbox`: photo GPS falls inside the box.

    Photos with NULL `taken_at` are excluded when a date filter is active.
    Photos with NULL GPS are excluded when a gps_bbox is active.
    """
    base = _build_filtered_query(req)

    total_q = select(func.count()).select_from(base.subquery())
    total = int(db.scalar(total_q) or 0)

    page_q = (
        base.order_by(Photo.taken_at.desc().nullslast(), Photo.created_at.desc())
        .offset(req.offset)
        .limit(req.limit)
    )
    items = list(db.scalars(page_q).all())
    return FilterResult(total=total, items=items)


def _build_filtered_query(req: PhotoSearchRequest) -> Select[tuple[Photo]]:
    q = select(Photo)

    conds = []

    if req.date_from is not None:
        conds.append(Photo.taken_at >= req.date_from)
    if req.date_to is not None:
        conds.append(Photo.taken_at <= req.date_to)

    if req.gps_bbox is not None:
        bbox = req.gps_bbox
        conds.append(Photo.gps_lat.is_not(None))
        conds.append(Photo.gps_lng.is_not(None))
        conds.append(Photo.gps_lat.between(bbox.min_lat, bbox.max_lat))
        conds.append(Photo.gps_lng.between(bbox.min_lng, bbox.max_lng))

    if req.person_cluster_ids:
        # Use EXISTS to avoid duplicate Photo rows when multiple faces match.
        face_exists = (
            select(FaceEmbedding.id)
            .where(
                FaceEmbedding.photo_id == Photo.id,
                FaceEmbedding.cluster_id.in_(req.person_cluster_ids),
            )
            .exists()
        )
        conds.append(face_exists)

    if req.animal_labels:
        label_exists = (
            select(PhotoLabel.id)
            .where(
                PhotoLabel.photo_id == Photo.id,
                PhotoLabel.label.in_(req.animal_labels),
            )
            .exists()
        )
        conds.append(label_exists)

    if conds:
        q = q.where(and_(*conds))
    return q
