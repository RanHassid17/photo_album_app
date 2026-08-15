from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.db import SessionLocal
from app.exporters import PRINT_SIZES
from app.exporters.print_zip import quality_report
from app.main import app
from app.models import Album, AlbumItem, AlbumPage, AlbumStyle, CommentPosition, Photo
from app.services.export import (
    AlbumNotFoundError,
    album_quality_report,
    export_album_pdf,
    export_album_print_zip,
)

client = TestClient(app)


def _make_jpeg(path: Path, *, size: tuple[int, int] = (600, 400)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(180, 60, 40)).save(path, format="JPEG")


def _seed_album(
    tmp_path: Path, *, n_photos: int = 2, photo_size: tuple[int, int] = (600, 400)
) -> uuid.UUID:
    """Create an album with one page and N photos laid out in a row."""
    db = SessionLocal()
    try:
        photos: list[Photo] = []
        for i in range(n_photos):
            jpeg_path = tmp_path / f"p_{i}.jpg"
            _make_jpeg(jpeg_path, size=photo_size)
            photo = Photo(
                source="local_folder",
                source_ref=f"p_{uuid.uuid4().hex[:6]}.jpg",
                sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                original_path=str(jpeg_path),
                stored_path=str(jpeg_path),
                width=photo_size[0],
                height=photo_size[1],
            )
            db.add(photo)
            photos.append(photo)
        db.flush()

        album = Album(
            name="Holiday",
            style=AlbumStyle.MODERN,
            page_count=1,
            used_fallback=True,
        )
        db.add(album)
        db.flush()

        page = AlbumPage(
            album_id=album.id,
            index=0,
            layout_json={"rows": 1, "cols": n_photos, "gap": 0.02},
        )
        db.add(page)
        db.flush()

        # Evenly slice the page width across photos.
        cell_w = 1.0 / n_photos
        for i, photo in enumerate(photos):
            db.add(
                AlbumItem(
                    page_id=page.id,
                    photo_id=photo.id,
                    position_index=i,
                    position={
                        "x": i * cell_w + 0.01,
                        "y": 0.1,
                        "w": cell_w - 0.02,
                        "h": 0.8,
                        "rotation_deg": 0.0,
                    },
                    comment="hello" if i == 0 else None,
                    comment_position=CommentPosition.BELOW if i == 0 else CommentPosition.NONE,
                )
            )
        db.commit()
        return album.id
    finally:
        db.close()


# ---------- PDF ----------


def test_render_album_pdf_produces_valid_pdf(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=2)

    db = SessionLocal()
    try:
        bundle = export_album_pdf(db, album_id)
    finally:
        db.close()

    assert bundle.media_type == "application/pdf"
    assert bundle.filename.endswith(".pdf")
    assert bundle.data.startswith(b"%PDF-")
    # Pillow writes valid PDFs that end in %%EOF (possibly followed by whitespace).
    assert b"%%EOF" in bundle.data[-64:]


def test_pdf_export_endpoint(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=2)
    r = client.post(f"/api/albums/{album_id}/export/pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF-")


def test_pdf_export_404_for_unknown_album() -> None:
    r = client.post(f"/api/albums/{uuid.uuid4()}/export/pdf")
    assert r.status_code == 404


def test_pdf_export_service_raises_for_missing_album() -> None:
    db = SessionLocal()
    try:
        import pytest

        with pytest.raises(AlbumNotFoundError):
            export_album_pdf(db, uuid.uuid4())
    finally:
        db.close()


# ---------- Print ZIP ----------


def test_print_zip_has_a_folder_per_size(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=2, photo_size=(4000, 3000))

    db = SessionLocal()
    try:
        bundle = export_album_print_zip(db, album_id)
    finally:
        db.close()

    assert bundle.media_type == "application/zip"
    assert bundle.filename.endswith("-print.zip")

    with zipfile.ZipFile(io.BytesIO(bundle.data)) as zf:
        names = zf.namelist()
        for size in PRINT_SIZES:
            # Paths are now <album>/<size>/<album>_p<page>_<pos>.jpg per prompt spec §14.
            # recommended/<size>/ also contains the label, so exclude it here.
            per_size = [
                n for n in names
                if f"/{size.label}/" in n and "/recommended/" not in n
            ]
            assert len(per_size) == 2
        assert "manifest.json" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["dpi"] == 300
        assert len(manifest["sizes_cm"]) == len(PRINT_SIZES)
        # 4000x3000 fills every size except 30x40 (which needs 4724x3543).
        assert {w["size"] for w in manifest["low_resolution_warnings"]} == {"30x40"}
        rec = manifest["recommended_sizes"][0]
        # Seeded photos sit in small cells, so the layout — not the pixels — decides.
        assert rec["recommended_size"] == rec["layout_size"]
        assert rec["max_by_resolution"] == "20x30"


def test_print_zip_resizes_to_exact_300dpi_pixels(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(4000, 3000))

    db = SessionLocal()
    try:
        bundle = export_album_print_zip(db, album_id)
    finally:
        db.close()

    with zipfile.ZipFile(io.BytesIO(bundle.data)) as zf:
        sample_name = next(n for n in zf.namelist() if "/10x15/" in n)
        img = Image.open(io.BytesIO(zf.read(sample_name)))
        # 10x15 cm @ 300 DPI = 1181x1772 px in portrait orientation.
        # Source is landscape, so the box is rotated to landscape: 1772x1181.
        assert (img.width, img.height) == (1772, 1181)


def test_print_zip_endpoint(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(2400, 1600))
    r = client.post(f"/api/albums/{album_id}/export/print")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert zipfile.is_zipfile(io.BytesIO(r.content))


def test_print_zip_dedupes_repeated_photos(tmp_path: Path) -> None:
    """A photo placed on multiple pages should appear once per size, not N times."""
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(4000, 3000))

    # Add a second page reusing the same photo.
    db = SessionLocal()
    try:
        album = db.get(Album, album_id)
        assert album is not None
        first_photo_id = album.pages[0].items[0].photo_id
        page2 = AlbumPage(
            album_id=album.id,
            index=1,
            layout_json={"rows": 1, "cols": 1, "gap": 0.02},
        )
        db.add(page2)
        db.flush()
        db.add(
            AlbumItem(
                page_id=page2.id,
                photo_id=first_photo_id,
                position_index=0,
                position={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "rotation_deg": 0.0},
                comment=None,
                comment_position=CommentPosition.NONE,
            )
        )
        db.commit()

        bundle = export_album_print_zip(db, album_id)
    finally:
        db.close()

    with zipfile.ZipFile(io.BytesIO(bundle.data)) as zf:
        image_entries = [n for n in zf.namelist() if n != "manifest.json"]
        # One copy per size, plus a single copy in recommended/.
        recommended = [n for n in image_entries if "/recommended/" in n]
        assert len(recommended) == 1
        assert len(image_entries) == len(PRINT_SIZES) + 1


# ---------- Quality report ----------


def test_low_res_warning_flagged_for_small_photos(tmp_path: Path) -> None:
    # 400x300 is well below 10x15@300dpi (1181x1772 portrait / 1772x1181 landscape).
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(400, 300))

    db = SessionLocal()
    try:
        report = album_quality_report(db, album_id)
    finally:
        db.close()

    # 400x300 is too small for every standard size.
    assert len(report.warnings) == len(PRINT_SIZES)
    assert {w.size_label for w in report.warnings} == {s.label for s in PRINT_SIZES}
    # Nothing is safe to print at 300 DPI.
    assert len(report.advice) == 1
    assert report.advice[0].recommended_size is None
    assert report.advice[0].max_by_resolution is None


def test_quality_endpoint_returns_warnings(tmp_path: Path) -> None:
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(400, 300))
    r = client.get(f"/api/albums/{album_id}/export/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["album_id"] == str(album_id)
    assert len(body["low_resolution_warnings"]) == len(PRINT_SIZES)
    sample = body["low_resolution_warnings"][0]
    assert sample["original_w"] == 400
    assert sample["original_h"] == 300


def test_quality_report_empty_for_large_source(tmp_path: Path) -> None:
    # Must clear the largest size (30x40 => 4724x3543 landscape).
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(5000, 4000))

    db = SessionLocal()
    try:
        report = album_quality_report(db, album_id)
    finally:
        db.close()

    assert report.warnings == []


def test_quality_report_skips_photos_with_unknown_dimensions(tmp_path: Path) -> None:
    """If width/height aren't recorded (e.g. indexer never ran), we don't warn."""
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(400, 300))

    db = SessionLocal()
    try:
        album = db.get(Album, album_id)
        assert album is not None
        photo_id = album.pages[0].items[0].photo_id
        photo = db.get(Photo, photo_id)
        assert photo is not None
        photo.width = None
        photo.height = None
        db.commit()
        # quality_report (the pure function) receives current photo state.
        report = quality_report(album, [photo])
    finally:
        db.close()

    assert report.warnings == []


# ---------- Hebrew album names in Content-Disposition ----------

def test_export_with_hebrew_album_name_does_not_500(tmp_path: Path) -> None:
    """Starlette encodes headers as latin-1.

    The raw album name used to be interpolated into the plain `filename=` parameter, so
    any Hebrew name raised UnicodeEncodeError and the export 500'd. That is why exports
    "sometimes" failed — it depended on whether the album had been named.
    """
    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(1200, 900))

    db = SessionLocal()
    try:
        album = db.get(Album, album_id)
        assert album is not None
        album.name = "קיץ 2024 בכרמל"
        db.commit()
    finally:
        db.close()

    for kind in ("pdf", "print"):
        r = client.post(f"/api/albums/{album_id}/export/{kind}")
        assert r.status_code == 200, f"{kind}: {r.text[:200]}"

        disposition = r.headers["content-disposition"]
        # Must survive the header encoding Starlette actually uses.
        disposition.encode("latin-1")
        # The real Hebrew name still travels, percent-encoded, per RFC 5987.
        assert "filename*=UTF-8''" in disposition
        assert "%D7" in disposition  # UTF-8 lead byte for Hebrew


def test_ascii_fallback_keeps_extension_and_never_empties() -> None:
    from app.api.exports import _ascii_fallback

    assert _ascii_fallback("קיץ.pdf") == "album.pdf"
    assert _ascii_fallback("Summer_2024.pdf") == "Summer_2024.pdf"
    assert _ascii_fallback("קיץ 2024 בכרמל-print.zip").endswith(".zip")
    assert _ascii_fallback("קיץ") == "album"


def test_recommendation_follows_layout_area_not_just_resolution(tmp_path: Path) -> None:
    """A hero photo should be recommended for a bigger print than a small one.

    "Largest size the pixels allow" returned 30x40 for every modern photo, which told
    the user nothing. The album's own design has to drive it.
    """
    from app.exporters.print_zip import max_size_for_resolution, size_for_page_area

    # Same enormous source, different prominence on the page.
    assert size_for_page_area(0.60) == "30x40"
    assert size_for_page_area(0.32) == "20x30"
    assert size_for_page_area(0.12) == "13x18"
    assert size_for_page_area(0.02) == "10x15"

    # Resolution still acts as a ceiling, never a floor.
    # 10x15 landscape needs 1772x1181; 13x18 needs 2126x1535.
    assert max_size_for_resolution(1800, 1200) == "10x15"

    album_id = _seed_album(tmp_path, n_photos=1, photo_size=(1800, 1200))
    db = SessionLocal()
    try:
        album = db.get(Album, album_id)
        assert album is not None
        item = album.pages[0].items[0]
        item.position = {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9, "rotation_deg": 0.0}
        db.commit()
        report = album_quality_report(db, album_id)
    finally:
        db.close()

    advice = report.advice[0]
    assert advice.layout_size == "30x40"          # the design wants a big print
    assert advice.max_by_resolution == "10x15"    # the pixels do not allow it
    assert advice.recommended_size == "10x15"     # ceiling wins
    assert advice.limited_by_resolution is True
