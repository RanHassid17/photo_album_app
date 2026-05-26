from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Job, JobKind, JobStatus
from app.schemas.jobs import JobCreated
from app.schemas.sources import LocalFolderIngestRequest
from app.services.ingest import run_ingest
from app.sources.local_folder import LocalFolderSource

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _create_job(db: Session, payload: dict) -> Job:
    job = Job(
        kind=JobKind.INGEST_LOCAL_FOLDER,
        status=JobStatus.PENDING,
        progress=0,
        payload=payload,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _run_local_folder_job(job_id: uuid.UUID, folder: Path, cleanup_dir: Path | None) -> None:
    """BackgroundTask entrypoint. Owns its own DB session via run_ingest."""
    try:
        source = LocalFolderSource(folder)
        run_ingest(job_id, source)
    except Exception:  # noqa: BLE001
        log.exception("local-folder ingest crashed for job %s", job_id)
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            if job is not None and job.status != JobStatus.SUCCEEDED:
                job.status = JobStatus.FAILED
                job.error = "ingest task crashed; see server logs"
                db.commit()
        finally:
            db.close()
    finally:
        if cleanup_dir is not None and cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)


@router.post(
    "/local-folder",
    response_model=JobCreated,
    status_code=202,
    summary="Ingest photos from a host folder path.",
)
def ingest_local_folder(
    body: LocalFolderIngestRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreated:
    folder = Path(body.path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"folder not found: {folder}")

    job = _create_job(db, payload={"mode": "path", "path": str(folder)})
    background.add_task(_run_local_folder_job, job.id, folder, None)
    return JobCreated(job_id=job.id)


@router.post(
    "/local-folder/upload",
    response_model=JobCreated,
    status_code=202,
    summary="Ingest photos from an uploaded ZIP archive.",
)
def ingest_local_folder_zip(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> JobCreated:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="upload must be a .zip file")

    temp_root = Path(tempfile.mkdtemp(prefix="album_ingest_"))
    extract_dir = temp_root / "extracted"
    extract_dir.mkdir()

    try:
        with zipfile.ZipFile(file.file) as zf:
            for member in zf.infolist():
                # Reject path traversal & absolute paths inside the archive.
                target = (extract_dir / member.filename).resolve()
                if not str(target).startswith(str(extract_dir.resolve())):
                    raise HTTPException(status_code=400, detail="unsafe zip entry rejected")
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"invalid zip: {exc}") from exc

    job = _create_job(
        db,
        payload={"mode": "zip", "original_filename": file.filename},
    )
    background.add_task(_run_local_folder_job, job.id, extract_dir, temp_root)
    return JobCreated(job_id=job.id)
