from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any

import anthropic
from pydantic import ValidationError

from app.agents.prompts import LAYOUT_SYSTEM, LAYOUT_TOOL_SCHEMA
from app.config import get_settings
from app.models import AlbumStyle, CommentPosition
from app.schemas.layouts import (
    LayoutGrid,
    LayoutItem,
    LayoutPage,
    LayoutPlan,
    LayoutPosition,
)

log = logging.getLogger(__name__)


class LayoutAgentError(Exception):
    """Raised when the Claude layout call fails or returns invalid output."""


def _is_real_api_key(key: str) -> bool:
    return bool(key) and not key.startswith("sk-ant-REPLACE")


def call_layout_agent(
    photos_metadata: list[dict[str, Any]],
    page_count: int,
    style: AlbumStyle,
) -> LayoutPlan:
    """Call Claude Sonnet with the Layout Agent prompt.

    Raises LayoutAgentError on any failure. Callers catch and fall back to a
    deterministic grid generator.
    """
    settings = get_settings()
    if not _is_real_api_key(settings.anthropic_api_key):
        raise LayoutAgentError("ANTHROPIC_API_KEY not configured")

    user_payload: dict[str, Any] = {
        "page_count": page_count,
        "style": style.value,
        "photos": photos_metadata,
    }

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=LAYOUT_SYSTEM,
            tools=[LAYOUT_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_layout"},
            messages=[{"role": "user", "content": json.dumps(user_payload)}],
        )
    except anthropic.APIError as exc:
        raise LayoutAgentError(f"Anthropic API error: {exc}") from exc

    tool_block = next(
        (b for b in message.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        raise LayoutAgentError("Claude did not call submit_layout tool")

    try:
        parsed = LayoutPlan.model_validate(tool_block.input)
    except ValidationError as exc:
        raise LayoutAgentError(f"submit_layout schema invalid: {exc}") from exc

    if len(parsed.pages) != page_count:
        raise LayoutAgentError(
            f"page_count mismatch: agent returned {len(parsed.pages)}, wanted {page_count}"
        )

    valid_ids: set[uuid.UUID] = {uuid.UUID(p["photo_id"]) for p in photos_metadata}
    placed: set[uuid.UUID] = set()
    for page in parsed.pages:
        for item in page.items:
            if item.photo_id not in valid_ids:
                raise LayoutAgentError(
                    f"layout references photo_id not in input: {item.photo_id}"
                )
            # Every input photo must appear exactly once. Without this the agent can
            # silently repeat one photo and drop another -- the layout still validates
            # against the schema, so nothing else would catch it.
            if item.photo_id in placed:
                raise LayoutAgentError(f"layout places photo {item.photo_id} more than once")
            placed.add(item.photo_id)

    # A dropped photo is repaired, not rejected. Observed in practice: the agent laid
    # out 11 of 12 photos, and throwing the plan away lost 11 good placements over one
    # miss -- the user just saw "the AI was unavailable". Only a photo placed *twice* is
    # unrecoverable, because we cannot know which copy was intended.
    missing = valid_ids - placed
    if missing:
        log.info(
            "layout omitted %d of %d photos; absorbing them into the emptiest page",
            len(missing),
            len(valid_ids),
        )
        _absorb_missing(parsed, sorted(missing, key=str))

    # Geometry is REPAIRED, not rejected. Asking the agent for varied, free-form boxes
    # (rather than fixed grid cells) means small arithmetic slips are routine; throwing
    # the whole plan away for a box 0.01 over the edge sends a perfectly good layout to
    # the deterministic fallback and tells the user "the AI was unavailable". Only
    # semantic errors above -- a photo placed twice or dropped -- are unrecoverable.
    for page in parsed.pages:
        for item in page.items:
            _clamp_into_page(item.position)

    # A little overlap can be deliberate (a photo tucked under a corner). Only a
    # substantial collision is treated as a broken layout.
    for page_no, page in enumerate(parsed.pages):
        boxes = [
            (it.position.x, it.position.y, it.position.w, it.position.h)
            for it in page.items
        ]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap_fraction(boxes[i], boxes[j]) > _MAX_OVERLAP_FRACTION:
                    raise LayoutAgentError(
                        f"page {page_no}: items {i} and {j} overlap substantially"
                    )

    return parsed


# Fraction of the smaller box that may be covered before a layout counts as broken.
_MAX_OVERLAP_FRACTION = 0.2


def _grid_boxes(n: int, gap: float = 0.025) -> list[LayoutPosition]:
    """Evenly spaced cells for `n` photos, filling row by row."""
    cols = 1 if n <= 1 else 2 if n <= 4 else 3
    rows = math.ceil(n / cols)
    cell_w = (1.0 - gap * (cols + 1)) / cols
    cell_h = (1.0 - gap * (rows + 1)) / rows
    out: list[LayoutPosition] = []
    for i in range(n):
        r, c = divmod(i, cols)
        out.append(
            LayoutPosition(
                x=gap + c * (cell_w + gap),
                y=gap + r * (cell_h + gap),
                w=cell_w,
                h=cell_h,
            )
        )
    return out


def _absorb_missing(plan: LayoutPlan, missing: list[uuid.UUID]) -> None:
    """Add dropped photos to the emptiest page, re-flowing just that page to a grid.

    Every other page keeps the agent's design; only the page that has to grow is
    recomputed, and a uniform grid guarantees the additions cannot overlap.
    """
    if not plan.pages:
        plan.pages.append(LayoutPage(grid=LayoutGrid(rows=1, cols=1), items=[]))

    target = min(plan.pages, key=lambda pg: len(pg.items))
    kept = list(target.items)
    photo_ids = [it.photo_id for it in kept] + list(missing)

    boxes = _grid_boxes(len(photo_ids))
    emphasis_by_id = {it.photo_id: it.emphasis for it in kept}
    comment_by_id = {it.photo_id: (it.comment, it.comment_position) for it in kept}

    target.items = [
        LayoutItem(
            photo_id=pid,
            position=boxes[i],
            emphasis=emphasis_by_id.get(pid, "normal"),
            comment=comment_by_id.get(pid, (None, CommentPosition.NONE))[0],
            comment_position=comment_by_id.get(pid, (None, CommentPosition.NONE))[1],
        )
        for i, pid in enumerate(photo_ids)
    ]
    cols = 1 if len(photo_ids) <= 1 else 2 if len(photo_ids) <= 4 else 3
    target.grid = LayoutGrid(rows=math.ceil(len(photo_ids) / cols), cols=cols, gap=0.025)


def _clamp_into_page(pos: LayoutPosition) -> None:
    """Nudge a box back inside the unit square, preserving size where possible."""
    pos.w = min(pos.w, 1.0)
    pos.h = min(pos.h, 1.0)
    pos.x = min(max(0.0, pos.x), 1.0 - pos.w)
    pos.y = min(max(0.0, pos.y), 1.0 - pos.h)


def _overlap_fraction(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    smaller = min(aw * ah, bw * bh)
    if smaller <= 0:
        return 0.0
    return (overlap_w * overlap_h) / smaller
