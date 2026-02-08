from __future__ import annotations

from collections.abc import Sequence
import logging

from PIL import Image, ImageFont
from pilmoji import Pilmoji

from utils.fonts import get_font, get_unicode_font


def has_emoji(text: str) -> bool:
    for char in text:
        code = ord(char)
        if (
            0x1F300 <= code <= 0x1F9FF
            or 0x2600 <= code <= 0x26FF
            or 0x2700 <= code <= 0x27BF
            or 0xFE00 <= code <= 0xFE0F
            or 0x1F000 <= code <= 0x1F02F
            or 0x1F0A0 <= code <= 0x1F0FF
            or 0x1F100 <= code <= 0x1F64F
            or 0x1F680 <= code <= 0x1F6FF
            or 0x1F900 <= code <= 0x1F9FF
            or 0x1FA00 <= code <= 0x1FA6F
            or 0x1FA70 <= code <= 0x1FAFF
            or 0x2300 <= code <= 0x23FF
            or 0x25A0 <= code <= 0x25FF
        ):
            return True
    return False


def fit_text(text: str, *, font: ImageFont.ImageFont, max_width: int, img: Image.Image) -> list[str]:
    """Split text into lines using Pilmoji for accurate emoji measurement."""
    lines: list[str] = []
    words = text.split()
    current_line = ""

    with Pilmoji(img) as pilmoji:
        for word in words:
            if len(lines) >= 10:
                break

            test_line = (current_line + " " + word).strip()
            w, _h = pilmoji.getsize(test_line, font=font)
            if w <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else ["..."]


def generate_text_image(
    text: str,
    *,
    output_path: str,
    size: tuple[int, int] = (600, 600),
    font_paths: Sequence[str],
    unicode_font_paths: Sequence[str],
) -> bool:
    """Generate an image from text (with colored emojis via Pilmoji)."""
    try:
        img = Image.new("RGB", size, "white")
        use_unicode = has_emoji(text)

        max_font_size = 120
        min_font_size = 40

        best_font: ImageFont.ImageFont | None = None
        best_lines: list[str] = []

        for font_size in range(max_font_size, min_font_size, -10):
            font = (
                get_unicode_font(font_size, unicode_font_paths=unicode_font_paths, font_paths=font_paths)
                if use_unicode
                else get_font(font_size, font_paths=font_paths)
            )
            lines = fit_text(text, font=font, max_width=size[0] - 40, img=img)
            total_height = len(lines) * (font_size + 10)
            if total_height < size[1] - 40:
                best_font = font
                best_lines = lines
                break

        if best_font is None:
            best_font = (
                get_unicode_font(min_font_size, unicode_font_paths=unicode_font_paths, font_paths=font_paths)
                if use_unicode
                else get_font(min_font_size, font_paths=font_paths)
            )
            best_lines = fit_text(text, font=best_font, max_width=size[0] - 40, img=img)

        font_size = getattr(best_font, "size", min_font_size)
        total_height = len(best_lines) * (font_size + 10)
        y = (size[1] - total_height) / 2

        with Pilmoji(img) as pilmoji:
            for line in best_lines:
                line_w, _ = pilmoji.getsize(line, font=best_font)
                x = (size[0] - line_w) / 2
                pilmoji.text((int(x), int(y)), line, font=best_font, fill="black")
                y += font_size + 10

        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error("Error generating text image: %s", e, exc_info=True)
        return False

