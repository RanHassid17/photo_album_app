"""Contract tests for the two Claude agents.

Both agents validate Claude's tool output before it reaches the database. These tests
cover the completeness/uniqueness rules: a response can satisfy the JSON schema and
still be wrong (a repeated photo, a dropped photo, the wrong number of picks), which is
exactly the class of bug that produced duplicate photos in exported albums.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.agents import layout as layout_agent
from app.agents import selection as selection_agent
from app.agents.layout import LayoutAgentError, call_layout_agent
from app.agents.selection import SelectionAgentError, call_selection_agent
from app.models import AlbumStyle


def _tool_block(payload: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload
    return block


def _install_fake_claude(monkeypatch, module, payload: dict) -> None:
    """Point an agent module at a Claude that always returns `payload`."""
    monkeypatch.setattr(
        f"app.agents.{module.__name__.rsplit('.', 1)[-1]}.get_settings",
        lambda: MagicMock(anthropic_api_key="sk-ant-test-key", anthropic_model="claude-test"),
    )
    fake_client = MagicMock()
    fake_client.messages.create.return_value = MagicMock(content=[_tool_block(payload)])
    monkeypatch.setattr(module.anthropic, "Anthropic", lambda **kw: fake_client)


def _metadata(n: int) -> list[dict]:
    return [{"photo_id": str(uuid.uuid4()), "blur_score": 50.0, "taken_at": None} for _ in range(n)]


def _position(i: int = 0) -> dict:
    """Non-overlapping boxes in a single row — the agent now rejects overlaps."""
    return {"x": 0.02 + i * 0.32, "y": 0.02, "w": 0.28, "h": 0.9}


# ---------- Layout agent ----------

def test_layout_rejects_repeated_photo(monkeypatch) -> None:
    meta = _metadata(2)
    repeated = meta[0]["photo_id"]
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {"photo_id": repeated, "position": _position(0)},
                    {"photo_id": repeated, "position": _position(1)},
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    with pytest.raises(LayoutAgentError, match="more than once"):
        call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)


def test_layout_absorbs_omitted_photo_instead_of_rejecting(monkeypatch) -> None:
    """A dropped photo is added back, not treated as a broken layout.

    Observed in the running app: the agent laid out 11 of 12 photos. Rejecting threw
    away 11 good placements over one miss and told the user the AI was unavailable.
    """
    meta = _metadata(3)
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {"photo_id": meta[0]["photo_id"], "position": _position(0)},
                    {"photo_id": meta[1]["photo_id"], "position": _position(1)},
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    plan = call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)

    placed = {str(it.photo_id) for pg in plan.pages for it in pg.items}
    assert placed == {m["photo_id"] for m in meta}          # nothing dropped
    assert len(placed) == 3                                  # and nothing duplicated

    # The repaired page must still be a usable layout.
    boxes = [(i.position.x, i.position.y, i.position.w, i.position.h)
             for pg in plan.pages for i in pg.items]
    for x, y, w, h in boxes:
        assert x + w <= 1.0 + 1e-9 and y + h <= 1.0 + 1e-9


def test_layout_still_rejects_duplicates_after_repair_exists(monkeypatch) -> None:
    """Repairing omissions must not soften the duplicate rule.

    A photo placed twice is unrecoverable — we cannot know which copy was intended.
    """
    meta = _metadata(3)
    dup = meta[0]["photo_id"]
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {"photo_id": dup, "position": _position(0)},
                    {"photo_id": dup, "position": _position(1)},
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    with pytest.raises(LayoutAgentError, match="more than once"):
        call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)


def test_layout_accepts_complete_unique_placement(monkeypatch) -> None:
    meta = _metadata(2)
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {"photo_id": meta[0]["photo_id"], "position": _position(0)},
                    {"photo_id": meta[1]["photo_id"], "position": _position(1)},
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    plan = call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)
    assert len(plan.pages) == 1
    assert len(plan.pages[0].items) == 2


# ---------- Selection agent ----------

def test_selection_rejects_duplicate_pick(monkeypatch) -> None:
    meta = _metadata(3)
    dup = meta[0]["photo_id"]
    payload = {
        "picks": [
            {"photo_id": dup, "score": 0.9, "reason": "a"},
            {"photo_id": dup, "score": 0.8, "reason": "b"},
        ]
    }
    _install_fake_claude(monkeypatch, selection_agent, payload)

    with pytest.raises(SelectionAgentError, match="duplicate"):
        call_selection_agent(meta, target_count=2, criteria=None)


def test_selection_rejects_short_response(monkeypatch) -> None:
    meta = _metadata(4)
    payload = {"picks": [{"photo_id": meta[0]["photo_id"], "score": 0.9, "reason": "a"}]}
    _install_fake_claude(monkeypatch, selection_agent, payload)

    with pytest.raises(SelectionAgentError, match="target_count mismatch"):
        call_selection_agent(meta, target_count=3, criteria=None)


def test_selection_allows_fewer_when_input_is_smaller(monkeypatch) -> None:
    """Asking for more photos than exist is legal — the cap is the input size."""
    meta = _metadata(2)
    payload = {
        "picks": [
            {"photo_id": meta[0]["photo_id"], "score": 0.9, "reason": "a"},
            {"photo_id": meta[1]["photo_id"], "score": 0.7, "reason": "b"},
        ]
    }
    _install_fake_claude(monkeypatch, selection_agent, payload)

    resp = call_selection_agent(meta, target_count=10, criteria=None)
    assert len(resp.picks) == 2


def test_layout_clamps_offpage_box_instead_of_rejecting(monkeypatch) -> None:
    """A box slightly off the page is repaired, not thrown away.

    Rejecting sent an otherwise-good layout to the deterministic fallback and told the
    user the AI was unavailable.
    """
    meta = _metadata(1)
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 1, "gap": 0.02},
                "items": [
                    {
                        "photo_id": meta[0]["photo_id"],
                        "position": {"x": 0.3, "y": 0.3, "w": 0.9, "h": 0.9},
                    }
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    plan = call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)
    pos = plan.pages[0].items[0].position
    assert pos.x + pos.w <= 1.0 + 1e-9
    assert pos.y + pos.h <= 1.0 + 1e-9
    assert pos.w == 0.9 and pos.h == 0.9  # size preserved, only moved


def test_layout_rejects_substantial_overlap(monkeypatch) -> None:
    meta = _metadata(2)
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {
                        "photo_id": meta[0]["photo_id"],
                        "position": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5},
                    },
                    {
                        "photo_id": meta[1]["photo_id"],
                        "position": {"x": 0.15, "y": 0.15, "w": 0.5, "h": 0.5},
                    },
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    with pytest.raises(LayoutAgentError, match="overlap"):
        call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)


def test_layout_tolerates_slight_overlap(monkeypatch) -> None:
    """Touching corners are normal in a free-form layout and must not trigger fallback."""
    meta = _metadata(2)
    payload = {
        "pages": [
            {
                "grid": {"rows": 1, "cols": 2, "gap": 0.02},
                "items": [
                    {
                        "photo_id": meta[0]["photo_id"],
                        "position": {"x": 0.02, "y": 0.02, "w": 0.45, "h": 0.9},
                    },
                    {
                        "photo_id": meta[1]["photo_id"],
                        "position": {"x": 0.46, "y": 0.02, "w": 0.45, "h": 0.9},
                    },
                ],
            }
        ]
    }
    _install_fake_claude(monkeypatch, layout_agent, payload)

    plan = call_layout_agent(meta, page_count=1, style=AlbumStyle.MODERN)
    assert len(plan.pages[0].items) == 2
