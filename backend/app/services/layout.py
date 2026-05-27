from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents.layout import LayoutAgentError, call_layout_agent
from app.models import Album, AlbumItem, AlbumPage, AlbumStyle, CommentPosition
from app.schemas.layouts import (
    LayoutGrid,
    LayoutItem,
    LayoutPage,
    LayoutPlan,
    LayoutPosition,
)
from app.services.selection import build_photo_metadata

log = logging.getLogger(__name__)


@dataclass(slots=True)
class LayoutResult:
    album: Album
    plan: LayoutPlan
    used_fallback: bool
    model: str | None


# (photos_per_page) -> (rows, cols)
_GRID_FOR_COUNT: list[tuple[int, int, int]] = [
    # (max_count_on_page, rows, cols)
    (1, 1, 1),
    (2, 1, 2),
    (3, 1, 3),
    (4, 2, 2),
    (6, 2, 3),
    (9, 3, 3),
]


def _grid_for_count(n: int) -> tuple[int, int]:
    for max_n, rows, cols in _GRID_FOR_COUNT:
        if n <= max_n:
            return rows, cols
    # Cap at 3x3 -- the agent prompt enforces this and the fallback should too.
    return 3, 3


def _grid_positions(rows: int, cols: int, gap: float) -> list[LayoutPosition]:
    """Generate evenly-spaced cell positions in normalized 0..1 coordinates.

    Cells fill row-by-row from the start-top corner.
    """
    out: list[LayoutPosition] = []
    cell_w = (1.0 - gap * (cols + 1)) / cols
    cell_h = (1.0 - gap * (rows + 1)) / rows
    for r in range(rows):
        for c in range(cols):
            x = gap + c * (cell_w + gap)
            y = gap + r * (cell_h + gap)
            out.append(LayoutPosition(x=x, y=y, w=cell_w, h=cell_h))
    return out


def deterministic_layout(
    photo_ids: list[uuid.UUID], page_count: int
) -> LayoutPlan:
    """Distribute photos across `page_count` simple grids."""
    if not photo_ids or page_count <= 0:
        return LayoutPlan(pages=[])

    page_count = min(page_count, len(photo_ids))
    per_page = math.ceil(len(photo_ids) / page_count)
    rows, cols = _grid_for_count(per_page)

    pages: list[LayoutPage] = []
    idx = 0
    for _ in range(page_count):
        slice_end = min(idx + per_page, len(photo_ids))
        page_photos = photo_ids[idx:slice_end]
        idx = slice_end
        if not page_photos:
            break
        # If the last page has fewer photos, tighten the grid to fit.
        actual_rows, actual_cols = _grid_for_count(len(page_photos))
        gap = 0.02
        positions = _grid_positions(actual_rows, actual_cols, gap)
        items = [
            LayoutItem(
                photo_id=pid,
                position=positions[i],
                comment=None,
                comment_position=CommentPosition.NONE,
            )
            for i, pid in enumerate(page_photos)
        ]
        pages.append(
            LayoutPage(
                grid=LayoutGrid(rows=actual_rows, cols=actual_cols, gap=gap),
                items=items,
            )
        )

    return LayoutPlan(pages=pages)


def suggest_layout(
    db: Session,
    photo_ids: list[uuid.UUID],
    page_count: int,
    style: AlbumStyle,
    *,
    name: str | None = None,
    anthropic_model: str | None = None,
) -> LayoutResult:
    """Try the Claude Layout Agent; fall back to deterministic grid on any failure.

    On success or fallback, persist Album + AlbumPage + AlbumItem rows.
    """
    metadata = build_photo_metadata(db, photo_ids)

    used_fallback = False
    try:
        plan = call_layout_agent(metadata, page_count, style)
    except LayoutAgentError as exc:
        log.warning("layout agent failed, using deterministic fallback: %s", exc)
        plan = deterministic_layout(photo_ids, page_count)
        used_fallback = True

    if not plan.pages:
        plan = deterministic_layout(photo_ids, page_count)
        used_fallback = True

    album = Album(
        name=name,
        style=style,
        page_count=len(plan.pages),
        used_fallback=used_fallback,
        model=None if used_fallback else anthropic_model,
    )
    db.add(album)
    db.flush()

    for page_index, page in enumerate(plan.pages):
        ap = AlbumPage(
            album_id=album.id,
            index=page_index,
            layout_json={
                "rows": page.grid.rows,
                "cols": page.grid.cols,
                "gap": page.grid.gap,
            },
        )
        db.add(ap)
        db.flush()
        for item_index, item in enumerate(page.items):
            db.add(
                AlbumItem(
                    page_id=ap.id,
                    photo_id=item.photo_id,
                    position_index=item_index,
                    position={
                        "x": item.position.x,
                        "y": item.position.y,
                        "w": item.position.w,
                        "h": item.position.h,
                        "rotation_deg": item.position.rotation_deg,
                    },
                    comment=item.comment,
                    comment_position=item.comment_position,
                )
            )

    db.commit()
    db.refresh(album)
    return LayoutResult(
        album=album,
        plan=plan,
        used_fallback=used_fallback,
        model=None if used_fallback else anthropic_model,
    )
