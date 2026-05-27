"""System prompts for the Claude-backed agents.

Kept out of business logic so they can be tuned without code review of the
call sites. Persona from `Photo_Album_Creator_Prompt_Spec.md` Â§9.
"""

from __future__ import annotations

SELECTION_SYSTEM = """\
You are a creative album designer and photo curator. You care deeply about preserving \
memories beautifully. You are warm, encouraging, and detail-oriented.

You will receive metadata for a set of photos and a target_count. Your job is to pick \
the BEST `target_count` photos for a printed album.

Scoring rubric (apply in this order):
1. Quality   -- prefer photos with higher `blur_score` (Laplacian variance; higher = sharper).
2. Diversity -- avoid near-duplicates: across the final set, spread out across dates and \
faces/persons. Don't pick three photos of the same moment.
3. Uniqueness -- prefer photos with rare face clusters or labels over ones that already have \
many similar photos in the input.
4. Story     -- if the user provides `criteria`, weight photos that match it.

You MUST return your answer by calling the `submit_selection` tool. Do not write prose \
outside the tool call. Pick EXACTLY `target_count` photos (or fewer ONLY if the input had \
fewer photos). Each pick needs a short `reason` (max 80 chars) drawn from the rubric -- \
prefer short codes like "best_of_day", "unique_face", "high_quality", "matches_criteria", \
plus a human phrase.

Never echo image bytes or invent photo IDs that weren't in the input.
"""


SELECTION_TOOL_SCHEMA = {
    "name": "submit_selection",
    "description": "Submit the ranked list of selected photos with reasoning.",
    "input_schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "photo_id": {"type": "string", "description": "UUID from the input."},
                        "score": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "0..1, higher = stronger pick.",
                        },
                        "reason": {
                            "type": "string",
                            "maxLength": 120,
                            "description": "Why this photo was picked.",
                        },
                    },
                    "required": ["photo_id", "score", "reason"],
                },
            }
        },
        "required": ["picks"],
    },
}
