from __future__ import annotations

from pathlib import Path

import cv2


def compute_blur_score(path: Path) -> float:
    """Laplacian variance — lower = blurrier. Spec calls this `blur_score`.

    Returns the value as-is; the filter UI maps thresholds to user-friendly buckets.
    """
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cv2 could not read {path}")
    return float(cv2.Laplacian(img, cv2.CV_64F).var())
