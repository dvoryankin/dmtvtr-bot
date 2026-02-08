from __future__ import annotations

import logging
import os

from PIL import Image

from demotivator.layout import LayoutConfig, build_layout_params
from utils.image_effects import apply_invert, apply_vintage


def create_demotivator_image(
    *,
    img_path: str,
    text: str,
    output_path: str,
    layout_cfg: LayoutConfig,
    is_avatar: bool = False,
    effect: str | None = None,
) -> bool:
    """Create a demotivator from an image."""
    try:
        orig = Image.open(img_path).convert("RGBA")

        if is_avatar or max(orig.size) < 300:
            orig = orig.resize((600, 600), Image.Resampling.LANCZOS)

        # Apply effect (by saving to temp file to reuse path-based effects).
        if effect in {"invert", "vintage"}:
            temp_path = img_path + "_temp.png"
            try:
                orig.save(temp_path)
                if effect == "invert":
                    if apply_invert(img_path=temp_path, output_path=temp_path):
                        orig = Image.open(temp_path).convert("RGBA")
                else:
                    if apply_vintage(img_path=temp_path, output_path=temp_path):
                        orig = Image.open(temp_path).convert("RGBA")
            finally:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

        bg, t_w, t_h, p_x, p_y = build_layout_params(
            base_w=orig.width,
            base_h=orig.height,
            text=text,
            for_video=False,
            cfg=layout_cfg,
        )

        orig = orig.resize((t_w, t_h), Image.Resampling.LANCZOS)
        bg_rgba = bg.convert("RGBA")
        bg_rgba.paste(orig, (p_x, p_y), orig)
        bg_rgba.convert("RGB").save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error("Image demotivator error: %s", e, exc_info=True)
        return False

