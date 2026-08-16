"""Face detections are filtered and scored before they ever reach a cluster.

MTCNN happily reports 0.98-1.0 confidence on flat patches of background, and those
tiny bogus detections were clustering together into "people" that do not exist. Size
is the honest signal, and sharpness/eye-separation decide which real face is worth
showing as a portrait.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.services.face_thumbs import face_display_rank
from app.workers import models as models_module


def _fake_represent(faces: list[dict]):
    """Stand in for DeepFace.represent, which we never want to load in a unit test."""

    def represent(**_kwargs):
        return faces

    return represent


def _install_stub(monkeypatch, tmp_path: Path, faces: list[dict]) -> Path:
    img = tmp_path / "frame.jpg"
    Image.new("RGB", (800, 600), (120, 120, 120)).save(img, "JPEG")

    from deepface import DeepFace

    monkeypatch.setattr(DeepFace, "represent", _fake_represent(faces))
    return img


def _face(x: int, y: int, w: int, h: int, eyes: bool = True) -> dict:
    area = {"x": x, "y": y, "w": w, "h": h}
    if eyes:
        area["left_eye"] = [x + int(w * 0.7), y + int(h * 0.4)]
        area["right_eye"] = [x + int(w * 0.3), y + int(h * 0.4)]
    return {"embedding": [0.1] * 8, "facial_area": area, "face_confidence": 0.99}


def test_tiny_detections_are_dropped(monkeypatch, tmp_path: Path) -> None:
    """A 20px "face" carries no identity — keeping it invents people out of noise."""
    img = _install_stub(
        monkeypatch, tmp_path, [_face(10, 10, 20, 20), _face(100, 100, 120, 120)]
    )

    out = list(models_module.face_embeddings(img))

    assert len(out) == 1
    assert out[0]["bbox"]["w"] == 120


def test_high_confidence_does_not_rescue_a_tiny_detection(
    monkeypatch, tmp_path: Path
) -> None:
    """The junk clusters were all 0.98+ confidence, so confidence cannot be the gate."""
    img = _install_stub(monkeypatch, tmp_path, [_face(5, 5, 18, 18)])
    # Explicitly the strongest possible detection.
    img_faces = list(models_module.face_embeddings(img))

    assert img_faces == []


def test_quality_scores_are_measured_and_stored(monkeypatch, tmp_path: Path) -> None:
    """Every surviving face carries the two numbers the portrait ranking needs."""
    img = _install_stub(monkeypatch, tmp_path, [_face(100, 100, 150, 150)])

    out = list(models_module.face_embeddings(img))

    assert len(out) == 1
    assert out[0]["sharpness"] is not None
    # Eyes were placed 40% of the width apart.
    assert out[0]["frontality"] == pytest.approx(0.4, abs=0.02)


def test_missing_eye_landmarks_leave_frontality_unknown(
    monkeypatch, tmp_path: Path
) -> None:
    """Unmeasurable is not the same as bad; it must stay None rather than score zero."""
    img = _install_stub(monkeypatch, tmp_path, [_face(100, 100, 150, 150, eyes=False)])

    out = list(models_module.face_embeddings(img))

    assert out[0]["frontality"] is None


def test_bbox_scale_is_applied_after_quality_is_measured(
    monkeypatch, tmp_path: Path
) -> None:
    """Boxes are stored against the original file, but scores describe analysed pixels."""
    img = _install_stub(monkeypatch, tmp_path, [_face(100, 100, 150, 150)])

    out = list(models_module.face_embeddings(img, scale=3.0))

    assert out[0]["bbox"] == {"x": 300, "y": 300, "w": 450, "h": 450}
    assert out[0]["frontality"] == pytest.approx(0.4, abs=0.02)


def test_clear_frontal_face_outranks_blurry_and_profile() -> None:
    """The ranking is tiered, so no amount of size promotes a bad face over a good one."""
    bbox_small = {"x": 100, "y": 100, "w": 60, "h": 60}
    bbox_huge = {"x": 100, "y": 100, "w": 400, "h": 400}

    clear = face_display_rank(bbox_small, 250.0, 0.44, 2000, 2000)
    blurry = face_display_rank(bbox_huge, 8.0, 0.44, 2000, 2000)
    profile = face_display_rank(bbox_huge, 250.0, 0.22, 2000, 2000)

    assert clear > blurry
    assert clear > profile


def test_face_touching_the_frame_edge_is_demoted() -> None:
    """A crop clamped by the frame is the half-a-head thumbnail we are avoiding."""
    inside = face_display_rank({"x": 500, "y": 500, "w": 100, "h": 100}, 250.0, 0.44, 2000, 2000)
    at_edge = face_display_rank({"x": 0, "y": 500, "w": 100, "h": 100}, 250.0, 0.44, 2000, 2000)

    assert inside > at_edge


def test_unmeasured_faces_fall_back_to_size() -> None:
    """Pre-existing rows have no scores; they must still be rankable, by size."""
    small = face_display_rank({"x": 10, "y": 10, "w": 50, "h": 50}, None, None, 2000, 2000)
    large = face_display_rank({"x": 10, "y": 10, "w": 200, "h": 200}, None, None, 2000, 2000)

    assert large > small
    # Neither can claim to be a verified-clean portrait.
    assert small[0] == large[0] == 0


def test_unknown_photo_size_does_not_penalise_a_face() -> None:
    """Photos with no recorded dimensions must not have every face marked as cropped."""
    known = face_display_rank({"x": 500, "y": 500, "w": 100, "h": 100}, 250.0, 0.44, 2000, 2000)
    unknown = face_display_rank({"x": 500, "y": 500, "w": 100, "h": 100}, 250.0, 0.44, None, None)

    assert known == unknown


def _face_like(size: int) -> np.ndarray:
    """The same synthetic 'face' rendered at a given pixel size.

    Scale invariance is about one subject photographed near and far, so the content has
    to stay fixed while only the resolution changes — a bigger window onto a repeating
    texture is a different question entirely.
    """
    import cv2

    canvas = np.full((size, size), 110, dtype=np.uint8)
    r = size // 12
    cv2.circle(canvas, (size // 3, size // 3), r, 30, -1)  # eyes
    cv2.circle(canvas, (2 * size // 3, size // 3), r, 30, -1)
    cv2.ellipse(
        canvas, (size // 2, 2 * size // 3), (size // 4, size // 8), 0, 0, 180, 60, -1
    )  # mouth
    return canvas


def test_sharpness_does_not_simply_track_face_size() -> None:
    """Scores are compared across faces of different sizes, so they must be comparable.

    Measuring the Laplacian on the raw crop would make a bigger face score higher purely
    for containing more pixels; the fixed 112x112 resize is what prevents that.
    """
    small = models_module._face_quality(
        _face_like(100), {"x": 0, "y": 0, "w": 100, "h": 100}
    )[0]
    large = models_module._face_quality(
        _face_like(400), {"x": 0, "y": 0, "w": 400, "h": 400}
    )[0]

    assert small is not None and large is not None
    # Same subject, four times the pixels: the readings must stay comparable.
    assert 0.5 < large / small < 2.0


def test_blur_scores_far_below_detail_at_the_same_size() -> None:
    """The score has to actually separate a sharp face from a soft one."""
    import cv2

    gray = np.zeros((400, 400), dtype=np.uint8)
    cell = 16
    for row in range(0, 400, cell):
        for col in range(0, 400, cell):
            if (row // cell + col // cell) % 2 == 0:
                gray[row : row + cell, col : col + cell] = 255
    blurred = cv2.GaussianBlur(gray, (31, 31), 0)

    box = {"x": 50, "y": 50, "w": 200, "h": 200}
    sharp_score = models_module._face_quality(gray, box)[0]
    blurred_score = models_module._face_quality(blurred, box)[0]

    assert sharp_score is not None and blurred_score is not None
    assert blurred_score < sharp_score / 10
