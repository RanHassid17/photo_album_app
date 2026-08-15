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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="actually delete and re-queue indexing"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would happen, change nothing"
    )
    args = parser.parse_args()

    if not args.yes and not args.dry_run:
        parser.error("pass --dry-run to preview, or --yes to run")

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
    print("watch progress in the Celery worker terminal (`make worker`)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
