"""Formats the app must be able to read.

A real test library was 53 Canon .CR3 files, 30 JPEGs and one iPhone .HEIC. Only the
JPEGs worked: RAW was silently filtered out at ingest and HEIC 500'd on the first
thumbnail request. These pin down both routes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.services.imaging import (
    SUPPORTED_SUFFIXES,
    is_supported,
    open_image,
    readable_path,
)


def test_raw_and_heic_count_as_supported() -> None:
    for suffix in (".cr3", ".CR3", ".heic", ".nef", ".dng", ".arw"):
        assert is_supported(Path(f"photo{suffix}")), suffix
    assert not is_supported(Path("notes.txt"))
    assert not is_supported(Path("movie.mov"))


def test_ingest_filter_uses_the_same_list() -> None:
    """local_folder must not keep its own narrower copy — that is what dropped the RAWs."""
    from app.sources.local_folder import IMAGE_SUFFIXES

    assert IMAGE_SUFFIXES is SUPPORTED_SUFFIXES


def test_open_image_reads_a_plain_jpeg(tmp_path: Path) -> None:
    p = tmp_path / "a.jpg"
    Image.new("RGB", (40, 30), (10, 20, 30)).save(p, "JPEG")
    with open_image(p) as img:
        assert img.size == (40, 30)


def test_readable_path_passes_native_formats_through_untouched(tmp_path: Path) -> None:
    p = tmp_path / "a.jpg"
    Image.new("RGB", (8, 8)).save(p, "JPEG")
    with readable_path(p) as readable:
        assert readable == p  # no copy, no re-encode


def test_readable_path_transcodes_heic_and_cleans_up(tmp_path: Path) -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()

    src = tmp_path / "shot.heic"
    Image.new("RGB", (64, 48), (200, 120, 60)).save(src, format="HEIF")

    with readable_path(src) as readable:
        assert readable.suffix == ".jpg"
        assert readable != src
        with Image.open(readable) as img:
            assert img.size == (64, 48)
        tmp_name = readable

    # The temporary file must not outlive the context.
    assert not tmp_name.exists()
