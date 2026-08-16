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

from app.services.imaging import readable_path

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
# Defaults, overridable per machine via .env — this project's reference machine is a
# 2020 Intel MacBook with no GPU (no CUDA, and MPS needs Apple Silicon), so everything
# runs on four CPU cores. Accuracy and indexing time trade directly against each other
# and the right point depends on the hardware, so it is configuration, not a constant.
_DEFAULT_FACE_MODEL = "Facenet512"  # 512-d embeddings.
_DEFAULT_FACE_DETECTOR = "mtcnn"


def _vision_settings() -> tuple[str, str, str]:
    from app.config import get_settings

    s = get_settings()
    return (
        getattr(s, "vision_face_model", _DEFAULT_FACE_MODEL),
        getattr(s, "vision_face_detector", _DEFAULT_FACE_DETECTOR),
        getattr(s, "vision_yolo_weights", "yolov8s.pt"),
    )

# NOTE: ultralytics is AGPL-3.0 — the only copyleft dependency in the project. The
# obligation is identical for every weight file, so the tier is purely a speed choice.

_yolo_model = None
_yolo_lock = threading.Lock()


def _get_yolo():
    global _yolo_model
    with _yolo_lock:
        if _yolo_model is None:
            from ultralytics import YOLO

            _yolo_model = YOLO(_vision_settings()[2])
    return _yolo_model


# A face this small on the analysis copy (longest edge 2000px) is a background
# bystander: too few pixels for Facenet512 to embed meaningfully, so it clusters on
# noise and invents people who do not exist. Measured on this library, the junk
# clusters were built entirely from detections under ~35px.
_MIN_FACE_PX = 32


def _face_quality(gray: "np.ndarray", region: dict) -> tuple[float | None, float | None]:
    """Return (sharpness, frontality) for one detected face.

    sharpness  variance of the Laplacian over the face crop, resized to a fixed
               112x112 so the number means the same thing for a big face and a small
               one. Crisp faces score in the hundreds, out-of-focus ones under ~20.
    frontality distance between the eyes as a fraction of face width. A head turned to
               the side foreshortens that gap: measured on this library, profiles land
               under 0.33 and faces looking at the camera at 0.40+.

    Either can be None when the detector gave us nothing to measure -- an unknown score
    must not be confused with a bad one.
    """
    import cv2

    x, y, w, h = (int(region.get(k, 0) or 0) for k in ("x", "y", "w", "h"))
    crop = gray[max(0, y) : y + h, max(0, x) : x + w]
    sharpness = None
    if crop.size:
        resized = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
        sharpness = float(cv2.Laplacian(resized, cv2.CV_64F).var())

    left, right = region.get("left_eye"), region.get("right_eye")
    frontality = None
    if left and right and w > 0:
        frontality = float(np.hypot(left[0] - right[0], left[1] - right[1])) / w

    return sharpness, frontality


def face_embeddings(path: Path, scale: float = 1.0) -> Iterator[dict[str, Any]]:
    """Yield one dict per detected face: bbox, embedding, and quality scores.

    `scale` maps detector coordinates back to the original frame when detection ran on
    a downscaled copy, so stored boxes stay valid against the full-resolution file. The
    quality scores are deliberately measured before that rescale, on the pixels the
    detector actually saw.
    """
    import cv2
    from deepface import DeepFace

    model_name, detector, _ = _vision_settings()
    try:
        # HEIC and RAW are transcoded to a temporary JPEG first: DeepFace opens the path
        # itself and understands neither.
        with readable_path(path) as readable:
            results = DeepFace.represent(
                img_path=str(readable),
                model_name=model_name,
                detector_backend=detector,
                enforce_detection=False,
                align=True,
            )
            gray = cv2.imread(str(readable), cv2.IMREAD_GRAYSCALE)
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
        # Detector confidence is no help here: MTCNN reports 0.98-1.0 even for the
        # flat patches of background it hallucinates faces in. Size is the honest signal.
        if min(w, h) < _MIN_FACE_PX:
            continue
        sharpness, frontality = (
            _face_quality(gray, region) if gray is not None else (None, None)
        )
        vec = np.asarray(embedding, dtype=np.float32)
        yield {
            "bbox": {
                "x": int(round(int(region.get("x", 0) or 0) * scale)),
                "y": int(round(int(region.get("y", 0) or 0) * scale)),
                "w": int(round(w * scale)),
                "h": int(round(h * scale)),
            },
            "embedding_bytes": vec.tobytes(),
            "dim": int(vec.size),
            "sharpness": sharpness,
            "frontality": frontality,
        }


def label_objects(path: Path) -> Iterator[tuple[str, float]]:
    """Yield (label, confidence) for objects YOLOv8 detected, filtered to ALLOWED_LABELS."""
    model = _get_yolo()
    with readable_path(path) as readable:
        results = model.predict(
            source=str(readable), verbose=False, conf=_YOLO_LABEL_CONF_THRESHOLD
        )
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
