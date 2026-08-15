"""Re-run face detection and clustering over the whole library.

Needed after changing the face model or detector: embeddings produced by different
models are not comparable, and a 512-d vector cannot be matched against a 128-d one.
Face data is entirely derived from the photos, so deleting it is safe — nothing the
user authored lives in these tables. Album contents and photo files are untouched.

Usage (from backend/, with the Celery worker running):

    .venv/bin/python -m scripts.reindex_faces --dry-run
    .venv/bin/python -m scripts.reindex_faces --yes
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import FaceCluster, FaceEmbedding, Photo


def _cluster_now() -> int:
    """Group unclustered faces into people, in-process.

    Indexing queues clustering as a chord callback, which Celery tracks in the result
    backend. Restarting the worker mid-run loses that counter, so every photo finishes
    and the clustering step silently never fires -- leaving a full embeddings table and
    zero people. Running it directly is the recovery, and it takes seconds because it is
    pure numeric work with no model loading.
    """
    from app.workers.vision import cluster_faces

    result = cluster_faces()
    print(
        f"clustered {result['clustered']} faces into {result['new_clusters']} people "
        f"({result['noise']} unassigned)"
    )
    return 0


def _print_status() -> int:
    db = SessionLocal()
    try:
        photos = db.scalar(select(func.count()).select_from(Photo)) or 0
        embeddings = db.scalar(select(func.count()).select_from(FaceEmbedding)) or 0
        clusters = db.scalar(select(func.count()).select_from(FaceCluster)) or 0
        indexed = (
            db.scalar(
                select(func.count())
                .select_from(Photo)
                .where(Photo.indexed_at.is_not(None))
            )
            or 0
        )
    finally:
        db.close()

    print(f"photos:          {photos}")
    # indexed_at is not reset by a re-index, so this counts anything ever indexed —
    # it is not this run's progress. Queue depth below is.
    print(f"ever indexed:    {indexed} / {photos}  (not this run)")
    print(f"queue remaining: {_queue_depth()}  <- this run's progress")
    print(f"face embeddings: {embeddings}")
    print(f"face clusters:   {clusters}  (written once, after the last photo)")
    print(f"worker running:  {'yes' if _worker_is_alive() else 'NO — run `make worker`'}")
    return 0


def _queue_depth() -> str:
    """Tasks still waiting on the broker — the real measure of re-index progress."""
    try:
        from app.workers.celery_app import celery_app

        with celery_app.connection_or_acquire() as conn:
            return str(conn.default_channel.client.llen("celery"))
    except Exception:  # noqa: BLE001
        return "unknown"


def _worker_is_alive(timeout: float = 5.0) -> bool:
    """True if at least one Celery worker answers a ping."""
    try:
        from app.workers.celery_app import celery_app

        replies = celery_app.control.ping(timeout=timeout)
        return bool(replies)
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="actually delete and re-queue indexing"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would happen, change nothing"
    )
    parser.add_argument(
        "--status", action="store_true", help="show re-indexing progress and exit"
    )
    parser.add_argument(
        "--cluster-only",
        action="store_true",
        help="group already-indexed faces into people, without re-indexing",
    )
    args = parser.parse_args()

    if args.status:
        return _print_status()

    if args.cluster_only:
        return _cluster_now()

    if not args.yes and not args.dry_run:
        parser.error("pass --dry-run to preview, or --yes to run, or --status to check")

    # Deleting face data before confirming anything can rebuild it leaves the app
    # showing zero people with no explanation. Check first.
    if args.yes and not _worker_is_alive():
        print("ERROR: no Celery worker is responding.")
        print()
        print("This script deletes all face data and queues re-indexing. Without a")
        print("worker consuming the queue you would be left with no faces at all.")
        print()
        print("Start one in another terminal:  make worker")
        return 1

    db = SessionLocal()
    try:
        embeddings = db.scalar(select(func.count()).select_from(FaceEmbedding)) or 0
        clusters = db.scalar(select(func.count()).select_from(FaceCluster)) or 0
        photos = db.scalar(select(func.count()).select_from(Photo)) or 0

        named = db.scalars(
            select(FaceCluster.name).where(FaceCluster.name.is_not(None))
        ).all()

        print(f"photos:          {photos}")
        print(f"face embeddings: {embeddings}  (will be deleted)")
        print(f"face clusters:   {clusters}  (will be deleted)")
        if named:
            print()
            print(f"WARNING: {len(named)} named {'person' if len(named) == 1 else 'people'} "
                  f"will lose their names: {', '.join(sorted(named))}")
            print("Clustering starts from scratch, so names cannot be carried over —")
            print("the new clusters are not the same groupings as the old ones.")

        if args.dry_run:
            print("\ndry run — nothing changed")
            return 0

        db.execute(delete(FaceEmbedding))
        db.execute(delete(FaceCluster))
        db.commit()
        print("\ndeleted face embeddings and clusters")

        photo_ids = [str(pid) for pid in db.scalars(select(Photo.id)).all()]
    finally:
        db.close()

    if not photo_ids:
        print("no photos to index")
        return 0

    from celery import chord

    from app.workers.vision import cluster_faces, index_photo

    chord([index_photo.s(pid) for pid in photo_ids])(cluster_faces.si())
    print(f"queued re-indexing for {len(photo_ids)} photos")
    print("watch progress in the Celery worker terminal, or run:")
    print("  .venv/bin/python -m scripts.reindex_faces --status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
