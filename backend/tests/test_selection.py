from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from app.agents import selection as agent_module
from app.agents.selection import SelectionAgentError
from app.db import SessionLocal
from app.main import app
from app.models import Photo
from app.services.selection import (
    build_photo_metadata,
    deterministic_ranker,
    suggest_selection,
)

client = TestClient(app)


def _seed_photo(
    name: str,
    *,
    blur: float | None,
    taken_at: datetime | None,
) -> uuid.UUID:
    db = SessionLocal()
    try:
        # Just need a row; we don't open any image bytes here.
        photo = Photo(
            source="local_folder",
            source_ref=name,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            original_path=f"/tmp/{name}",
            stored_path=f"/tmp/{name}",
            blur_score=blur,
            taken_at=taken_at,
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return photo.id
    finally:
        db.close()


# ---------- Deterministic ranker ----------

def test_deterministic_prefers_sharper() -> None:
    md = [
        {"photo_id": "a", "taken_at": "2024-01-01", "persons": [], "labels": [], "blur_score": 10.0},
        {"photo_id": "b", "taken_at": "2024-02-01", "persons": [], "labels": [], "blur_score": 200.0},
        {"photo_id": "c", "taken_at": "2024-03-01", "persons": [], "labels": [], "blur_score": 5.0},
    ]
    out = deterministic_ranker(md, target_count=2)
    ids = [p.photo_id for p in out.picks]
    assert ids[0] == "b"  # sharpest first


def test_deterministic_diversifies_dates() -> None:
    """Three near-identical sharp photos on day 1 should not crowd out a day-2 photo."""
    md = [
        {"photo_id": "x1", "taken_at": "2024-01-01", "persons": [], "labels": [], "blur_score": 100.0},
        {"photo_id": "x2", "taken_at": "2024-01-01", "persons": [], "labels": [], "blur_score": 99.0},
        {"photo_id": "x3", "taken_at": "2024-01-01", "persons": [], "labels": [], "blur_score": 98.0},
        {"photo_id": "y1", "taken_at": "2024-06-01", "persons": [], "labels": [], "blur_score": 60.0},
    ]
    out = deterministic_ranker(md, target_count=3)
    ids = {p.photo_id for p in out.picks}
    assert "y1" in ids  # diversity bonus should pull this in


def test_deterministic_empty_input() -> None:
    assert deterministic_ranker([], target_count=5).picks == []
    assert deterministic_ranker([{"photo_id": "a", "taken_at": None, "persons": [], "labels": [], "blur_score": 1.0}], target_count=0).picks == []


# ---------- Build metadata ----------

def test_build_photo_metadata_includes_no_paths() -> None:
    pid = _seed_photo(
        "m.jpg", blur=42.0, taken_at=datetime(2024, 1, 5, 10, 0, tzinfo=timezone.utc)
    )
    db = SessionLocal()
    try:
        md = build_photo_metadata(db, [pid])
    finally:
        db.close()
    assert len(md) == 1
    row = md[0]
    assert row["photo_id"] == str(pid)
    assert row["blur_score"] == 42.0
    assert "/" not in str(row)  # no stored_path / original_path leak


# ---------- Agent + fallback wiring ----------

def test_no_api_key_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.selection.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-REPLACE_ME", anthropic_model="claude-sonnet-4-6"),
    )
    pid = _seed_photo("a.jpg", blur=50.0, taken_at=None)

    db = SessionLocal()
    try:
        result = suggest_selection(db, [pid], target_count=1, criteria=None)
    finally:
        db.close()

    assert result.used_fallback is True
    assert len(result.picks) == 1
    assert result.picks[0].photo_id == str(pid)


def test_claude_happy_path(monkeypatch) -> None:
    pid = _seed_photo("a.jpg", blur=50.0, taken_at=None)
    photo_id_str = str(pid)

    fake_tool_use = MagicMock(type="tool_use", input={
        "picks": [
            {"photo_id": photo_id_str, "score": 0.92, "reason": "best_of_day: warm light"}
        ]
    })
    fake_message = MagicMock(content=[fake_tool_use])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    monkeypatch.setattr(agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_selection(db, [pid], target_count=1, criteria="warm")
    finally:
        db.close()

    assert result.used_fallback is False
    assert len(result.picks) == 1
    assert result.picks[0].reason == "best_of_day: warm light"
    fake_client.messages.create.assert_called_once()


def test_claude_returns_bogus_id_falls_back(monkeypatch) -> None:
    pid = _seed_photo("a.jpg", blur=10.0, taken_at=None)

    bogus_tool_use = MagicMock(type="tool_use", input={
        "picks": [{"photo_id": str(uuid.uuid4()), "score": 0.5, "reason": "made up"}]
    })
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(content=[bogus_tool_use])
    monkeypatch.setattr(agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_selection(db, [pid], target_count=1, criteria=None)
    finally:
        db.close()

    assert result.used_fallback is True
    assert result.picks[0].photo_id == str(pid)


def test_claude_returns_no_tool_use_falls_back(monkeypatch) -> None:
    pid = _seed_photo("a.jpg", blur=10.0, taken_at=None)

    # Only a text block, no tool_use.
    text_block = MagicMock(type="text", text="hello")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(content=[text_block])
    monkeypatch.setattr(agent_module.anthropic, "Anthropic", lambda **kw: fake_client)

    db = SessionLocal()
    try:
        result = suggest_selection(db, [pid], target_count=1, criteria=None)
    finally:
        db.close()

    assert result.used_fallback is True


def test_call_selection_agent_raises_without_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.selection.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-REPLACE_ME", anthropic_model="x"),
    )
    try:
        agent_module.call_selection_agent([], target_count=1, criteria=None)
    except SelectionAgentError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("expected SelectionAgentError")


# ---------- API ----------

def test_suggest_endpoint_with_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agents.selection.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-REPLACE_ME", anthropic_model="x"),
    )
    p1 = _seed_photo("a.jpg", blur=80.0, taken_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    p2 = _seed_photo("b.jpg", blur=10.0, taken_at=datetime(2024, 2, 1, tzinfo=timezone.utc))

    r = client.post(
        "/api/selection/suggest",
        json={"photo_ids": [str(p1), str(p2)], "target_count": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["used_fallback"] is True
    assert len(body["picks"]) == 1
    assert body["picks"][0]["photo_id"] == str(p1)  # sharper one


def test_suggest_endpoint_validates_target_count(monkeypatch) -> None:
    p1 = _seed_photo("a.jpg", blur=1.0, taken_at=None)
    r = client.post(
        "/api/selection/suggest",
        json={"photo_ids": [str(p1)], "target_count": 0},
    )
    assert r.status_code == 422
