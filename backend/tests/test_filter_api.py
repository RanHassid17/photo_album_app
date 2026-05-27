from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.main import app
from app.models import FaceCluster, FaceEmbedding, Photo, PhotoLabel

client = TestClient(app)


def _seed_photo(
    *,
    stored_path: Path,
    taken_at: datetime | None = None,
    gps_lat: float | None = None,
    gps_lng: float | None = None,
    width: int = 64,
    height: int = 48,
) -> uuid.UUID:
    db = SessionLocal()
    try:
        photo = Photo(
            source="local_folder",
            source_ref=stored_path.name,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            original_path=str(stored_path),
            stored_path=str(stored_path),
            taken_at=taken_at,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            width=width,
            height=height,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return photo.id
    finally:
        db.close()


def _add_face_cluster() -> uuid.UUID:
    db = SessionLocal()
    try:
        cluster = FaceCluster(face_count=0)
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        return cluster.id
    finally:
        db.close()


def _attach_face(photo_id: uuid.UUID, cluster_id: uuid.UUID | None) -> None:
    db = SessionLocal()
    try:
        db.add(
            FaceEmbedding(
                photo_id=photo_id,
                cluster_id=cluster_id,
                bbox={"x": 0, "y": 0, "w": 8, "h": 8},
                embedding=np.zeros(128, dtype=np.float32).tobytes(),
                embedding_dim=128,
            )
        )
        db.commit()
    finally:
        db.close()


def _attach_label(photo_id: uuid.UUID, label: str, confidence: float = 0.9) -> None:
    db = SessionLocal()
    try:
        db.add(PhotoLabel(photo_id=photo_id, label=label, confidence=confidence))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def seeded(tmp_path: Path, tmp_storage_dir: Path, make_image):
    """Seed a varied corpus of photos for filter tests."""
    img_a = make_image("a.jpg")  # 2024-01-01, in box, dog + cluster1
    img_b = make_image("b.jpg")  # 2024-06-15, no GPS, cat + cluster2
    img_c = make_image("c.jpg")  # 2025-03-01, out of box, no faces, no labels

    pid_a = _seed_photo(
        stored_path=img_a,
        taken_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        gps_lat=32.0,
        gps_lng=34.0,
    )
    pid_b = _seed_photo(
        stored_path=img_b,
        taken_at=datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc),
    )
    pid_c = _seed_photo(
        stored_path=img_c,
        taken_at=datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc),
        gps_lat=51.5,
        gps_lng=-0.1,
    )

    c1 = _add_face_cluster()
    c2 = _add_face_cluster()

    _attach_face(pid_a, c1)
    _attach_face(pid_b, c2)
    _attach_label(pid_a, "dog")
    _attach_label(pid_b, "cat")

    return {
        "pid_a": pid_a,
        "pid_b": pid_b,
        "pid_c": pid_c,
        "cluster_a": c1,
        "cluster_b": c2,
    }


def test_search_no_filters_returns_all(seeded) -> None:
    r = client.post("/api/photos/search", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    # Sorted by taken_at desc.
    assert body["items"][0]["id"] == str(seeded["pid_c"])


def test_filter_by_date_range(seeded) -> None:
    r = client.post(
        "/api/photos/search",
        json={"date_from": "2024-01-01T00:00:00Z", "date_to": "2024-12-31T23:59:59Z"},
    )
    body = r.json()
    assert body["total"] == 2
    ids = {item["id"] for item in body["items"]}
    assert ids == {str(seeded["pid_a"]), str(seeded["pid_b"])}


def test_filter_by_person_cluster(seeded) -> None:
    r = client.post(
        "/api/photos/search",
        json={"person_cluster_ids": [str(seeded["cluster_a"])]},
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(seeded["pid_a"])


def test_filter_by_animal_label(seeded) -> None:
    r = client.post("/api/photos/search", json={"animal_labels": ["cat"]})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(seeded["pid_b"])


def test_filter_by_gps_bbox_excludes_outside_and_null(seeded) -> None:
    r = client.post(
        "/api/photos/search",
        json={
            "gps_bbox": {
                "min_lat": 31.0,
                "max_lat": 33.0,
                "min_lng": 33.0,
                "max_lng": 35.0,
            }
        },
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(seeded["pid_a"])


def test_filters_combine_with_and(seeded) -> None:
    # Date 2024 + dog label → only pid_a.
    r = client.post(
        "/api/photos/search",
        json={
            "date_from": "2024-01-01T00:00:00Z",
            "date_to": "2024-12-31T23:59:59Z",
            "animal_labels": ["dog"],
        },
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(seeded["pid_a"])


def test_pagination(seeded) -> None:
    r1 = client.post("/api/photos/search", json={"limit": 2, "offset": 0})
    r2 = client.post("/api/photos/search", json={"limit": 2, "offset": 2})
    assert r1.json()["total"] == 3
    assert len(r1.json()["items"]) == 2
    assert len(r2.json()["items"]) == 1


def test_invalid_bbox_rejected() -> None:
    r = client.post(
        "/api/photos/search",
        json={
            "gps_bbox": {
                "min_lat": 50.0,
                "max_lat": 10.0,
                "min_lng": 0.0,
                "max_lng": 1.0,
            }
        },
    )
    assert r.status_code == 422


def test_invalid_date_range_rejected() -> None:
    r = client.post(
        "/api/photos/search",
        json={
            "date_from": "2025-01-01T00:00:00Z",
            "date_to": "2024-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 422


def test_face_clusters_endpoint(seeded) -> None:
    r = client.get("/api/face-clusters")
    assert r.status_code == 200
    rows = r.json()
    # The seeded clusters have face_count=0 because we wrote embeddings without updating
    # the cluster tally; still expect both rows back.
    assert len(rows) == 2


def test_labels_endpoint_returns_counts(seeded) -> None:
    r = client.get("/api/labels")
    assert r.status_code == 200
    rows = r.json()
    label_map = {row["label"]: row["photo_count"] for row in rows}
    assert label_map == {"dog": 1, "cat": 1}
