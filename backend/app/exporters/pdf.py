from __future__ import annotations

import io
import logging
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.models import Album, AlbumItem, CommentPosition, Photo

log = logging.getLogger(__name__)


class PdfExportError(Exception):
    """Raised when an album cannot be rendered to PDF."""


# A4 landscape at 150 DPI — high enough for a digital album, small enough that the file
# stays under a few MB for ~30 pages. Print-quality output goes through the print ZIP.
_PAGE_W_PX = 1754
_PAGE_H_PX = 1240
_PAGE_BG = (255, 255, 255)
_CAPTION_PAD_PX = 6


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
    img = Image.open(path)
    img.load()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    return img


def _fit_into_box(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Resize-with-letterbox: preserve aspect, fit fully inside the target box."""
    scale = min(box_w / img.width, box_h / img.height)
    new_w = max(1, int(round(img.width * scale)))
    new_h = max(1, int(round(img.height * scale)))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _draw_caption(
    page_img: Image.Image,
    text: str,
    *,
    box_x: int,
    box_y: int,
    box_w: int,
    box_h: int,
    position: CommentPosition,
    font: ImageFont.ImageFont,
) -> None:
    if not text:
        return
    draw = ImageDraw.Draw(page_img)
    # Pillow may truncate very long lines; the schema already caps at 200 chars.
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad = _CAPTION_PAD_PX

    if position is CommentPosition.ABOVE:
        x = box_x + (box_w - text_w) // 2
        y = max(0, box_y - text_h - pad)
    elif position is CommentPosition.BELOW:
        x = box_x + (box_w - text_w) // 2
        y = min(page_img.height - text_h, box_y + box_h + pad)
    elif position is CommentPosition.START:
        x = max(0, box_x - text_w - pad)
        y = box_y + (box_h - text_h) // 2
    elif position is CommentPosition.END:
        x = min(page_img.width - text_w, box_x + box_w + pad)
        y = box_y + (box_h - text_h) // 2
    else:
        return

    draw.text((x, y), text, fill=(40, 40, 40), font=font)


def _render_page(items: list[AlbumItem], photos_by_id: dict[Any, Photo]) -> Image.Image:
    canvas = Image.new("RGB", (_PAGE_W_PX, _PAGE_H_PX), _PAGE_BG)
    font = _load_font(20)

    for item in items:
        photo = photos_by_id.get(item.photo_id)
        if photo is None:
            continue
        pos = item.position
        box_x = int(round(pos["x"] * _PAGE_W_PX))
        box_y = int(round(pos["y"] * _PAGE_H_PX))
        box_w = max(1, int(round(pos["w"] * _PAGE_W_PX)))
        box_h = max(1, int(round(pos["h"] * _PAGE_H_PX)))

        src = _open_photo(photo)
        try:
            sized = _fit_into_box(src, box_w, box_h)
            rotation = float(pos.get("rotation_deg") or 0.0)
            if not math.isclose(rotation, 0.0):
                sized = sized.rotate(-rotation, resample=Image.BICUBIC, expand=True)
            paste_x = box_x + (box_w - sized.width) // 2
            paste_y = box_y + (box_h - sized.height) // 2
            canvas.paste(sized, (paste_x, paste_y))
        finally:
            src.close()

        if item.comment:
            _draw_caption(
                canvas,
                item.comment,
                box_x=box_x,
                box_y=box_y,
                box_w=box_w,
                box_h=box_h,
                position=CommentPosition(item.comment_position),
                font=font,
            )

    return canvas


def render_album_pdf(album: Album, photos: list[Photo]) -> bytes:
    """Render an album to a multi-page PDF in memory."""
    if not album.pages:
        raise PdfExportError("album has no pages")

    photos_by_id = {p.id: p for p in photos}

    pages_sorted = sorted(album.pages, key=lambda p: p.index)
    rendered: list[Image.Image] = []
    try:
        for page in pages_sorted:
            items_sorted = sorted(page.items, key=lambda it: it.position_index)
            rendered.append(_render_page(items_sorted, photos_by_id))

        buf = io.BytesIO()
        first, rest = rendered[0], rendered[1:]
        first.save(buf, format="PDF", save_all=True, append_images=rest, resolution=150.0)
        return buf.getvalue()
    finally:
        for img in rendered:
            img.close()
