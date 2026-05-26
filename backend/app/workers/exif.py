from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import exifread
from PIL import Image


@dataclass(frozen=True, slots=True)
class PhotoMetadata:
    width: int | None
    height: int | None
    taken_at: datetime | None
    gps_lat: float | None
    gps_lng: float | None


def _ratio_to_float(value) -> float:  # exifread Ratio or IfdTag
    try:
        return float(value.num) / float(value.den)
    except (AttributeError, ZeroDivisionError):
        return float(value)


def _dms_to_decimal(dms_values, ref: str) -> float:
    d, m, s = (_ratio_to_float(v) for v in dms_values)
    decimal = d + (m / 60.0) + (s / 3600.0)
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_taken_at(tags) -> datetime | None:
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        raw = tags.get(key)
        if raw is None:
            continue
        try:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _parse_gps(tags) -> tuple[float | None, float | None]:
    lat_dms = tags.get("GPS GPSLatitude")
    lat_ref = tags.get("GPS GPSLatitudeRef")
    lng_dms = tags.get("GPS GPSLongitude")
    lng_ref = tags.get("GPS GPSLongitudeRef")
    if not (lat_dms and lat_ref and lng_dms and lng_ref):
        return None, None
    try:
        lat = _dms_to_decimal(lat_dms.values, str(lat_ref))
        lng = _dms_to_decimal(lng_dms.values, str(lng_ref))
    except Exception:  # noqa: BLE001
        return None, None
    return lat, lng


def extract_exif_metadata(path: Path) -> PhotoMetadata:
    width: int | None = None
    height: int | None = None
    try:
        with Image.open(path) as img:
            width, height = img.size
    except Exception:  # noqa: BLE001
        pass

    with path.open("rb") as fh:
        tags = exifread.process_file(fh, details=False)

    taken_at = _parse_taken_at(tags)
    gps_lat, gps_lng = _parse_gps(tags)

    return PhotoMetadata(
        width=width,
        height=height,
        taken_at=taken_at,
        gps_lat=gps_lat,
        gps_lng=gps_lng,
    )
