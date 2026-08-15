from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.sources.base import IngestCandidate, PhotoSource

# Single source of truth — RAW (.CR3 etc.) was missing, so a Canon library ingested
# zero files while appearing to succeed.
from app.services.imaging import SUPPORTED_SUFFIXES as IMAGE_SUFFIXES  # noqa: E402


class LocalFolderSource(PhotoSource):
    """Walks a directory tree on the local filesystem for image files."""

    name = "local_folder"

    def __init__(self, root: Path) -> None:
        root = root.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Folder does not exist: {root}")
        self.root = root

    def iter_candidates(self) -> Iterator[IngestCandidate]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            yield IngestCandidate(
                source=self.name,
                source_ref=str(path.relative_to(self.root)),
                local_path=path,
            )

    def estimated_count(self) -> int | None:
        return sum(
            1
            for p in self.root.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )
