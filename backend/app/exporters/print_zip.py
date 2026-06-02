from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.models import Album, Photo

log = logging.getLogger(__name__)

PRINT_DPI = 300
_CM_PER_INCH = 2.54


@dataclass(frozen=True, slots=True)
class PrintSize:
    label: str  # e.g. "10x15" — used as folder name and ZIP path prefix
    width_cm: float
    height_cm: float

    @property
    def width_px(self) -> int:
        return int(round(self.width_cm / _CM_PER_INCH * PRINT_DPI))

    @property
    def height_px(self) -> int:
        return int(round(self.height_cm / _CM_PER_INCH * PRINT_DPI))


PRINT_SIZES: tuple[PrintSize, ...] = (
    PrintSize(label="10x15", width_cm=10.0, height_cm=15.0),
    PrintSize(label="13x18", width_cm=13.0, height_cm=18.0),
    PrintSize(label="20x30", width_cm=20.0, height_cm=30.0),
)


@dataclass(slots=True)
class QualityWarning:
    photo_id: str
    original_w: int | None
    original_h: int | None
    size_label: str
    required_w: int
    required_h: int


@dataclass(slots=True)
class QualityReport:
    warnings: list[QualityWarning]

    def to_jsonable(self) -> list[dict]:
        return [
            {
                "photo_id": w.photo_id,
                "original_w": w.original_w,
                "original_h": w.original_h,
                "size": w.size_label,
                "required_w": w.required_w,
                "required_h": w.required_h,
            }
            for w in self.warnings
        ]


def _target_dims_for_orientation(photo_w: int, photo_h: int, size: PrintSize) -> tuple[int, int]:
    """Rotate the print box so the photo's orientation is preserved.

    A landscape photo on 10x15 should print at 15cm-wide × 10cm-tall, not get cropped to
    portrait.
    """
    photo_is_landscape = photo_w >= photo_h
    box_is_landscape = size.width_px >= size.height_px
    if photo_is_landscape == box_is_landscape:
        return size.width_px, size.height_px
    return size.height_px, size.width_px


def quality_report(album: Album, photos: list[Photo]) -> QualityReport:
    """Flag every (photo, size) pair where the original is smaller than the print target."""
    warnings: list[QualityWarning] = []
    seen: set[tuple[str, str]] = set()

    photos_by_id = {p.id: p for p in photos}
    for page in album.pages:
        for item in page.items:
            photo = photos_by_id.get(item.photo_id)
            if photo is None or photo.width is None or photo.height is None:
                continue
            for size in PRINT_SIZES:
                key = (str(photo.id), size.label)
                if key in seen:
                    continue
                target_w, target_h = _target_dims_for_orientation(
                    photo.width, photo.height, size
                )
                if photo.width < target_w or photo.height < target_h:
                    warnings.append(
                        QualityWarning(
                            photo_id=str(photo.id),
                            original_w=photo.width,
                            original_h=photo.height,
                            size_label=size.label,
                            required_w=target_w,
                            required_h=target_h,
                        )
                    )
                    seen.add(key)

    return QualityReport(warnings=warnings)


def _resize_for_print(src: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Cover-fit: scale to fill, then center-crop to the exact print dimensions.

    Photo orientation is preserved by the caller via _target_dims_for_orientation.
    """
    scale = max(target_w / src.width, target_h / src.height)
    new_w = max(1, int(round(src.width * scale)))
    new_h = max(1, int(round(src.height * scale)))
    resized = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _collect_unique_photo_ids(album: Album) -> list:
    seen: dict = {}
    for page in sorted(album.pages, key=lambda p: p.index):
        for item in sorted(page.items, key=lambda it: it.position_index):
            seen.setdefault(item.photo_id, None)
    return list(seen.keys())


def build_print_zip(album: Album, photos: list[Photo]) -> bytes:
    """Pack one print-quality copy of each unique photo per size into a ZIP.

    Layout:
        10x15/<photo_id>.jpg
        13x18/<photo_id>.jpg
        20x30/<photo_id>.jpg
        manifest.json
    """
    photos_by_id = {p.id: p for p in photos}
    unique_ids = _collect_unique_photo_ids(album)

    quality = quality_report(album, photos)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for photo_id in unique_ids:
            photo = photos_by_id.get(photo_id)
            if photo is None:
                continue
            src_path = Path(photo.stored_path)
            if not src_path.exists():
                log.warning("skipping missing print source %s", src_path)
                continue
            with Image.open(src_path) as raw:
                raw.load()
                src = raw.convert("RGB")
            try:
                for size in PRINT_SIZES:
                    target_w, target_h = _target_dims_for_orientation(
                        src.width, src.height, size
                    )
                    resized = _resize_for_print(src, target_w, target_h)
                    try:
                        page_buf = io.BytesIO()
                        resized.save(
                            page_buf,
                            format="JPEG",
                            quality=92,
                            dpi=(PRINT_DPI, PRINT_DPI),
                        )
                        zf.writestr(
                            f"{size.label}/{photo.id}.jpg", page_buf.getvalue()
                        )
                    finally:
                        resized.close()
            finally:
                src.close()

        manifest = {
            "album_id": str(album.id),
            "album_name": album.name,
            "dpi": PRINT_DPI,
            "sizes_cm": [
                {
                    "label": s.label,
                    "width_cm": s.width_cm,
                    "height_cm": s.height_cm,
                    "width_px": s.width_px,
                    "height_px": s.height_px,
                }
                for s in PRINT_SIZES
            ],
            "low_resolution_warnings": quality.to_jsonable(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return buf.getvalue()
