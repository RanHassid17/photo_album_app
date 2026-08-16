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


def _seed_cluster_with_faces(tmp_path: Path, faces: list[dict]) -> uuid.UUID:
    """One cluster whose faces differ only in the qualities the ranking cares about."""
    img_path = tmp_path / f"multi_{uuid.uuid4().hex[:6]}.jpg"
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
        cluster = FaceCluster(representative_photo_id=photo.id, face_count=len(faces))
        db.add(cluster)
        db.flush()
        for spec in faces:
            db.add(
                FaceEmbedding(
                    photo_id=photo.id,
                    cluster_id=cluster.id,
                    bbox=spec["bbox"],
                    embedding=np.zeros(8, dtype=np.float32).tobytes(),
                    embedding_dim=8,
                    sharpness=spec.get("sharpness"),
                    frontality=spec.get("frontality"),
                )
            )
        db.commit()
        return cluster.id
    finally:
        db.close()


def test_representative_prefers_a_clear_frontal_face_over_a_bigger_one(
    tmp_path: Path,
) -> None:
    """The whole point: a large blurry profile must lose to a smaller clear portrait."""
    from app.api.face_clusters import _representative_face

    clear = {"x": 100, "y": 60, "w": 70, "h": 70, "sharpness": 260.0, "frontality": 0.44}
    big_blurry_profile = {
        "x": 40, "y": 40, "w": 180, "h": 180, "sharpness": 9.0, "frontality": 0.22,
    }
    cluster_id = _seed_cluster_with_faces(
        tmp_path,
        [
            {"bbox": {k: big_blurry_profile[k] for k in "xywh"},
             "sharpness": big_blurry_profile["sharpness"],
             "frontality": big_blurry_profile["frontality"]},
            {"bbox": {k: clear[k] for k in "xywh"},
             "sharpness": clear["sharpness"], "frontality": clear["frontality"]},
        ],
    )

    db = SessionLocal()
    try:
        cluster = db.get(FaceCluster, cluster_id)
        _, bbox = _representative_face(db, cluster)
    finally:
        db.close()

    assert bbox["w"] == 70, "picked the big blurry profile instead of the clear face"


def test_representative_avoids_a_face_cut_off_by_the_frame(tmp_path: Path) -> None:
    """A face at the edge crops to half a head, so an equally good centred face wins."""
    from app.api.face_clusters import _representative_face

    cluster_id = _seed_cluster_with_faces(
        tmp_path,
        [
            # Flush against the left edge: the padded crop cannot fit.
            {"bbox": {"x": 0, "y": 100, "w": 90, "h": 90},
             "sharpness": 300.0, "frontality": 0.45},
            {"bbox": {"x": 150, "y": 100, "w": 85, "h": 85},
             "sharpness": 300.0, "frontality": 0.45},
        ],
    )

    db = SessionLocal()
    try:
        cluster = db.get(FaceCluster, cluster_id)
        _, bbox = _representative_face(db, cluster)
    finally:
        db.close()

    assert bbox["x"] == 150


def test_representative_still_returns_a_face_when_none_are_measured(
    tmp_path: Path,
) -> None:
    """Faces indexed before quality scoring existed have no scores — show them anyway."""
    from app.api.face_clusters import _representative_face

    cluster_id = _seed_cluster_with_faces(
        tmp_path,
        [
            {"bbox": {"x": 100, "y": 60, "w": 40, "h": 40}},
            {"bbox": {"x": 150, "y": 60, "w": 95, "h": 95}},
        ],
    )

    db = SessionLocal()
    try:
        cluster = db.get(FaceCluster, cluster_id)
        _, bbox = _representative_face(db, cluster)
    finally:
        db.close()

    # No scores to go on, so size is the only remaining signal.
    assert bbox["w"] == 95
