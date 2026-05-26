from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, JobKind, JobStatus, Photo
from app.services.ingest import run_ingest
from app.sources.local_folder import LocalFolderSource


def _make_job(payload: dict) -> Job:
    db = SessionLocal()
    try:
        job = Job(kind=JobKind.INGEST_LOCAL_FOLDER, payload=payload)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def test_ingest_inserts_photos_and_copies_files(
    tmp_path: Path, tmp_storage_dir: Path, make_image
) -> None:
    folder = tmp_path / "src"
    make_image("src/a.jpg", color=(10, 20, 30))
    make_image("src/sub/b.png", color=(40, 50, 60))

    job = _make_job({"mode": "path", "path": str(folder)})

    result = run_ingest(job.id, LocalFolderSource(folder))

    assert result.scanned == 2
    assert result.inserted == 2
    assert result.duplicates == 0
    assert result.errors == 0

    db = SessionLocal()
    try:
        photos = db.scalars(select(Photo)).all()
        assert len(photos) == 2
        for p in photos:
            assert p.source == "local_folder"
            assert Path(p.stored_path).exists()
            assert Path(p.stored_path).is_file()
            assert len(p.sha256) == 64

        refreshed = db.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.SUCCEEDED
        assert refreshed.progress == 100
        assert refreshed.payload["inserted"] == 2
    finally:
        db.close()


def test_ingest_dedupes_by_sha256(tmp_path: Path, tmp_storage_dir: Path, make_image) -> None:
    folder = tmp_path / "src"
    original = make_image("src/orig.jpg", color=(99, 99, 99))
    # An exact byte-copy with a different name and nested path.
    dup_target = tmp_path / "src" / "sub" / "dup.jpg"
    dup_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, dup_target)

    job = _make_job({"mode": "path", "path": str(folder)})
    result = run_ingest(job.id, LocalFolderSource(folder))

    assert result.scanned == 2
    assert result.inserted == 1
    assert result.duplicates == 1

    db = SessionLocal()
    try:
        photos = db.scalars(select(Photo)).all()
        assert len(photos) == 1
    finally:
        db.close()


def test_ingest_dedupes_across_jobs(tmp_path: Path, tmp_storage_dir: Path, make_image) -> None:
    folder = tmp_path / "src"
    make_image("src/a.jpg", color=(1, 2, 3))

    job1 = _make_job({"mode": "path", "path": str(folder)})
    run_ingest(job1.id, LocalFolderSource(folder))

    job2 = _make_job({"mode": "path", "path": str(folder)})
    result = run_ingest(job2.id, LocalFolderSource(folder))

    assert result.scanned == 1
    assert result.inserted == 0
    assert result.duplicates == 1

    db = SessionLocal()
    try:
        photos = db.scalars(select(Photo)).all()
        assert len(photos) == 1
    finally:
        db.close()
