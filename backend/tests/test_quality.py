from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.workers.quality import compute_blur_score


def test_sharp_image_scores_higher_than_blurry(tmp_path: Path) -> None:
    # Sharp: high-frequency checkerboard.
    rng = np.random.default_rng(0)
    sharp_arr = (rng.integers(0, 2, size=(64, 64), endpoint=False) * 255).astype("uint8")
    sharp_arr = np.repeat(np.repeat(sharp_arr, 1, axis=0), 1, axis=1)
    sharp_path = tmp_path / "sharp.png"
    Image.fromarray(sharp_arr, mode="L").save(sharp_path, "PNG")

    # Blurry: solid gray.
    blurry_path = tmp_path / "blur.png"
    Image.new("L", (64, 64), color=128).save(blurry_path, "PNG")

    sharp_score = compute_blur_score(sharp_path)
    blur_score = compute_blur_score(blurry_path)

    assert sharp_score > blur_score
    assert blur_score < 1.0  # solid gray = ~0 Laplacian variance
