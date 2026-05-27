from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import layout as layout_agent_module
from app.db import SessionLocal
from app.main import app
from app.models import Album, AlbumItem, AlbumPage, AlbumStyle, Photo
from app.schemas.layouts import LayoutPlan
from app.services.layout import deterministic_layout, suggest_layout

client = TestClient(app)


def _seed_photo() -> uuid.UUID:
    db = SessionLocal()
    try:
        photo = Photo(
            source="local_folder",
            source_ref=f"p_{uuid.uuid4().hex[:6]}.jpg",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            original_path="/tmp/p.jpg",
            stored_path="/tmp/p.jpg",
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return photo.id
    finally:
        db.close()


# ---------- Deterministic layout ----------


def test_deterministic_simple_2x2() -> None:
    pids = [_seed_photo() for _ in range(4)]
    plan = deterministic_layout(pids, page_count=1)
    assert len(plan.pages) == 1
    page = plan.pages[0]
    assert page.grid.rows == 2 and page.grid.cols == 2
    assert len(page.items) == 4
    # Positions are inside the unit square and non-overlapping enough.
    for item in page.items:
        assert 0.0 <= item.position.x < 1.0
        assert 0.0 <= item.position.y < 1.0
        assert item.position.w > 0
        assert item.position.h > 0


def test_deterministic_splits_across_pages() -> None:
    pids = [_seed_photo() for _ in range(6)]
    plan = deterministic_layout(pids, page_count=2)
    assert len(plan.pages) == 2
    total = sum(len(p.items) for p in plan.pages)
    assert total == 6


def test_deterministic_page_count_capped_to_photo_count() -> None:
    pids = [_seed_photo() for _ in range(2)]
    plan = deterministic_layout(pids, page_count=10)
    assert len(plan.pages) == 2  # one photo each


def test_deterministic_empty() -> None:
    assert deterministic_layout([], page_count=3).pages == []
    assert deterministic_layout([_seed_photo()], page_count=0).pages == []


# ---------- suggest_layout (orchestrator + DB writes) ----------


def test_suggest_layout_fallback_persists_album(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.layout.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-REPLACE_ME", anthropic_model="x"),
    )
    pids = [_seed_photo() for _ in range(4)]
    db = SessionLocal()
    try:
        result = suggest_layout(
            db, pids, page_count=2, style=AlbumStyle.MODERN, name="Test"
        )
    finally:
        db.close()

    assert result.used_fallback is True
    assert result.model is None
    assert result.album.page_count == 2
    assert result.album.name == "Test"

    db = SessionLocal()
    try:
        pages = list(
            db.scalars(
                select(AlbumPage).where(AlbumPage.album_id == result.album.id).order_by(
                    AlbumPage.index
                )
            )
        )
        assert len(pages) == 2
        items = list(db.scalars(select(AlbumItem).where(AlbumItem.page_id.in_([p.id for p in pages]))))
        assert len(items) == 4
        assert all(0 <= i.position["x"] <= 1 for i in items)
    finally:
        db.close()


def test_suggest_layout_claude_happy_path(monkeypatch) -> None:
    pid = _seed_photo()

    fake_input = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 1, "gap": 0.02},
                "items": [
                    {
                        "photo_id": str(pid),
                        "position": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9},
                        "comment": "summer day",
                        "comment_position": "below",
                    }
                ],
            }
        ]
    }
    fake_tool = MagicMock(type="tool_use", input=fake_input)
    fake_message = MagicMock(content=[fake_tool])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message
    monkeypatch.setattr(layout_agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_layout(
            db, [pid], page_count=1, style=AlbumStyle.MODERN, anthropic_model="claude-x"
        )
    finally:
        db.close()

    assert result.used_fallback is False
    assert result.model == "claude-x"
    assert result.album.page_count == 1
    db = SessionLocal()
    try:
        items = list(db.scalars(select(AlbumItem)))
        assert len(items) == 1
        assert items[0].comment == "summer day"
        assert items[0].comment_position.value == "below"
    finally:
        db.close()


def test_suggest_layout_bogus_photo_id_falls_back(monkeypatch) -> None:
    pid = _seed_photo()
    fake_input = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 1, "gap": 0.02},
                "items": [
                    {
                        "photo_id": str(uuid.uuid4()),
                        "position": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                    }
                ],
            }
        ]
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="tool_use", input=fake_input)]
    )
    monkeypatch.setattr(layout_agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_layout(db, [pid], page_count=1, style=AlbumStyle.MODERN)
    finally:
        db.close()

    assert result.used_fallback is True


def test_suggest_layout_page_count_mismatch_falls_back(monkeypatch) -> None:
    pid = _seed_photo()
    # Agent returns 1 page when we asked for 2.
    fake_input = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 1, "gap": 0.02},
                "items": [
                    {
                        "photo_id": str(pid),
                        "position": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                    }
                ],
            }
        ]
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="tool_use", input=fake_input)]
    )
    monkeypatch.setattr(layout_agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_layout(db, [pid], page_count=2, style=AlbumStyle.MODERN)
    finally:
        db.close()

    assert result.used_fallback is True


def test_layout_plan_schema_rejects_oversized_grid() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LayoutPlan.model_validate(
            {
                "pages": [
                    {
                        "grid": {"rows": 10, "cols": 1, "gap": 0.02},
                        "items": [],
                    }
                ]
            }
        )


# ---------- API ----------


def test_suggest_endpoint_writes_album(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.layout.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-REPLACE_ME", anthropic_model="x"),
    )
    pids = [str(_seed_photo()) for _ in range(3)]

    r = client.post(
        "/api/layouts/suggest",
        json={"photo_ids": pids, "page_count": 1, "style": "modern", "name": "Hello"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["used_fallback"] is True
    assert len(body["layout"]["pages"]) == 1
    assert len(body["layout"]["pages"][0]["items"]) == 3

    album_id = body["album_id"]
    list_r = client.get("/api/albums")
    assert list_r.status_code == 200
    assert any(a["id"] == album_id for a in list_r.json())

    get_r = client.get(f"/api/albums/{album_id}")
    assert get_r.status_code == 200
    album = get_r.json()
    assert album["page_count"] == 1
    assert len(album["pages"]) == 1
    assert len(album["pages"][0]["items"]) == 3


def test_get_album_404() -> None:
    r = client.get(f"/api/albums/{uuid.uuid4()}")
    assert r.status_code == 404


def test_suggest_endpoint_validates_inputs() -> None:
    r = client.post(
        "/api/layouts/suggest",
        json={"photo_ids": [], "page_count": 1, "style": "modern"},
    )
    assert r.status_code == 422  # photo_ids must be non-empty
