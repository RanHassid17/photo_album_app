from __future__ import annotations

import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.models import Album, AlbumItem, AlbumStyle, CommentPosition, Photo
from app.services.imaging import open_image

log = logging.getLogger(__name__)


class PdfExportError(Exception):
    """Raised when an album cannot be rendered to PDF."""


# A4 landscape at 150 DPI — high enough for a digital album, small enough that the file
# stays under a few MB for ~30 pages. Print-quality output goes through the print ZIP.
_PAGE_W_PX = 1754
_PAGE_H_PX = 1240
_CAPTION_PAD_PX = 8


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """The visual difference between album styles.

    Style used to reach only the agent's prompt, so two albums with different styles
    rendered identically -- and whenever the deterministic fallback ran, style had no
    effect at all. These are the knobs that make the choice visible in the output.
    """

    bg: tuple[int, int, int]
    margin_px: int
    caption_px: int
    caption_fill: tuple[int, int, int]
    title_px: int
    title_fill: tuple[int, int, int]


_STYLES: dict[AlbumStyle, StyleSpec] = {
    AlbumStyle.MODERN: StyleSpec(
        bg=(255, 255, 255),
        margin_px=30,
        caption_px=20,
        caption_fill=(60, 60, 60),
        title_px=40,
        title_fill=(20, 20, 20),
    ),
    AlbumStyle.CLASSIC: StyleSpec(
        bg=(250, 247, 240),
        margin_px=66,
        caption_px=19,
        caption_fill=(84, 70, 52),
        title_px=46,
        title_fill=(48, 38, 26),
    ),
    AlbumStyle.KIDS: StyleSpec(
        bg=(255, 252, 240),
        margin_px=20,
        caption_px=23,
        caption_fill=(40, 80, 120),
        title_px=48,
        title_fill=(220, 90, 40),
    ),
    AlbumStyle.ROMANTIC: StyleSpec(
        bg=(253, 246, 248),
        margin_px=56,
        caption_px=20,
        caption_fill=(120, 70, 90),
        title_px=44,
        title_fill=(110, 50, 74),
    ),
    AlbumStyle.MINIMALIST: StyleSpec(
        bg=(255, 255, 255),
        margin_px=96,
        caption_px=16,
        caption_fill=(120, 120, 120),
        title_px=32,
        title_fill=(60, 60, 60),
    ),
}

_DEFAULT_STYLE = _STYLES[AlbumStyle.MODERN]


def _spec_for(style: Any) -> StyleSpec:
    try:
        return _STYLES.get(AlbumStyle(style), _DEFAULT_STYLE)
    except ValueError:
        return _DEFAULT_STYLE


def _load_font(size_px: int) -> ImageFont.ImageFont:
    """Return a TrueType font if one is available on the system, else Pillow's default.

    The default bitmap font does not support Hebrew, but it is never *worse* than crashing.
    """
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size_px)
            except OSError:
                continue
    return ImageFont.load_default()


def _open_photo(photo: Photo) -> Image.Image:
    path = Path(photo.stored_path)
    if not path.exists():
        raise PdfExportError(f"photo file missing on disk: {path}")
    img = open_image(path)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def _fit_into_box(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Resize-with-letterbox: preserve aspect, fit fully inside the target box."""
    scale = min(box_w / img.width, box_h / img.height)
    new_w = max(1, int(round(img.width * scale)))
    new_h = max(1, int(round(img.height * scale)))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _reserve_caption_band(
    box_x: int, box_y: int, box_w: int, box_h: int, position: CommentPosition, band: int
) -> tuple[int, int, int, int]:
    """Shrink a cell on the caption's edge so the photo and its caption don't compete."""
    if position is CommentPosition.ABOVE:
        box_y, box_h = box_y + band, box_h - band
    elif position is CommentPosition.BELOW:
        box_h -= band
    elif position is CommentPosition.START:
        box_x, box_w = box_x + band, box_w - band
    elif position is CommentPosition.END:
        box_w -= band
    return box_x, box_y, max(1, box_w), max(1, box_h)


def _draw_caption(
    page_img: Image.Image,
    text: str,
    *,
    photo_x: int,
    photo_y: int,
    photo_w: int,
    photo_h: int,
    position: CommentPosition,
    font: ImageFont.ImageFont,
    spec: StyleSpec,
) -> None:
    """Place a caption against the photo's *rendered* rectangle.

    The caption used to be positioned against the grid cell instead. Because a photo is
    letterboxed and centred inside its cell, a landscape photo in a tall cell left a wide
    gap between image and caption, and a tight cell put the caption on top of the image.
    """
    if not text:
        return
    draw = ImageDraw.Draw(page_img)
    # textbbox's origin is not (0, 0) — ascent/descent shift it. Keep the offsets so the
    # drawn glyphs (descenders included) land exactly where they were measured to.
    bbox = draw.textbbox((0, 0), text, font=font)
    off_x, off_y = bbox[0], bbox[1]
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad = _CAPTION_PAD_PX

    if position is CommentPosition.ABOVE:
        x = photo_x + (photo_w - text_w) // 2
        y = photo_y - text_h - pad
    elif position is CommentPosition.BELOW:
        x = photo_x + (photo_w - text_w) // 2
        y = photo_y + photo_h + pad
    elif position is CommentPosition.START:
        x = photo_x - text_w - pad
        y = photo_y + (photo_h - text_h) // 2
    elif position is CommentPosition.END:
        x = photo_x + photo_w + pad
        y = photo_y + (photo_h - text_h) // 2
    else:
        return

    # Clamp the whole glyph box inside the printable area.
    edge = max(8, spec.margin_px // 2)
    max_x = max(edge, page_img.width - edge - text_w)
    max_y = max(edge, page_img.height - edge - text_h)
    x = min(max(edge, x), max_x)
    y = min(max(edge, y), max_y)

    draw.text((x - off_x, y - off_y), text, fill=spec.caption_fill, font=font)


def _draw_title(page_img: Image.Image, title: str, spec: StyleSpec) -> None:
    draw = ImageDraw.Draw(page_img)
    font = _load_font(spec.title_px)
    bbox = draw.textbbox((0, 0), title, font=font)
    text_w = bbox[2] - bbox[0]
    x = max(spec.margin_px, (page_img.width - text_w) // 2)
    y = max(10, spec.margin_px // 2)
    draw.text((x - bbox[0], y - bbox[1]), title, fill=spec.title_fill, font=font)


def _render_page(
    items: list[AlbumItem],
    photos_by_id: dict[Any, Photo],
    *,
    spec: StyleSpec,
    title: str | None = None,
) -> Image.Image:
    canvas = Image.new("RGB", (_PAGE_W_PX, _PAGE_H_PX), spec.bg)
    font = _load_font(spec.caption_px)
    band = spec.caption_px + 14

    # Normalized item coordinates map into the style's content area, not the raw sheet.
    # This is what turns `margin_px` into a visible difference between styles.
    title_band = spec.title_px + spec.margin_px if title else 0
    content_x = spec.margin_px
    content_y = spec.margin_px + title_band
    content_w = _PAGE_W_PX - 2 * spec.margin_px
    content_h = _PAGE_H_PX - 2 * spec.margin_px - title_band

    if title:
        _draw_title(canvas, title, spec)

    for item in items:
        photo = photos_by_id.get(item.photo_id)
        if photo is None:
            continue
        pos = item.position
        box_x = content_x + int(round(pos["x"] * content_w))
        box_y = content_y + int(round(pos["y"] * content_h))
        box_w = max(1, int(round(pos["w"] * content_w)))
        box_h = max(1, int(round(pos["h"] * content_h)))

        caption_pos = CommentPosition(item.comment_position)
        has_caption = bool(item.comment) and caption_pos is not CommentPosition.NONE
        if has_caption:
            box_x, box_y, box_w, box_h = _reserve_caption_band(
                box_x, box_y, box_w, box_h, caption_pos, band
            )

        src = _open_photo(photo)
        try:
            sized = _fit_into_box(src, box_w, box_h)
            rotation = float(pos.get("rotation_deg") or 0.0)
            if not math.isclose(rotation, 0.0):
                sized = sized.rotate(-rotation, resample=Image.BICUBIC, expand=True)
            paste_x = box_x + (box_w - sized.width) // 2
            paste_y = box_y + (box_h - sized.height) // 2
            canvas.paste(sized, (paste_x, paste_y))
            photo_rect = (paste_x, paste_y, sized.width, sized.height)
        finally:
            src.close()

        if has_caption:
            _draw_caption(
                canvas,
                item.comment,
                photo_x=photo_rect[0],
                photo_y=photo_rect[1],
                photo_w=photo_rect[2],
                photo_h=photo_rect[3],
                position=caption_pos,
                font=font,
                spec=spec,
            )

    return canvas


def render_album_pdf(album: Album, photos: list[Photo]) -> bytes:
    """Render an album to a multi-page PDF in memory."""
    if not album.pages:
        raise PdfExportError("album has no pages")

    photos_by_id = {p.id: p for p in photos}
    spec = _spec_for(album.style)

    pages_sorted = sorted(album.pages, key=lambda p: p.index)
    title = (album.name or "").strip() or None
    rendered: list[Image.Image] = []
    try:
        for page_no, page in enumerate(pages_sorted):
            items_sorted = sorted(page.items, key=lambda it: it.position_index)
            rendered.append(
                _render_page(
                    items_sorted,
                    photos_by_id,
                    spec=spec,
                    title=title if page_no == 0 else None,
                )
            )

        buf = io.BytesIO()
        first, rest = rendered[0], rendered[1:]
        first.save(buf, format="PDF", save_all=True, append_images=rest, resolution=150.0)
        return buf.getvalue()
    finally:
        for img in rendered:
            img.close()
