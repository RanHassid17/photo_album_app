from __future__ import annotations

import io
import json
import logging
import zipfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.models import Album, Photo
from app.services.imaging import open_image

log = logging.getLogger(__name__)

PRINT_DPI = 300
_CM_PER_INCH = 2.54
# Prompt spec §14 Agent 5 calls for JPEG quality 95%+; this was 92.
_JPEG_QUALITY = 95


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

    @property
    def area_cm2(self) -> float:
        return self.width_cm * self.height_cm


# Ordered smallest to largest — `recommended_size` relies on the ordering.
# 15x21 and 30x40 were specified in §14 Agent 5 but missing from the implementation.
PRINT_SIZES: tuple[PrintSize, ...] = (
    PrintSize(label="10x15", width_cm=10.0, height_cm=15.0),
    PrintSize(label="13x18", width_cm=13.0, height_cm=18.0),
    PrintSize(label="15x21", width_cm=15.0, height_cm=21.0),
    PrintSize(label="20x30", width_cm=20.0, height_cm=30.0),
    PrintSize(label="30x40", width_cm=30.0, height_cm=40.0),
)


@dataclass(slots=True)
class QualityWarning:
    photo_id: str
    original_w: int | None
    original_h: int | None
    size_label: str
    required_w: int
    required_h: int


# How much of a page a photo covers -> the print size that matches its role in the album.
# Recommending "the largest size the pixels allow" returned 30x40 for every photo in a
# modern camera library, which is not a recommendation. What the album designer gave a
# photo half a page for deserves a bigger print than something in a corner cell.
_AREA_TIERS: tuple[tuple[float, str], ...] = (
    (0.45, "30x40"),
    (0.30, "20x30"),
    (0.18, "15x21"),
    (0.10, "13x18"),
    (0.0, "10x15"),
)


@dataclass(slots=True)
class SizeAdvice:
    photo_id: str
    # What we actually suggest printing: the layout's ambition, capped by the pixels.
    recommended_size: str | None
    # What the photo's prominence in the album alone would call for.
    layout_size: str
    # Largest size the original fills at a true 300 DPI (None = too small even for 10x15).
    max_by_resolution: str | None

    @property
    def limited_by_resolution(self) -> bool:
        return self.recommended_size != self.layout_size


@dataclass(slots=True)
class QualityReport:
    warnings: list[QualityWarning]
    advice: list[SizeAdvice] = field(default_factory=list)

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

    def recommendations_jsonable(self) -> list[dict]:
        return [
            {
                "photo_id": a.photo_id,
                "recommended_size": a.recommended_size,
                "layout_size": a.layout_size,
                "max_by_resolution": a.max_by_resolution,
                "limited_by_resolution": a.limited_by_resolution,
            }
            for a in sorted(self.advice, key=lambda a: a.photo_id)
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


def _size_index(label: str) -> int:
    for i, size in enumerate(PRINT_SIZES):
        if size.label == label:
            return i
    return 0


def size_for_page_area(area_fraction: float) -> str:
    """Print size implied by how much of its page a photo occupies."""
    for threshold, label in _AREA_TIERS:
        if area_fraction >= threshold:
            return label
    return PRINT_SIZES[0].label


def max_size_for_resolution(photo_w: int, photo_h: int) -> str | None:
    """Largest print size this photo can fill at a true 300 DPI without upscaling."""
    best: str | None = None
    for size in PRINT_SIZES:
        target_w, target_h = _target_dims_for_orientation(photo_w, photo_h, size)
        if photo_w >= target_w and photo_h >= target_h:
            best = size.label
    return best


def quality_report(album: Album, photos: list[Photo]) -> QualityReport:
    """Flag every (photo, size) pair where the original is smaller than the print target."""
    warnings: list[QualityWarning] = []
    advice: list[SizeAdvice] = []
    seen: set[tuple[str, str]] = set()

    photos_by_id = {p.id: p for p in photos}
    areas = {pid: area for pid, _, _, area in _collect_placements(album)}
    advised: set[uuid.UUID] = set()

    for page in album.pages:
        for item in page.items:
            photo = photos_by_id.get(item.photo_id)
            if photo is None or photo.width is None or photo.height is None:
                continue
            if photo.id not in advised:
                advised.add(photo.id)
                layout_size = size_for_page_area(areas.get(photo.id, 0.0))
                max_res = max_size_for_resolution(photo.width, photo.height)
                recommended = (
                    None
                    if max_res is None
                    else PRINT_SIZES[
                        min(_size_index(layout_size), _size_index(max_res))
                    ].label
                )
                advice.append(
                    SizeAdvice(
                        photo_id=str(photo.id),
                        recommended_size=recommended,
                        layout_size=layout_size,
                        max_by_resolution=max_res,
                    )
                )
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

    return QualityReport(warnings=warnings, advice=advice)


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


def _safe_component(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name.strip())
    return cleaned or fallback


def _collect_placements(album: Album) -> list[tuple]:
    """First (photo_id, page_index, position_index, page_area) per unique photo."""
    seen: dict = {}
    for page in sorted(album.pages, key=lambda p: p.index):
        for item in sorted(page.items, key=lambda it: it.position_index):
            if item.photo_id in seen:
                continue
            pos = item.position or {}
            area = float(pos.get("w") or 0.0) * float(pos.get("h") or 0.0)
            seen[item.photo_id] = (page.index, item.position_index, area)
    return [(pid, pg, ix, area) for pid, (pg, ix, area) in seen.items()]


def build_print_zip(album: Album, photos: list[Photo]) -> bytes:
    """Pack one print-quality copy of each unique photo per size into a ZIP.

    Layout follows prompt spec §14 Agent 5:
        <album>/10x15/<album>_p1_1.jpg
        <album>/13x18/<album>_p1_1.jpg
        ...
        <album>/recommended/20x30/<album>_p1_1.jpg   <- one per photo, by size
        manifest.json

    Filenames previously carried only a bare photo UUID, so a downloaded folder gave no
    indication of which album a print belonged to or what order the pages ran in.
    """
    photos_by_id = {p.id: p for p in photos}
    placements = _collect_placements(album)
    album_slug = _safe_component(album.name, f"album-{album.id}")

    quality = quality_report(album, photos)
    advice_by_photo = {a.photo_id: a for a in quality.advice}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for photo_id, page_index, position_index, _area in placements:
            photo = photos_by_id.get(photo_id)
            if photo is None:
                continue
            src_path = Path(photo.stored_path)
            if not src_path.exists():
                log.warning("skipping missing print source %s", src_path)
                continue
            with open_image(src_path) as raw:
                raw.load()
                src = raw.convert("RGB")
            try:
                stem = f"{album_slug}_p{page_index + 1}_{position_index + 1}"
                advice = advice_by_photo.get(str(photo.id))
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
                            quality=_JPEG_QUALITY,
                            dpi=(PRINT_DPI, PRINT_DPI),
                        )
                        data = page_buf.getvalue()
                        zf.writestr(f"{album_slug}/{size.label}/{stem}.jpg", data)
                        # Every photo at every size answers "give me all the options".
                        # `recommended/` answers "tell me what to print" — one file per
                        # photo, at the size the album's own design calls for.
                        if advice is not None and advice.recommended_size == size.label:
                            zf.writestr(
                                f"{album_slug}/recommended/{size.label}/{stem}.jpg", data
                            )
                    finally:
                        resized.close()
            finally:
                src.close()

        manifest = {
            "album_id": str(album.id),
            "album_name": album.name,
            "dpi": PRINT_DPI,
            "jpeg_quality": _JPEG_QUALITY,
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
            "recommended_sizes": quality.recommendations_jsonable(),
            "low_resolution_warnings": quality.to_jsonable(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    return buf.getvalue()
