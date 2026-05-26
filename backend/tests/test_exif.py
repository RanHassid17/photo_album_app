from __future__ import annotations

from datetime import datetime
from pathlib import Path

import piexif
from PIL import Image

from app.workers.exif import extract_exif_metadata


def test_extracts_dimensions_only_when_no_exif(tmp_path: Path) -> None:
    p = tmp_path / "no_exif.jpg"
    Image.new("RGB", (40, 30), (255, 0, 0)).save(p, "JPEG")

    meta = extract_exif_metadata(p)
    assert meta.width == 40
    assert meta.height == 30
    assert meta.taken_at is None
    assert meta.gps_lat is None
    assert meta.gps_lng is None


def test_extracts_taken_at_and_gps(tmp_path: Path) -> None:
    p = tmp_path / "exif.jpg"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(p, "JPEG")

    exif_dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2024:08:15 14:22:01",
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((32, 1), (4, 1), (39, 1)),  # 32 deg 4' 39" N
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: ((34, 1), (47, 1), (0, 1)),
        },
        "1st": {},
        "thumbnail": None,
    }
    piexif.insert(piexif.dump(exif_dict), str(p))

    meta = extract_exif_metadata(p)
    assert meta.taken_at == datetime(2024, 8, 15, 14, 22, 1)
    assert meta.gps_lat is not None and abs(meta.gps_lat - (32 + 4 / 60 + 39 / 3600)) < 1e-6
    assert meta.gps_lng is not None and abs(meta.gps_lng - (34 + 47 / 60)) < 1e-6
