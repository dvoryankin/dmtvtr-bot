from __future__ import annotations

from collections.abc import Sequence
import os

from PIL import ImageFont


def get_font(size: int, *, font_paths: Sequence[str]) -> ImageFont.ImageFont:
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def get_unicode_font(
    size: int, *, unicode_font_paths: Sequence[str], font_paths: Sequence[str]
) -> ImageFont.ImageFont:
    for font_path in unicode_font_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return get_font(size, font_paths=font_paths)

