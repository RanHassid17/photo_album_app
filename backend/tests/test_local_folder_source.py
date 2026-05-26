from __future__ import annotations

from pathlib import Path

import pytest

from app.sources.local_folder import LocalFolderSource


def test_walks_images_and_ignores_non_images(tmp_path: Path, make_image) -> None:
    make_image("a.jpg")
    make_image("nested/b.png")
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / "weird.dat").write_bytes(b"\x00\x01")

    source = LocalFolderSource(tmp_path)
    candidates = list(source.iter_candidates())

    refs = sorted(c.source_ref for c in candidates)
    assert refs == ["a.jpg", "nested/b.png"]
    assert all(c.source == "local_folder" for c in candidates)
    assert source.estimated_count() == 2


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        LocalFolderSource(tmp_path / "does-not-exist")
