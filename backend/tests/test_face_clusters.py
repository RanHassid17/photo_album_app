"""People filter: face crops and naming.

The filter used to render a truncated cluster UUID, so there was no way to tell who a
person was or to label them. Clusters are global, so a name set once is reused by every
album created afterwards — these tests pin that down.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.main import app
from app.models import FaceCluster, FaceEmbedding, Photo

client = TestClient(app)


def _seed_cluster(tmp_path: Path, *, name: str | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """A photo with one detected face, and the cluster that face belongs to."""
    img_path = tmp_path / f"face_{uuid.uuid4().hex[:6]}.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 300), (180, 140, 120)).save(img_path, "JPEG")

    db = SessionLocal()
    try:
        photo = Photo(
            source="local_folder",
            source_ref=img_path.name,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            original_path=str(img_path),
            stored_path=str(img_path),
            width=400,
            height=300,
        )
        db.add(photo)
        db.flush()

        cluster = FaceCluster(
            name=name, representative_photo_id=photo.id, face_count=1
        )
        db.add(cluster)
        db.flush()

        db.add(
            FaceEmbedding(
                photo_id=photo.id,
                cluster_id=cluster.id,
                bbox={"x": 120, "y": 80, "w": 90, "h": 90},
                embedding=np.zeros(8, dtype=np.float32).tobytes(),
                embedding_dim=8,
            )
        )
        db.commit()
        return cluster.id, photo.id
    finally:
        db.close()


def test_rename_persists_and_is_listed(tmp_path: Path) -> None:
    cluster_id, _ = _seed_cluster(tmp_path)

    r = client.patch(f"/api/face-clusters/{cluster_id}", json={"name": "  סבתא  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "סבתא"  # trimmed

    listing = client.get("/api/face-clusters").json()
    assert [c["name"] for c in listing if c["id"] == str(cluster_id)] == ["סבתא"]


def test_rename_with_blank_clears_the_name(tmp_path: Path) -> None:
    cluster_id, _ = _seed_cluster(tmp_path, name="Dana")

    r = client.patch(f"/api/face-clusters/{cluster_id}", json={"name": "   "})
    assert r.status_code == 200
    assert r.json()["name"] is None


def test_rename_unknown_cluster_is_404() -> None:
    r = client.patch(f"/api/face-clusters/{uuid.uuid4()}", json={"name": "x"})
    assert r.status_code == 404


def test_thumb_returns_a_cropped_face(tmp_path: Path) -> None:
    cluster_id, _ = _seed_cluster(tmp_path)

    r = client.get(f"/api/face-clusters/{cluster_id}/thumb")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"

    img = Image.open(io.BytesIO(r.content))
    # 90px box + 40% padding on each side = 162px, clamped to the frame — and crucially
    # much smaller than the 400x300 original, i.e. it really is a crop.
    assert max(img.size) <= 162
    assert img.width < 400 and img.height < 300


def test_thumb_for_unknown_cluster_is_404() -> None:
    r = client.get(f"/api/face-clusters/{uuid.uuid4()}/thumb")
    assert r.status_code == 404
