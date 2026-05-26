from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Photo

client = TestClient(app)


def test_local_folder_path_ingest_end_to_end(
    tmp_path: Path, tmp_storage_dir: Path, make_image
) -> None:
    make_image("a.jpg")
    make_image("nested/b.png")

    r = client.post("/api/sources/local-folder", json={"path": str(tmp_path)})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    poll = client.get(f"/api/jobs/{job_id}")
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "succeeded"
    assert body["progress"] == 100
    assert body["payload"]["inserted"] == 2

    db = SessionLocal()
    try:
        assert len(db.scalars(select(Photo)).all()) == 2
    finally:
        db.close()


def test_local_folder_path_missing_returns_400(tmp_path: Path, tmp_storage_dir: Path) -> None:
    r = client.post("/api/sources/local-folder", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 400


def test_jobs_404_for_unknown_id(tmp_storage_dir: Path) -> None:
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_zip_upload_ingest(tmp_path: Path, tmp_storage_dir: Path, make_image) -> None:
    img_a = make_image("staging/a.jpg")
    img_b = make_image("staging/nested/b.png")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(img_a, arcname="a.jpg")
        zf.write(img_b, arcname="nested/b.png")
    buf.seek(0)

    r = client.post(
        "/api/sources/local-folder/upload",
        files={"file": ("album.zip", buf, "application/zip")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    poll = client.get(f"/api/jobs/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "succeeded"
    assert poll.json()["payload"]["inserted"] == 2


def test_zip_upload_rejects_path_traversal(tmp_path: Path, tmp_storage_dir: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.jpg", b"not a real jpeg")
    buf.seek(0)

    r = client.post(
        "/api/sources/local-folder/upload",
        files={"file": ("bad.zip", buf, "application/zip")},
    )
    assert r.status_code == 400
