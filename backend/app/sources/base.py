from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IngestCandidate:
    """One photo discovered by a source, ready to be hashed and copied."""

    source: str
    source_ref: str
    local_path: Path


class PhotoSource(ABC):
    """A source of photos to be ingested.

    Implementations walk an underlying location (folder, cloud account, archive)
    and yield candidates. The ingest service handles hashing, dedup, and copy —
    sources do not write to the DB.
    """

    name: str

    @abstractmethod
    def iter_candidates(self) -> Iterator[IngestCandidate]:
        ...

    @abstractmethod
    def estimated_count(self) -> int | None:
        """Best-effort total for progress reporting. None if unknown."""
