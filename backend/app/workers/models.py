"""Thin wrappers around DeepFace + YOLOv8.

Kept in their own module so tests can monkeypatch `face_embeddings` and
`label_objects` without dragging in TensorFlow/PyTorch.
"""

from __future__ import annotations

import logging
import os
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import certifi
import numpy as np

# macOS Python.org distros ship without a trusted root bundle; YOLO weight
# downloads fail with SSL_CERTIFICATE_VERIFY_FAILED. Point urllib/requests at
# certifi's bundle if no system CA path is already set.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
try:
    ssl._create_default_https_context = ssl.create_default_context  # type: ignore[assignment]
except Exception:  # noqa: BLE001
    pass

log = logging.getLogger(__name__)

# COCO classes we care about for the album-creator filter. Anything else is dropped.
ALLOWED_LABELS = frozenset(
    {
        "person",
        "dog",
        "cat",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "bird",
    }
)

_YOLO_LABEL_CONF_THRESHOLD = 0.35

# Facenet512 over Facenet: same davidsandberg/facenet lineage (MIT), but 512-d instead
# of 128-d. The 128-d embedding could not separate people reliably, which is what let a
# single face cluster swallow 199 faces.
#
# MTCNN over OpenCV: the DeepFace default is an OpenCV Haar cascade, which misses turned
# heads and returns sloppy boxes. A sloppy box crops badly, a bad crop embeds badly, and
# a bad embedding clusters wrong — so the detector was poisoning everything downstream.
#
# Both are MIT. ArcFace and RetinaFace would be marginally stronger but their upstream
# InsightFace weights are published for non-commercial research only, so they are
# deliberately avoided here.
_DEEPFACE_MODEL = "Facenet512"  # 512-d embeddings.
_DEEPFACE_DETECTOR = "mtcnn"
_FACE_EMBEDDING_DIM = 512

# NOTE: ultralytics is AGPL-3.0 — the only copyleft dependency in the project. It applies
# equally to yolov8n and yolov8s, so this upgrade changes nothing about the obligation.
_YOLO_WEIGHTS = "yolov8s.pt"

_yolo_model = None
_yolo_lock = threading.Lock()


def _get_yolo():
    global _yolo_model
    with _yolo_lock:
        if _yolo_model is None:
            from ultralytics import YOLO

            _yolo_model = YOLO(_YOLO_WEIGHTS)
    return _yolo_model


def face_embeddings(path: Path) -> Iterator[dict[str, Any]]:
    """Yield {'bbox': {...}, 'embedding_bytes': bytes, 'dim': int} per detected face."""
    from deepface import DeepFace

    try:
        results = DeepFace.represent(
            img_path=str(path),
            model_name=_DEEPFACE_MODEL,
            detector_backend=_DEEPFACE_DETECTOR,
            enforce_detection=False,
            align=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("DeepFace.represent failed for %s: %s", path, exc)
        return

    for face in results:
        embedding = face.get("embedding")
        if embedding is None:
            continue
        region = face.get("facial_area") or {}
        # DeepFace returns the whole image as one "face" when no face is detected;
        # skip those by requiring non-zero bbox area.
        w = region.get("w", 0) or 0
        h = region.get("h", 0) or 0
        if w <= 0 or h <= 0:
            continue
        vec = np.asarray(embedding, dtype=np.float32)
        yield {
            "bbox": {
                "x": int(region.get("x", 0) or 0),
                "y": int(region.get("y", 0) or 0),
                "w": int(w),
                "h": int(h),
            },
            "embedding_bytes": vec.tobytes(),
            "dim": int(vec.size),
        }


def label_objects(path: Path) -> Iterator[tuple[str, float]]:
    """Yield (label, confidence) for objects YOLOv8 detected, filtered to ALLOWED_LABELS."""
    model = _get_yolo()
    results = model.predict(source=str(path), verbose=False, conf=_YOLO_LABEL_CONF_THRESHOLD)
    # Keep best confidence per label.
    best: dict[str, float] = {}
    for r in results:
        names = r.names
        if r.boxes is None:
            continue
        for cls_idx, conf in zip(
            r.boxes.cls.tolist(), r.boxes.conf.tolist(), strict=True
        ):
            label = names.get(int(cls_idx))
            if not label or label not in ALLOWED_LABELS:
                continue
            if conf > best.get(label, 0.0):
                best[label] = float(conf)
    for label, conf in best.items():
        yield label, conf
