from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.selection import (
    SelectionAgentError,
    SelectionPick,
    SelectionResponse,
    call_selection_agent,
)
from app.models import FaceEmbedding, Photo, PhotoLabel

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SelectionResult:
    picks: list[SelectionPick]
    used_fallback: bool
    model: str | None


def build_photo_metadata(db: Session, photo_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Assemble the metadata payload Claude sees -- IDs, dates, faces, labels, quality.

    Never includes image bytes or paths.
    """
    photos = list(db.scalars(select(Photo).where(Photo.id.in_(photo_ids))).all())

    # Fetch faces + labels in bulk to avoid N+1.
    face_rows = db.execute(
        select(FaceEmbedding.photo_id, FaceEmbedding.cluster_id).where(
            FaceEmbedding.photo_id.in_(photo_ids)
        )
    ).all()
    label_rows = db.execute(
        select(PhotoLabel.photo_id, PhotoLabel.label).where(
            PhotoLabel.photo_id.in_(photo_ids)
        )
    ).all()

    faces_by_photo: dict[uuid.UUID, list[str]] = {}
    for pid, cid in face_rows:
        if cid is None:
            continue
        faces_by_photo.setdefault(pid, []).append(str(cid))

    labels_by_photo: dict[uuid.UUID, list[str]] = {}
    for pid, lbl in label_rows:
        labels_by_photo.setdefault(pid, []).append(lbl)

    out: list[dict[str, Any]] = []
    for p in photos:
        out.append(
            {
                "photo_id": str(p.id),
                "taken_at": p.taken_at.isoformat() if p.taken_at else None,
                "persons": faces_by_photo.get(p.id, []),
                "labels": labels_by_photo.get(p.id, []),
                "blur_score": p.blur_score,
            }
        )
    return out


def suggest_selection(
    db: Session,
    photo_ids: list[uuid.UUID],
    target_count: int,
    criteria: str | None,
    *,
    anthropic_model: str | None = None,
) -> SelectionResult:
    metadata = build_photo_metadata(db, photo_ids)
    if not metadata:
        return SelectionResult(picks=[], used_fallback=False, model=None)

    try:
        ai_resp = call_selection_agent(metadata, target_count, criteria)
        return SelectionResult(
            picks=ai_resp.picks[:target_count],
            used_fallback=False,
            model=anthropic_model,
        )
    except SelectionAgentError as exc:
        log.warning("selection agent failed, using deterministic fallback: %s", exc)
        det = deterministic_ranker(metadata, target_count)
        return SelectionResult(picks=det.picks, used_fallback=True, model=None)


def deterministic_ranker(
    metadata: list[dict[str, Any]], target_count: int
) -> SelectionResponse:
    """Greedy ranker: blur-quality scaled by a date-diversity penalty.

    score = max(0.1, normalized_blur) * (1 / (1 + same_day_picks))
    The multiplicative penalty (rather than additive) makes diversity bite even
    when a date bucket already has the sharpest photos. Tie-breaker: more recent first.
    """
    if not metadata or target_count <= 0:
        return SelectionResponse(picks=[])

    blurs = [m["blur_score"] for m in metadata if m["blur_score"] is not None]
    blur_max = max(blurs) if blurs else 1.0
    blur_max = blur_max or 1.0  # avoid div-by-zero

    remaining = list(metadata)
    chosen: list[SelectionPick] = []
    chosen_days: dict[date, int] = {}

    while remaining and len(chosen) < target_count:
        scored: list[tuple[float, dict[str, Any]]] = []
        for m in remaining:
            quality = max(0.1, (m["blur_score"] or 0.0) / blur_max)
            day = _date_bucket(m["taken_at"])
            same_day = chosen_days.get(day, 0) if day else 0
            diversity = 1.0 / (1 + same_day)
            scored.append((quality * diversity, m))

        scored.sort(
            key=lambda t: (t[0], t[1]["taken_at"] or ""),
            reverse=True,
        )
        best_score, best = scored[0]
        chosen.append(
            SelectionPick(
                photo_id=best["photo_id"],
                score=min(1.0, round(best_score, 3)),
                reason=_fallback_reason(best),
            )
        )
        remaining.remove(best)
        day = _date_bucket(best["taken_at"])
        if day:
            chosen_days[day] = chosen_days.get(day, 0) + 1

    return SelectionResponse(picks=chosen)


def _date_bucket(taken_at: str | None) -> date | None:
    if not taken_at:
        return None
    try:
        return date.fromisoformat(taken_at[:10])
    except ValueError:
        return None


def _fallback_reason(m: dict[str, Any]) -> str:
    bits: list[str] = []
    if m.get("blur_score") is not None:
        bits.append(f"sharp ({m['blur_score']:.0f})")
    if m.get("persons"):
        bits.append(f"{len(m['persons'])} face(s)")
    if m.get("labels"):
        bits.append(",".join(m["labels"][:2]))
    return ", ".join(bits) if bits else "fallback pick"
