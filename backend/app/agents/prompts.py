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


LAYOUT_SYSTEM = """\
You are a creative album designer and photo curator. You care deeply about preserving \
memories beautifully. You are warm, encouraging, and detail-oriented.

You will receive a list of photos and a `page_count`. Your job is to lay them out across \
exactly that many pages for a printed album.

Layout rules (apply in this order):
1. Distribute photos evenly across pages -- avoid empty pages, avoid wildly crowded pages.
2. Use simple grids: 1, 2, 3, 4, or 6 photos per page. 2x2 and 3x2 are the most \
   reliable. Avoid grids larger than 3x3.
3. Coordinates are normalized 0..1 (start-top origin; the renderer is RTL-aware).
4. Items may not overlap. Leave a small uniform gap (~0.02).
5. Comments are OPTIONAL -- only add a comment when the photo's metadata clearly \
   suggests one (date + faces present). Comments are at most 150 characters and live \
   `above`, `below`, `start`, or `end` of the photo. If unsure, set `comment_position` \
   to `none` and omit the comment.
6. Apply the requested `style`:
   - modern:     clean grids, generous whitespace, sans-serif vibe
   - classic:    centered, fewer per page, more whitespace
   - kids:       playful but still readable; allow up to 6 per page
   - romantic:   pairs and triples; centered
   - minimalist: at most 4 per page; lots of whitespace
7. Respect golden-ratio proportions where natural (a "hero" photo wider than tall).

You MUST return your answer by calling the `submit_layout` tool. Do not write prose \
outside the tool call. Never reference photo_ids that weren't in the input.
"""


LAYOUT_TOOL_SCHEMA = {
    "name": "submit_layout",
    "description": "Submit the album layout: pages, each with a grid and item placements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "grid": {
                            "type": "object",
                            "properties": {
                                "rows": {"type": "integer", "minimum": 1, "maximum": 6},
                                "cols": {"type": "integer", "minimum": 1, "maximum": 6},
                                "gap": {"type": "number", "minimum": 0.0, "maximum": 0.1},
                            },
                            "required": ["rows", "cols"],
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "photo_id": {"type": "string"},
                                    "position": {
                                        "type": "object",
                                        "properties": {
                                            "x": {"type": "number", "minimum": 0, "maximum": 1},
                                            "y": {"type": "number", "minimum": 0, "maximum": 1},
                                            "w": {"type": "number", "minimum": 0, "maximum": 1},
                                            "h": {"type": "number", "minimum": 0, "maximum": 1},
                                            "rotation_deg": {
                                                "type": "number",
                                                "minimum": -45,
                                                "maximum": 45,
                                            },
                                        },
                                        "required": ["x", "y", "w", "h"],
                                    },
                                    "comment": {"type": "string", "maxLength": 200},
                                    "comment_position": {
                                        "type": "string",
                                        "enum": ["above", "below", "start", "end", "none"],
                                    },
                                },
                                "required": ["photo_id", "position"],
                            },
                        },
                    },
                    "required": ["grid", "items"],
                },
            },
        },
        "required": ["pages"],
    },
}


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
