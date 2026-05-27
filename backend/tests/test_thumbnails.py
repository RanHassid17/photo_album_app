from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.main import app
from app.models import Photo
from app.services.thumbnails import (
    get_or_create_thumbnail,
    thumbnail_path_for,
)

client = TestClient(app)


def _insert_photo(stored_path: Path) -> uuid.UUID:
    db = SessionLocal()
    try:
        photo = Photo(
            source="local_folder",
            source_ref=stored_path.name,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            original_path=str(stored_path),
            stored_path=str(stored_path),
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return photo.id
    finally:
        db.close()


def test_generates_webp_within_512px(tmp_path: Path, tmp_storage_dir: Path) -> None:
    src = tmp_path / "big.jpg"
    Image.new("RGB", (2000, 1000), (10, 20, 30)).save(src, "JPEG")
    photo_id = uuid.uuid4()

    thumb = get_or_create_thumbnail(photo_id, src)
    assert thumb.exists()
    assert thumb.suffix == ".webp"
    with Image.open(thumb) as img:
        assert max(img.size) == 512
        assert img.format == "WEBP"


def test_second_call_reuses_cached(tmp_path: Path, tmp_storage_dir: Path) -> None:
    src = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100), (50, 50, 50)).save(src, "JPEG")
    photo_id = uuid.uuid4()

    first = get_or_create_thumbnail(photo_id, src)
    mtime_first = first.stat().st_mtime_ns
    second = get_or_create_thumbnail(photo_id, src)
    assert second == first
    assert second.stat().st_mtime_ns == mtime_first  # not rewritten


def test_thumb_endpoint_serves_webp(tmp_path: Path, tmp_storage_dir: Path) -> None:
    src = tmp_path / "p.jpg"
    Image.new("RGB", (300, 300), (200, 100, 50)).save(src, "JPEG")
    pid = _insert_photo(src)

    r = client.get(f"/api/photos/{pid}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert len(r.content) > 0
    # cached on disk
    assert thumbnail_path_for(pid).exists()


def test_file_endpoint_serves_original(tmp_path: Path, tmp_storage_dir: Path) -> None:
    src = tmp_path / "p.jpg"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(src, "JPEG")
    pid = _insert_photo(src)

    r = client.get(f"/api/photos/{pid}/file")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_thumb_404_for_unknown_photo(tmp_storage_dir: Path) -> None:
    r = client.get(f"/api/photos/{uuid.uuid4()}/thumb")
    assert r.status_code == 404


def test_thumb_410_when_file_missing(tmp_path: Path, tmp_storage_dir: Path) -> None:
    ghost = tmp_path / "missing.jpg"  # never written
    pid = _insert_photo(ghost)
    r = client.get(f"/api/photos/{pid}/thumb")
    assert r.status_code == 410
