from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from celery import shared_task
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import FaceCluster, FaceEmbedding, Photo, PhotoLabel
from app.services.face_thumbs import delete_face_thumbs
from app.services.imaging import analysis_copy
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

        # Decode the source once and work from a downscaled JPEG. Previously EXIF, the
        # face model and the object model each re-decoded the original: three LibRaw
        # passes over a 30MB RAW per photo, with detection then running at full
        # resolution. Measured cost was ~300s/photo.
        try:
            analysis_ctx = analysis_copy(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not decode %s: %s", pid, exc)
            outcome.errors.append(f"decode:{exc}")
            photo.indexed_at = datetime.now(timezone.utc)
            db.commit()
            return _outcome_to_dict(outcome)

        with analysis_ctx as (apath, scale, original_size):
            _index_from_analysis(db, photo, pid, path, apath, scale, original_size, outcome)

        photo.indexed_at = datetime.now(timezone.utc)
        db.commit()
        return _outcome_to_dict(outcome)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("index_photo crashed for %s", pid)
        raise
    finally:
        db.close()


def _index_from_analysis(  # noqa: PLR0913
    db: Session,
    photo: Photo,
    pid: uuid.UUID,
    original_path: Path,
    apath: Path,
    scale: float,
    original_size: tuple[int, int],
    outcome: "IndexOutcome",
) -> None:
    # --- EXIF + dimensions ---
    try:
        meta = extract_exif_metadata(original_path, known_size=original_size)
        photo.width = meta.width
        photo.height = meta.height
        photo.taken_at = meta.taken_at
        photo.gps_lat = meta.gps_lat
        photo.gps_lng = meta.gps_lng
    except Exception as exc:  # noqa: BLE001
        log.warning("exif failed for %s: %s", pid, exc)
        outcome.errors.append(f"exif:{exc}")

    # --- Quality (blur) ---
    # Scored on the analysis copy: OpenCV cannot read RAW or HEIC, so every RAW
    # photo previously ended up with no blur score at all, which silently degraded
    # the selection ranking.
    try:
        photo.blur_score = compute_blur_score(apath)
    except Exception as exc:  # noqa: BLE001
        log.warning("blur failed for %s: %s", pid, exc)
        outcome.errors.append(f"blur:{exc}")

    # Indexing REPLACES a photo's derived data rather than appending to it. Without
    # this, re-indexing an already-indexed photo violates
    # uq_photo_labels_photo_id_label on the first label it re-detects, the task
    # crashes, and -- because index_photo is a chord header -- the whole chord fails,
    # so cluster_faces never runs and the app is left with embeddings but no people.
    db.execute(delete(FaceEmbedding).where(FaceEmbedding.photo_id == pid))
    db.execute(delete(PhotoLabel).where(PhotoLabel.photo_id == pid))

    # --- Faces ---
    try:
        for face in face_embeddings(apath, scale=scale):
            db.add(
                FaceEmbedding(
                    photo_id=pid,
                    bbox=face["bbox"],
                    embedding=face["embedding_bytes"],
                    embedding_dim=face["dim"],
                    sharpness=face.get("sharpness"),
                    frontality=face.get("frontality"),
                )
            )
            outcome.face_count += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("faces failed for %s: %s", pid, exc)
        outcome.errors.append(f"faces:{exc}")

    # --- Object/animal labels ---
    try:
        for label, confidence in label_objects(apath):
            db.add(
                PhotoLabel(photo_id=pid, label=label, confidence=confidence)
            )
            outcome.label_count += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("labels failed for %s: %s", pid, exc)
        outcome.errors.append(f"labels:{exc}")


def _normalized(row: FaceEmbedding) -> np.ndarray:
    """Unit-length float32 vector for one stored face."""
    vec = np.frombuffer(row.embedding, dtype=np.float32).reshape(row.embedding_dim)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def _merge_duplicate_clusters(db: Session, max_distance: float) -> int:
    """Fold clusters that are the same person into one. Returns clusters removed.

    Two things make duplicates unavoidable without this pass. `cluster_selection_method
    ="leaf"` deliberately cuts the HDBSCAN tree at its tightest nodes, which splits one
    person across several clusters whenever their photos span lighting, angle or years.
    And clustering is incremental -- it only ever looks at faces with no cluster yet --
    so every new import invents fresh clusters for people who already have one.

    Merging on the average embedding fixes both: a cluster's centroid is a much cleaner
    signal of identity than any single face, so the same person's fragments sit far
    closer together than two different people ever do.
    """
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    rows = db.scalars(
        select(FaceEmbedding).where(FaceEmbedding.cluster_id.is_not(None))
    ).all()

    by_cluster: dict[uuid.UUID, list[np.ndarray]] = {}
    for row in rows:
        by_cluster.setdefault(row.cluster_id, []).append(_normalized(row))
    # Only comparable dimensions can be stacked; mixed dims are already logged upstream.
    per_dim: dict[int, int] = {}
    for vs in by_cluster.values():
        for v in vs:
            per_dim[v.size] = per_dim.get(v.size, 0) + 1
    if len(per_dim) > 1:
        keep = max(per_dim, key=lambda d: per_dim[d])
        by_cluster = {
            cid: vs for cid, vs in by_cluster.items() if all(v.size == keep for v in vs)
        }
    if len(by_cluster) < 2:
        return 0

    cluster_ids = list(by_cluster)
    centroids = np.stack([np.mean(by_cluster[cid], axis=0) for cid in cluster_ids])
    norms = np.linalg.norm(centroids, axis=1, keepdims=True)
    centroids = centroids / np.where(norms == 0, 1.0, norms)

    distances = np.clip(1.0 - centroids @ centroids.T, 0.0, None)
    np.fill_diagonal(distances, 0.0)
    # Average linkage, not single: single linkage chains two people together through one
    # ambiguous cluster sitting between them.
    groups = fcluster(
        linkage(squareform(distances, checks=False), method="average"),
        t=max_distance,
        criterion="distance",
    )

    merged_away = 0
    for group in set(groups):
        members = [cid for cid, g in zip(cluster_ids, groups, strict=True) if g == group]
        if len(members) < 2:
            continue
        clusters = [
            c for c in (db.get(FaceCluster, cid) for cid in members) if c is not None
        ]
        named = [c for c in clusters if c.name]
        if len({c.name for c in named}) > 1:
            # The user told us these are different people. Believe them over the model.
            log.info(
                "not merging clusters with conflicting names: %s",
                sorted(c.name for c in named),
            )
            continue

        # Keep the named cluster so the name survives; otherwise the biggest one, which
        # keeps the representative face that the user has already learned to recognise.
        survivor = named[0] if named else max(clusters, key=lambda c: c.face_count)
        losers = [c for c in clusters if c.id != survivor.id]
        for loser in losers:
            db.execute(
                update(FaceEmbedding)
                .where(FaceEmbedding.cluster_id == loser.id)
                .values(cluster_id=survivor.id)
            )
            if survivor.representative_photo_id is None:
                survivor.representative_photo_id = loser.representative_photo_id
            delete_face_thumbs(loser.id)
            db.delete(loser)
        survivor.face_count = sum(len(by_cluster[c.id]) for c in clusters)
        merged_away += len(losers)

    return merged_away


def _cluster_new_faces(db: Session, min_cluster_size: int) -> tuple[int, int, int]:
    """HDBSCAN over faces with no cluster yet. Returns (clustered, noise, new clusters)."""
    import hdbscan  # heavy import; defer

    rows = db.scalars(
        select(FaceEmbedding).where(FaceEmbedding.cluster_id.is_(None))
    ).all()
    if len(rows) < min_cluster_size:
        return 0, len(rows), 0

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
        return 0, len(rows), 0

    # Re-hydrate float32 embeddings from BYTEA and L2-normalize, so cosine distance
    # matches the metric face nets are trained on.
    normalized = np.stack([_normalized(row) for row in rows])

    # "leaf" instead of "eom": excess-of-mass prefers a few large, high-stability
    # clusters, which on face embeddings means one blob absorbing many different
    # people (a single cluster reached 199 faces). Leaf selection takes the tightest
    # clusters in the tree instead. It errs the other way — one person split across
    # several clusters — which _merge_duplicate_clusters then stitches back together.
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
        cluster = db.get(FaceCluster, cid)
        if cluster is not None:
            cluster.face_count = int(np.sum(labels == label))

    db.flush()
    return clustered, noise, len(cluster_ids)


@shared_task(name="vision.cluster_faces")
def cluster_faces(min_cluster_size: int = 2) -> dict[str, Any]:
    """Group face embeddings into people: cluster the new faces, then de-duplicate.

    The merge step runs over every cluster, not just the ones created here, because
    duplicates of the same person accumulate across runs as new photos are imported.
    """
    from app.config import get_settings

    db: Session = SessionLocal()
    try:
        clustered, noise, new_clusters = _cluster_new_faces(db, min_cluster_size)
        merged = _merge_duplicate_clusters(
            db, get_settings().vision_face_merge_distance
        )
        db.commit()
        return {
            "clustered": clustered,
            "noise": noise,
            "new_clusters": new_clusters,
            "merged": merged,
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
