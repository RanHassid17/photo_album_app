from __future__ import annotations

import logging
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

# Golden-ratio split used for hero pages -- prompt spec §14 Agent 3 calls for a
# golden-ratio layout engine, and it is what stops every page looking like a grid.
_HERO_RATIO = 0.618

# How many photos each style wants per page, as a repeating cycle. The cycle is scaled
# to the real photo count, so what it actually encodes is *relative* density: the album
# alternates between sparse feature pages and busier ones instead of dividing evenly.
_STYLE_DENSITY: dict[AlbumStyle, tuple[int, ...]] = {
    AlbumStyle.MODERN: (1, 4, 2, 6, 3),
    AlbumStyle.CLASSIC: (1, 3, 2, 2),
    AlbumStyle.KIDS: (4, 6, 3, 6),
    AlbumStyle.ROMANTIC: (2, 1, 3, 2),
    AlbumStyle.MINIMALIST: (1, 2, 1, 3),
}

# Page margin per style, as a fraction of the page. Bigger margin = calmer page.
_STYLE_GAP: dict[AlbumStyle, float] = {
    AlbumStyle.MODERN: 0.025,
    AlbumStyle.CLASSIC: 0.045,
    AlbumStyle.KIDS: 0.018,
    AlbumStyle.ROMANTIC: 0.040,
    AlbumStyle.MINIMALIST: 0.060,
}


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


def _hero_positions(n: int, gap: float) -> list[LayoutPosition]:
    """One dominant photo beside a column of smaller ones.

    The first position is the hero and is deliberately several times the area of the
    others: an album where every photo is the same size reads as a contact sheet, not a
    designed page.
    """
    if n <= 1:
        return [LayoutPosition(x=gap, y=gap, w=1.0 - 2 * gap, h=1.0 - 2 * gap)]

    hero_w = _HERO_RATIO - 1.5 * gap
    hero = LayoutPosition(x=gap, y=gap, w=hero_w, h=1.0 - 2 * gap)

    col_x = gap + hero_w + gap
    col_w = 1.0 - col_x - gap
    rest = n - 1
    cell_h = (1.0 - gap * (rest + 1)) / rest

    out = [hero]
    for i in range(rest):
        out.append(
            LayoutPosition(x=col_x, y=gap + i * (cell_h + gap), w=col_w, h=cell_h)
        )
    return out


def _page_densities(total: int, page_count: int, style: AlbumStyle) -> list[int]:
    """Split `total` photos across `page_count` pages using the style's density cycle.

    Replaces the previous `ceil(total / page_count)` even split, which guaranteed that
    every page held the same number of photos no matter the style or the material.
    """
    cycle = _STYLE_DENSITY.get(style, _STYLE_DENSITY[AlbumStyle.MODERN])
    raw = [cycle[i % len(cycle)] for i in range(page_count)]

    scale = total / sum(raw)
    counts = [max(1, round(r * scale)) for r in raw]

    # Rounding and the min-1 floor drift off the target; settle the difference by
    # walking the pages, densest first when removing so feature pages stay sparse.
    drift = total - sum(counts)
    guard = 0
    while drift != 0 and guard < 10_000:
        guard += 1
        if drift > 0:
            idx = max(range(page_count), key=lambda i: counts[i])
            counts[idx] += 1
            drift -= 1
        else:
            idx = max(range(page_count), key=lambda i: counts[i])
            if counts[idx] > 1:
                counts[idx] -= 1
                drift += 1
            else:
                break
    return counts


def deterministic_layout(
    photo_ids: list[uuid.UUID],
    page_count: int,
    style: AlbumStyle = AlbumStyle.MODERN,
) -> LayoutPlan:
    """Distribute photos across pages with style-driven density and hero sizing."""
    if not photo_ids or page_count <= 0:
        return LayoutPlan(pages=[])

    page_count = min(page_count, len(photo_ids))
    gap = _STYLE_GAP.get(style, 0.025)
    densities = _page_densities(len(photo_ids), page_count, style)

    pages: list[LayoutPage] = []
    idx = 0
    for page_index, want in enumerate(densities):
        slice_end = min(idx + want, len(photo_ids))
        page_photos = photo_ids[idx:slice_end]
        idx = slice_end
        if not page_photos:
            break

        n = len(page_photos)
        # Alternate hero pages with grid pages so the album has a rhythm. Photos arrive
        # in selection-score order, so the first of each slice is the strongest and
        # earns the hero slot.
        use_hero = n == 1 or (page_index % 2 == 0 and n >= 2)
        if use_hero:
            positions = _hero_positions(n, gap)
            # Describes the hero + stacked column; LayoutGrid caps rows at 6, so a
            # dense hero page reports the cap rather than failing validation.
            rows, cols = (1, 1) if n == 1 else (min(6, n - 1), 2)
        else:
            rows, cols = _grid_for_count(n)
            positions = _grid_positions(rows, cols, gap)

        items = [
            LayoutItem(
                photo_id=pid,
                position=positions[i],
                emphasis="hero" if (use_hero and i == 0 and n > 1) else "normal",
                comment=None,
                comment_position=CommentPosition.NONE,
            )
            for i, pid in enumerate(page_photos)
        ]
        pages.append(
            LayoutPage(grid=LayoutGrid(rows=rows, cols=cols, gap=gap), items=items)
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
        plan = deterministic_layout(photo_ids, page_count, style)
        used_fallback = True

    if not plan.pages:
        plan = deterministic_layout(photo_ids, page_count, style)
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
                "style": style.value,
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
                        "emphasis": item.emphasis,
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
