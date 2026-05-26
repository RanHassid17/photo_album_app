from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, JobStatus, Photo
from app.sources.base import PhotoSource

log = logging.getLogger(__name__)

_HASH_CHUNK = 1024 * 1024  # 1 MiB


@dataclass(slots=True)
class IngestResult:
    scanned: int
    inserted: int
    duplicates: int
    errors: int
    inserted_ids: list[uuid.UUID]


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _photo_storage_root() -> Path:
    return get_settings().photo_storage_dir.resolve() / "local"


def run_ingest(job_id: uuid.UUID, source: PhotoSource) -> IngestResult:
    """Walk a source, hash each file, dedupe by SHA-256, copy into storage, insert Photo rows.

    Updates the Job row with progress as it goes. Designed to be called from a
    FastAPI BackgroundTask in B.1; in B.2 we move it behind Celery.
    """
    storage_root = _photo_storage_root()
    storage_root.mkdir(parents=True, exist_ok=True)

    total = source.estimated_count() or 0
    result = IngestResult(
        scanned=0, inserted=0, duplicates=0, errors=0, inserted_ids=[]
    )

    db: Session = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            log.error("ingest job %s not found", job_id)
            return result
        job.status = JobStatus.RUNNING
        job.payload = {**(job.payload or {}), "total": total}
        db.commit()

        for candidate in source.iter_candidates():
            result.scanned += 1
            try:
                digest = _sha256_of_file(candidate.local_path)
            except OSError as exc:
                log.warning("hash failed for %s: %s", candidate.local_path, exc)
                result.errors += 1
                continue

            existing = db.scalar(select(Photo.id).where(Photo.sha256 == digest))
            if existing is not None:
                result.duplicates += 1
            else:
                photo_id = uuid.uuid4()
                ext = candidate.local_path.suffix.lower() or ".bin"
                stored_path = storage_root / f"{photo_id}{ext}"
                try:
                    shutil.copy2(candidate.local_path, stored_path)
                except OSError as exc:
                    log.warning("copy failed for %s: %s", candidate.local_path, exc)
                    result.errors += 1
                    continue

                db.add(
                    Photo(
                        id=photo_id,
                        source=candidate.source,
                        source_ref=candidate.source_ref,
                        sha256=digest,
                        original_path=str(candidate.local_path),
                        stored_path=str(stored_path),
                    )
                )
                result.inserted += 1
                result.inserted_ids.append(photo_id)

            if total > 0:
                job.progress = min(100, int(result.scanned * 100 / total))
            job.payload = {
                "total": total,
                "scanned": result.scanned,
                "inserted": result.inserted,
                "duplicates": result.duplicates,
                "errors": result.errors,
            }
            # Commit per file so polling sees progress and partial work survives crashes.
            db.commit()

        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

        _enqueue_vision_pipeline(result.inserted_ids)
        return result
    except Exception as exc:  # noqa: BLE001 -- job runner must catch everything
        log.exception("ingest job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        return result
    finally:
        db.close()


def _enqueue_vision_pipeline(photo_ids: list[uuid.UUID]) -> None:
    """Schedule index_photo per new photo + a follow-up cluster_faces.

    Imported lazily so test runs that don't touch Celery don't drag in TF.
    Silent on broker errors — vision can be re-run via the worker manually.
    """
    if not photo_ids:
        return
    if os.environ.get("ALBUM_DISABLE_VISION_ENQUEUE") == "1":
        return
    try:
        from celery import chord

        from app.workers.vision import cluster_faces, index_photo

        header = [index_photo.s(str(pid)) for pid in photo_ids]
        # `.si()` (immutable) — don't pass per-photo results to cluster_faces;
        # it works off the DB.
        chord(header)(cluster_faces.si())
    except Exception:  # noqa: BLE001
        log.exception("failed to enqueue vision pipeline for %d photos", len(photo_ids))
