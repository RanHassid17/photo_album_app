from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Force the app to use a dedicated test database BEFORE any app modules import config.
TEST_DB_URL = os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://album:album@localhost:5432/album_test"
)


def _ensure_test_database() -> None:
    """Create the test database if it doesn't already exist."""
    admin_url = "postgresql+psycopg://album:album@localhost:5432/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'album_test'")
        ).scalar()
        if not exists:
            conn.execute(text("CREATE DATABASE album_test OWNER album"))
    engine.dispose()


_ensure_test_database()

# Now safe to import the app (uses the env var we set above).
from app import models  # noqa: E402, F401  -- register models on Base.metadata
from app.db import Base, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    # Leave tables in place for inspection between runs.


@pytest.fixture(autouse=True)
def _truncate_between_tests() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE photos, jobs RESTART IDENTITY CASCADE"))


@pytest.fixture
def tmp_storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PHOTO_STORAGE_DIR at a tmp dir for each test."""
    from app.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]
    monkeypatch.setenv("PHOTO_STORAGE_DIR", str(tmp_path / "storage"))
    settings = get_settings()
    return settings.photo_storage_dir


@pytest.fixture
def make_image(tmp_path: Path):
    """Factory that drops a tiny but real JPEG/PNG into a directory."""
    from PIL import Image

    def _make(rel_path: str, *, color: tuple[int, int, int] = (200, 100, 50), size=(8, 8)) -> Path:
        target = tmp_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", size, color=color)
        fmt = "PNG" if target.suffix.lower() == ".png" else "JPEG"
        img.save(target, fmt)
        return target

    return _make
