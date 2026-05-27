from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.agents.prompts import SELECTION_SYSTEM, SELECTION_TOOL_SCHEMA
from app.config import get_settings

log = logging.getLogger(__name__)


class SelectionPick(BaseModel):
    photo_id: str
    score: float = Field(ge=0, le=1)
    reason: str = Field(max_length=120)


class SelectionResponse(BaseModel):
    picks: list[SelectionPick]


class SelectionAgentError(Exception):
    """Raised when the Claude call fails or returns invalid output."""


def _is_real_api_key(key: str) -> bool:
    return bool(key) and not key.startswith("sk-ant-REPLACE")


def call_selection_agent(
    photos_metadata: list[dict[str, Any]],
    target_count: int,
    criteria: str | None,
) -> SelectionResponse:
    """Call Claude Sonnet with the Selection Agent prompt.

    Raises SelectionAgentError on any failure (no key, network, bad JSON, schema
    mismatch, picks referencing unknown photo IDs). Callers should catch and
    fall back to the deterministic ranker.
    """
    settings = get_settings()
    if not _is_real_api_key(settings.anthropic_api_key):
        raise SelectionAgentError("ANTHROPIC_API_KEY not configured")

    user_payload: dict[str, Any] = {
        "target_count": target_count,
        "criteria": criteria or "",
        "photos": photos_metadata,
    }

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=SELECTION_SYSTEM,
            tools=[SELECTION_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_selection"},
            messages=[{"role": "user", "content": json.dumps(user_payload)}],
        )
    except anthropic.APIError as exc:
        raise SelectionAgentError(f"Anthropic API error: {exc}") from exc

    tool_block = next(
        (b for b in message.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        raise SelectionAgentError("Claude did not call submit_selection tool")

    try:
        parsed = SelectionResponse.model_validate(tool_block.input)
    except ValidationError as exc:
        raise SelectionAgentError(f"submit_selection schema invalid: {exc}") from exc

    valid_ids = {p["photo_id"] for p in photos_metadata}
    bogus = [p.photo_id for p in parsed.picks if p.photo_id not in valid_ids]
    if bogus:
        raise SelectionAgentError(f"Claude returned photo_ids not in input: {bogus[:3]}")

    return parsed
