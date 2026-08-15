"""Cropped face thumbnails for the people filter.

The filter used to label each person cluster with a truncated UUID ("#a1b2"), which is
unusable for picking a person out of a list. FaceCluster already stored a representative
photo and FaceEmbedding already stored a bounding box; this turns the two into a picture.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import uuid
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.services.imaging import open_image

log = logging.getLogger(__name__)

_FACE_THUMB_PX = 160
_FACE_QUALITY = 82
# Faces cropped tight to the detector box look like mugshots; a margin of 40% of the box
# on each side reads as a portrait.
_FACE_PAD_RATIO = 0.4

_locks: dict[uuid.UUID, threading.Lock] = {}
_locks_guard = threading.Lock()


def _face_dir() -> Path:
    return get_settings().photo_storage_dir.resolve() / "_faces"


def _crop_key(photo_id: uuid.UUID, bbox: dict) -> str:
    """Short digest of the exact crop, so the cache invalidates when the chosen face changes."""
    raw = f"{photo_id}:{bbox.get('x')}:{bbox.get('y')}:{bbox.get('w')}:{bbox.get('h')}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def face_thumb_path_for(cluster_id: uuid.UUID, key: str) -> Path:
    return _face_dir() / f"{cluster_id}_{key}.webp"


def _lock_for(cluster_id: uuid.UUID) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(cluster_id)
        if lock is None:
            lock = threading.Lock()
            _locks[cluster_id] = lock
        return lock


def _padded_box(bbox: dict, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    x = int(bbox.get("x", 0) or 0)
    y = int(bbox.get("y", 0) or 0)
    w = int(bbox.get("w", 0) or 0)
    h = int(bbox.get("h", 0) or 0)
    pad_x = int(w * _FACE_PAD_RATIO)
    pad_y = int(h * _FACE_PAD_RATIO)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(img_w, x + w + pad_x)
    bottom = min(img_h, y + h + pad_y)
    if right <= left or bottom <= top:
        raise ValueError("degenerate face box")
    return left, top, right, bottom


def get_or_create_face_thumb(
    cluster_id: uuid.UUID, photo_id: uuid.UUID, source_path: Path, bbox: dict
) -> Path:
    """Return a path to a square-ish cropped face thumbnail, generating + caching on miss.

    Coordinates are used exactly as the detector recorded them — no EXIF transpose — so
    the crop matches the frame the bounding box was measured against.
    """
    target = face_thumb_path_for(cluster_id, _crop_key(photo_id, bbox))
    if target.exists() and target.stat().st_size > 0:
        return target

    with _lock_for(cluster_id):
        if target.exists() and target.stat().st_size > 0:
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
        try:
            with open_image(source_path) as img:
                img.load()
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                box = _padded_box(bbox, img.width, img.height)
                face = img.crop(box)
                face.thumbnail(
                    (_FACE_THUMB_PX, _FACE_THUMB_PX), Image.Resampling.LANCZOS
                )
                face.save(tmp, format="WEBP", quality=_FACE_QUALITY, method=4)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return target
