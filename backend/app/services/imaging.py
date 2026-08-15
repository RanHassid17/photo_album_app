"""One place that knows how to open a photo, whatever the camera produced.

Pillow reads JPEG and PNG. It does not read HEIC (every modern iPhone) or camera RAW
(a Canon library is entirely .CR3). Those files ingested fine — the copy succeeds —
and then every thumbnail, every export and every indexing pass failed on them.

`open_image` decodes any supported format into a Pillow image. `readable_path` exists
for the vision models: DeepFace and YOLO take a *path* and open the file themselves, so
non-native formats have to be transcoded to a temporary JPEG first.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# Formats Pillow handles unaided.
NATIVE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
)
HEIF_SUFFIXES = frozenset({".heic", ".heif", ".hif"})
# Camera RAW. LibRaw (via rawpy) covers all of these; CR3 needs LibRaw >= 0.20.
RAW_SUFFIXES = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".srw", ".pef"}
)

SUPPORTED_SUFFIXES = NATIVE_SUFFIXES | HEIF_SUFFIXES | RAW_SUFFIXES

_heif_registered = False


def _register_heif() -> bool:
    """Teach Pillow about HEIC. Idempotent, and tolerant of the package being absent."""
    global _heif_registered
    if _heif_registered:
        return True
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True
    except ImportError:
        log.warning("pillow-heif not installed — HEIC/HEIF photos cannot be read")
    return _heif_registered


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def _open_raw(path: Path) -> Image.Image:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        # Camera white balance rather than the daylight default: these are personal
        # photos, and the point is to match what the camera intended.
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
    return Image.fromarray(rgb)


def open_image(path: Path | str) -> Image.Image:
    """Open any supported photo as an RGB-ish Pillow image.

    Raises the underlying decoder's error if the file is corrupt or unsupported, so
    callers can keep treating "cannot read this" as an exception.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in RAW_SUFFIXES:
        return _open_raw(path)

    if suffix in HEIF_SUFFIXES:
        _register_heif()

    img = Image.open(path)
    img.load()
    return img


@contextmanager
def readable_path(path: Path | str) -> Iterator[Path]:
    """Yield a path the vision models can open directly.

    DeepFace and YOLO read files themselves and understand neither HEIC nor RAW, so for
    those formats this transcodes to a temporary JPEG and cleans up afterwards. Native
    formats are passed straight through — no copy, no quality loss.
    """
    path = Path(path)
    if path.suffix.lower() in NATIVE_SUFFIXES:
        yield path
        return

    tmp = Path(
        tempfile.mkstemp(suffix=".jpg", prefix=f"{path.stem}_")[1]
    )
    try:
        img = open_image(path)
        try:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            # Quality 95: this is what the detector and the embedder see, so it should
            # not be the weak link.
            img.save(tmp, format="JPEG", quality=95)
        finally:
            img.close()
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)
