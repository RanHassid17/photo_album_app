from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import anthropic
from pydantic import ValidationError

from app.agents.prompts import LAYOUT_SYSTEM, LAYOUT_TOOL_SCHEMA
from app.config import get_settings
from app.models import AlbumStyle
from app.schemas.layouts import LayoutPlan

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

    missing = valid_ids - placed
    if missing:
        raise LayoutAgentError(
            f"layout omits {len(missing)} of {len(valid_ids)} input photos"
        )

    return parsed
