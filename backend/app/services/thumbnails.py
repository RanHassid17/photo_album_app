from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from app.config import get_settings

log = logging.getLogger(__name__)

_THUMB_MAX_EDGE = 512
_THUMB_QUALITY = 80
_locks: dict[uuid.UUID, threading.Lock] = {}
_locks_guard = threading.Lock()


def _thumb_dir() -> Path:
    return get_settings().photo_storage_dir.resolve() / "_thumbs"


def thumbnail_path_for(photo_id: uuid.UUID) -> Path:
    return _thumb_dir() / f"{photo_id}.webp"


def _lock_for(photo_id: uuid.UUID) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(photo_id)
        if lock is None:
            lock = threading.Lock()
            _locks[photo_id] = lock
        return lock


def get_or_create_thumbnail(photo_id: uuid.UUID, source_path: Path) -> Path:
    """Return a path to a 512px WebP thumbnail of `source_path`, generating + caching on miss.

    Per-photo lock prevents two concurrent requests from both writing the file.
    """
    target = thumbnail_path_for(photo_id)
    if target.exists() and target.stat().st_size > 0:
        return target

    with _lock_for(photo_id):
        # Re-check after acquiring lock.
        if target.exists() and target.stat().st_size > 0:
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
        try:
            with Image.open(source_path) as img:
                img = ImageOps.exif_transpose(img)  # respect EXIF orientation
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.thumbnail((_THUMB_MAX_EDGE, _THUMB_MAX_EDGE), Image.Resampling.LANCZOS)
                img.save(tmp, format="WEBP", quality=_THUMB_QUALITY, method=4)
            os.replace(tmp, target)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
    return target
