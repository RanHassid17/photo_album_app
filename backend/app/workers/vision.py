from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import FaceCluster, FaceEmbedding, Photo, PhotoLabel
from app.workers.celery_app import celery_app  # noqa: F401 -- bind shared_tasks to our app
from app.workers.exif import extract_exif_metadata
from app.workers.models import face_embeddings, label_objects
from app.workers.quality import compute_blur_score

log = logging.getLogger(__name__)


@dataclass(slots=True)
class IndexOutcome:
    photo_id: uuid.UUID
    face_count: int
    label_count: int
    errors: list[str]


@shared_task(name="vision.index_photo", bind=True, max_retries=2)
def index_photo(self, photo_id: str) -> dict[str, Any]:  # noqa: ANN001 -- celery bound
    """Index a single photo: EXIF, blur, faces, labels.

    Errors per-step are caught and reported but do not crash the task;
    we'd rather mark the photo indexed-with-warnings than re-run the whole
    pipeline on a flaky model run.
    """
    pid = uuid.UUID(photo_id)
    db: Session = SessionLocal()
    outcome = IndexOutcome(photo_id=pid, face_count=0, label_count=0, errors=[])
    try:
        photo = db.get(Photo, pid)
        if photo is None:
            log.warning("index_photo: photo %s not found", pid)
            return {"status": "missing"}

        path = Path(photo.stored_path)
        if not path.exists():
            log.warning("index_photo: file missing for %s at %s", pid, path)
            outcome.errors.append("file_missing")
            photo.indexed_at = datetime.now(timezone.utc)
            db.commit()
            return _outcome_to_dict(outcome)

        # --- EXIF + dimensions ---
        try:
            meta = extract_exif_metadata(path)
            photo.width = meta.width
            photo.height = meta.height
            photo.taken_at = meta.taken_at
            photo.gps_lat = meta.gps_lat
            photo.gps_lng = meta.gps_lng
        except Exception as exc:  # noqa: BLE001
            log.warning("exif failed for %s: %s", pid, exc)
            outcome.errors.append(f"exif:{exc}")

        # --- Quality (blur) ---
        try:
            photo.blur_score = compute_blur_score(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("blur failed for %s: %s", pid, exc)
            outcome.errors.append(f"blur:{exc}")

        # --- Faces ---
        try:
            for face in face_embeddings(path):
                db.add(
                    FaceEmbedding(
                        photo_id=pid,
                        bbox=face["bbox"],
                        embedding=face["embedding_bytes"],
                        embedding_dim=face["dim"],
                    )
                )
                outcome.face_count += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("faces failed for %s: %s", pid, exc)
            outcome.errors.append(f"faces:{exc}")

        # --- Object/animal labels ---
        try:
            for label, confidence in label_objects(path):
                db.add(
                    PhotoLabel(photo_id=pid, label=label, confidence=confidence)
                )
                outcome.label_count += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("labels failed for %s: %s", pid, exc)
            outcome.errors.append(f"labels:{exc}")

        photo.indexed_at = datetime.now(timezone.utc)
        db.commit()
        return _outcome_to_dict(outcome)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("index_photo crashed for %s", pid)
        raise
    finally:
        db.close()


@shared_task(name="vision.cluster_faces")
def cluster_faces(min_cluster_size: int = 2) -> dict[str, Any]:
    """Run HDBSCAN over all unclustered face embeddings, write FaceCluster rows."""
    import hdbscan  # heavy import; defer

    db: Session = SessionLocal()
    try:
        rows = db.scalars(
            select(FaceEmbedding).where(FaceEmbedding.cluster_id.is_(None))
        ).all()
        if len(rows) < min_cluster_size:
            return {"clustered": 0, "noise": len(rows), "new_clusters": 0}

        # Embeddings of different lengths cannot be stacked, and after a face-model
        # change the table holds both old and new vectors. Cluster the dominant
        # dimension and leave the stragglers unclustered rather than crashing; they get
        # picked up once the library is re-indexed.
        by_dim: dict[int, list] = {}
        for row in rows:
            by_dim.setdefault(int(row.embedding_dim), []).append(row)
        if len(by_dim) > 1:
            log.warning(
                "mixed face embedding dimensions %s — clustering the largest group only; "
                "re-index to migrate the rest",
                {d: len(v) for d, v in by_dim.items()},
            )
        rows = max(by_dim.values(), key=len)
        if len(rows) < min_cluster_size:
            return {"clustered": 0, "noise": len(rows), "new_clusters": 0}

        # Re-hydrate float32 embeddings from BYTEA.
        vectors = np.stack(
            [
                np.frombuffer(row.embedding, dtype=np.float32).reshape(row.embedding_dim)
                for row in rows
            ]
        )
        # L2-normalize so cosine distance matches the metric face nets are trained on.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = vectors / norms

        # "leaf" instead of "eom": excess-of-mass prefers a few large, high-stability
        # clusters, which on face embeddings means one blob absorbing many different
        # people (a single cluster reached 199 faces). Leaf selection takes the tightest
        # clusters in the tree instead — more clusters, each far more homogeneous, which
        # is what a "who is in this photo" filter actually needs.
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, min_cluster_size),
            metric="euclidean",
            cluster_selection_method="leaf",
        )
        labels = clusterer.fit_predict(normalized)

        cluster_ids: dict[int, uuid.UUID] = {}
        clustered = 0
        noise = 0
        for row, label in zip(rows, labels, strict=True):
            if label < 0:
                noise += 1
                continue
            cid = cluster_ids.get(int(label))
            if cid is None:
                cluster = FaceCluster(face_count=0, representative_photo_id=row.photo_id)
                db.add(cluster)
                db.flush()
                cid = cluster.id
                cluster_ids[int(label)] = cid
            row.cluster_id = cid
            clustered += 1

        # Update face_count tallies.
        for label, cid in cluster_ids.items():
            count = int(np.sum(labels == label))
            cluster = db.get(FaceCluster, cid)
            if cluster is not None:
                cluster.face_count = count

        db.commit()
        return {
            "clustered": clustered,
            "noise": noise,
            "new_clusters": len(cluster_ids),
        }
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("cluster_faces crashed")
        raise
    finally:
        db.close()


def _outcome_to_dict(o: IndexOutcome) -> dict[str, Any]:
    return {
        "photo_id": str(o.photo_id),
        "face_count": o.face_count,
        "label_count": o.label_count,
        "errors": o.errors,
    }
