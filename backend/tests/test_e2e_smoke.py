"""End-to-end smoke test for the whole MVP flow.

Walks every backend phase a user touches:
    B.1 ingest → B.3 filter → B.4 selection → B.5 layout → B.6 export.

Runs against the real Postgres test DB and the FastAPI app via TestClient.
No external services (Anthropic falls back to the deterministic path because the
test environment has no real API key).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _seed_zip(make_image, tmp_path: Path, count: int) -> io.BytesIO:
    """Build an in-memory ZIP containing `count` real but tiny photos."""
    staged: list[Path] = []
    for i in range(count):
        # Larger-than-tiny so quality reports have something to chew on.
        staged.append(
            make_image(f"staging/p{i}.jpg", color=(20 * i, 200 - 20 * i, 80), size=(800, 600))
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in staged:
            zf.write(path, arcname=path.name)
    buf.seek(0)
    return buf


def test_full_mvp_flow_ingest_to_export(
    tmp_path: Path, tmp_storage_dir: Path, make_image
) -> None:
    # --- B.1: ingest ---
    zip_buf = _seed_zip(make_image, tmp_path, count=5)
    r = client.post(
        "/api/sources/local-folder/upload",
        files={"file": ("smoke.zip", zip_buf, "application/zip")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    poll = client.get(f"/api/jobs/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "succeeded"
    assert poll.json()["payload"]["inserted"] == 5

    # --- B.3: filter / search ---
    r = client.post("/api/photos/search", json={"limit": 100, "offset": 0})
    assert r.status_code == 200
    search = r.json()
    assert search["total"] == 5
    photo_ids = [item["id"] for item in search["items"]]
    assert len(photo_ids) == 5

    # --- B.4: AI selection (deterministic fallback) ---
    r = client.post(
        "/api/selection/suggest",
        json={"photo_ids": photo_ids, "target_count": 3, "criteria": "best shots"},
    )
    assert r.status_code == 200
    selection = r.json()
    # Real Claude or deterministic fallback — either is a valid smoke-test outcome.
    assert len(selection["picks"]) == 3
    picked_ids = [p["photo_id"] for p in selection["picks"]]
    assert all(pid in photo_ids for pid in picked_ids)

    # --- B.5: AI layout (deterministic fallback) ---
    r = client.post(
        "/api/layouts/suggest",
        json={
            "photo_ids": picked_ids,
            "page_count": 2,
            "style": "modern",
            "name": "Smoke album",
        },
    )
    assert r.status_code == 201
    layout = r.json()
    album_id = layout["album_id"]
    assert len(layout["layout"]["pages"]) == 2

    # Album list + detail
    list_r = client.get("/api/albums")
    assert list_r.status_code == 200
    assert any(a["id"] == album_id for a in list_r.json())

    detail = client.get(f"/api/albums/{album_id}")
    assert detail.status_code == 200
    assert detail.json()["page_count"] == 2

    # --- B.6: export ---
    quality = client.get(f"/api/albums/{album_id}/export/quality")
    assert quality.status_code == 200
    quality_body = quality.json()
    assert quality_body["album_id"] == album_id
    # Vision worker is disabled in tests so width/height aren't recorded, which means
    # the report has no warnings to emit. We just verify the endpoint shape here;
    # test_export.py covers warning generation when dimensions are present.
    assert isinstance(quality_body["low_resolution_warnings"], list)

    pdf_r = client.post(f"/api/albums/{album_id}/export/pdf")
    assert pdf_r.status_code == 200
    assert pdf_r.headers["content-type"] == "application/pdf"
    assert pdf_r.content.startswith(b"%PDF-")

    zip_r = client.post(f"/api/albums/{album_id}/export/print")
    assert zip_r.status_code == 200
    assert zip_r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_r.content)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        # 3 unique picked photos × 3 sizes = 9 image entries.
        image_entries = [n for n in names if n != "manifest.json"]
        assert len(image_entries) == 9
        for size_label in ("10x15", "13x18", "20x30"):
            assert sum(1 for n in image_entries if n.startswith(f"{size_label}/")) == 3
