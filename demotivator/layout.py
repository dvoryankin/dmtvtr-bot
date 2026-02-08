from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw
from pilmoji import Pilmoji

from utils.fonts import get_font, get_unicode_font
from utils.text import fit_text, has_emoji


@dataclass(frozen=True)
class LayoutConfig:
    font_paths: tuple[str, ...]
    unicode_font_paths: tuple[str, ...]


def build_layout_params(
    *,
    base_w: int,
    base_h: int,
    text: str,
    for_video: bool,
    cfg: LayoutConfig,
) -> tuple[Image.Image, int, int, int, int]:
    """Create demotivator canvas with border and text; return (canvas, target_w, target_h, pad_x, pad_y)."""
    target_w, target_h = base_w, base_h
    max_side = 720 if for_video else 1024

    if max(target_w, target_h) > max_side:
        ratio = max_side / max(target_w, target_h)
        target_w = int(target_w * ratio)
        target_h = int(target_h * ratio)

    if for_video:
        target_w = (target_w // 2) * 2
        target_h = (target_h // 2) * 2

    pad_top = 40
    pad_side = 40
    gap_to_text = 50
    gap_after_text = 40

    total_w = target_w + pad_side * 2
    font_size = max(20, int(total_w / 12))
    font = (
        get_unicode_font(
            font_size,
            unicode_font_paths=cfg.unicode_font_paths,
            font_paths=cfg.font_paths,
        )
        if has_emoji(text)
        else get_font(font_size, font_paths=cfg.font_paths)
    )

    temp_img = Image.new("RGB", (1, 1))
    lines = fit_text(text, font=font, max_width=total_w - 20, img=temp_img)
    text_block_h = len(lines) * (font_size + 10)
    pad_bottom = gap_to_text + text_block_h + gap_after_text

    total_h = target_h + pad_top + pad_bottom

    if for_video:
        total_w = (total_w // 2) * 2
        total_h = (total_h // 2) * 2

    canvas = Image.new("RGB", (total_w, total_h), "black")
    draw = ImageDraw.Draw(canvas)

    border = 2
    draw.rectangle(
        [(pad_side - 5, pad_top - 5), (pad_side + target_w + 4, pad_top + target_h + 4)],
        outline="white",
        width=border,
    )

    y_text = pad_top + target_h + gap_to_text
    with Pilmoji(canvas) as pilmoji:
        for line in lines:
            line_w, _ = pilmoji.getsize(line, font=font)
            x_text = (total_w - line_w) / 2
            pilmoji.text((int(x_text), int(y_text)), line, font=font, fill="white")
            y_text += font_size + 10

    return canvas, target_w, target_h, pad_side, pad_top
