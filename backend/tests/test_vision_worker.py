from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaceCluster, FaceEmbedding, Photo, PhotoLabel
from app.workers import vision as vision_module


def _insert_photo(stored_path: Path) -> uuid.UUID:
    db = SessionLocal()
    try:
        photo = Photo(
            source="local_folder",
            source_ref=stored_path.name,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,  # 64-char unique
            original_path=str(stored_path),
            stored_path=str(stored_path),
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return photo.id
    finally:
        db.close()


def _seed_jpeg(target: Path, color=(120, 80, 60)) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color).save(target, "JPEG")
    return target


@pytest.fixture
def stub_face_embeddings(monkeypatch):
    """Patch DeepFace.represent with a deterministic stub returning one 128-d face."""

    def fake_faces(_path, scale: float = 1.0):
        vec = np.linspace(0.0, 1.0, 128, dtype=np.float32)
        yield {
            "bbox": {"x": 10, "y": 10, "w": 32, "h": 32},
            "embedding_bytes": vec.tobytes(),
            "dim": 128,
        }

    monkeypatch.setattr(vision_module, "face_embeddings", fake_faces)


@pytest.fixture
def stub_label_objects(monkeypatch):
    """Patch YOLO call with deterministic labels."""

    def fake_labels(_path):
        yield "dog", 0.91
        yield "person", 0.66

    monkeypatch.setattr(vision_module, "label_objects", fake_labels)


def test_index_photo_writes_exif_blur_faces_labels(
    tmp_path: Path, stub_face_embeddings, stub_label_objects
) -> None:
    img = _seed_jpeg(tmp_path / "p.jpg")
    photo_id = _insert_photo(img)

    out = vision_module.index_photo.apply(args=[str(photo_id)]).get()

    assert out["face_count"] == 1
    assert out["label_count"] == 2
    assert out["errors"] == []

    db = SessionLocal()
    try:
        photo = db.get(Photo, photo_id)
        assert photo is not None
        assert photo.width == 64
        assert photo.height == 48
        assert photo.indexed_at is not None
        assert photo.blur_score is not None  # any number is fine; just exercised

        faces = db.scalars(select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)).all()
        assert len(faces) == 1
        assert faces[0].embedding_dim == 128
        assert len(faces[0].embedding) == 128 * 4  # float32 bytes
        assert faces[0].bbox == {"x": 10, "y": 10, "w": 32, "h": 32}

        labels = db.scalars(select(PhotoLabel).where(PhotoLabel.photo_id == photo_id)).all()
        assert {label.label for label in labels} == {"dog", "person"}
    finally:
        db.close()


def test_index_photo_records_error_when_face_extractor_fails(
    tmp_path: Path, stub_label_objects, monkeypatch
) -> None:
    img = _seed_jpeg(tmp_path / "p.jpg")
    photo_id = _insert_photo(img)

    def boom(_path):
        raise RuntimeError("kaboom")
        yield  # pragma: no cover

    monkeypatch.setattr(vision_module, "face_embeddings", boom)

    out = vision_module.index_photo.apply(args=[str(photo_id)]).get()

    assert out["face_count"] == 0
    assert any(e.startswith("faces:") for e in out["errors"])
    # Photo still marked indexed so we don't reprocess it forever.
    db = SessionLocal()
    try:
        photo = db.get(Photo, photo_id)
        assert photo is not None and photo.indexed_at is not None
    finally:
        db.close()


def test_index_photo_missing_file(tmp_path: Path) -> None:
    photo_id = _insert_photo(tmp_path / "ghost.jpg")  # never created on disk

    out = vision_module.index_photo.apply(args=[str(photo_id)]).get()
    assert out["errors"] == ["file_missing"]

    db = SessionLocal()
    try:
        photo = db.get(Photo, photo_id)
        assert photo is not None and photo.indexed_at is not None
    finally:
        db.close()


def test_cluster_faces_groups_similar_embeddings(tmp_path: Path) -> None:
    """Seed two visually-distinct embedding clusters and confirm HDBSCAN finds them."""
    img1 = _seed_jpeg(tmp_path / "a.jpg", color=(10, 10, 10))
    img2 = _seed_jpeg(tmp_path / "b.jpg", color=(200, 200, 200))
    pid1 = _insert_photo(img1)
    pid2 = _insert_photo(img2)

    rng = np.random.default_rng(42)

    # Cluster A: vectors near [1,0,0,...] with small noise; 4 of them on pid1.
    base_a = np.zeros(128, dtype=np.float32)
    base_a[0] = 1.0
    # Cluster B: vectors near [0,1,0,...]; 4 of them on pid2.
    base_b = np.zeros(128, dtype=np.float32)
    base_b[1] = 1.0

    db = SessionLocal()
    try:
        for _ in range(4):
            noise = rng.normal(0, 0.02, size=128).astype(np.float32)
            db.add(
                FaceEmbedding(
                    photo_id=pid1,
                    bbox={"x": 0, "y": 0, "w": 32, "h": 32},
                    embedding=(base_a + noise).tobytes(),
                    embedding_dim=128,
                )
            )
        for _ in range(4):
            noise = rng.normal(0, 0.02, size=128).astype(np.float32)
            db.add(
                FaceEmbedding(
                    photo_id=pid2,
                    bbox={"x": 0, "y": 0, "w": 32, "h": 32},
                    embedding=(base_b + noise).tobytes(),
                    embedding_dim=128,
                )
            )
        db.commit()
    finally:
        db.close()

    out = vision_module.cluster_faces.apply(kwargs={"min_cluster_size": 2}).get()
    assert out["new_clusters"] == 2
    assert out["clustered"] == 8
    assert out["noise"] == 0

    db = SessionLocal()
    try:
        clusters = db.scalars(select(FaceCluster)).all()
        assert len(clusters) == 2
        assert sorted(c.face_count for c in clusters) == [4, 4]

        all_embeddings = db.scalars(select(FaceEmbedding)).all()
        assert all(e.cluster_id is not None for e in all_embeddings)
    finally:
        db.close()


def test_index_photo_is_idempotent(
    tmp_path: Path, stub_face_embeddings, stub_label_objects
) -> None:
    """Indexing the same photo twice must replace its derived data, not append.

    Labels are unique on (photo_id, label). Appending violated that constraint on every
    re-index, which crashed the task -- and because index_photo is a chord header, the
    crash took cluster_faces with it, leaving embeddings but no people.
    """
    img = _seed_jpeg(tmp_path / "again.jpg")
    photo_id = _insert_photo(img)

    first = vision_module.index_photo.apply(args=[str(photo_id)]).get()
    second = vision_module.index_photo.apply(args=[str(photo_id)]).get()

    assert first["errors"] == []
    assert second["errors"] == []
    assert second["face_count"] == first["face_count"]
    assert second["label_count"] == first["label_count"]

    db = SessionLocal()
    try:
        labels = db.scalars(
            select(PhotoLabel).where(PhotoLabel.photo_id == photo_id)
        ).all()
        faces = db.scalars(
            select(FaceEmbedding).where(FaceEmbedding.photo_id == photo_id)
        ).all()
    finally:
        db.close()

    assert len(labels) == first["label_count"]   # not doubled
    assert len(faces) == first["face_count"]
