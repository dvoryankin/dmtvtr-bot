from __future__ import annotations

import logging
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageOps


def apply_invert(*, img_path: str, output_path: str) -> bool:
    try:
        img = Image.open(img_path)
        if img.mode == "RGBA":
            r, g, b, a = img.split()
            rgb = Image.merge("RGB", (r, g, b))
            rgb = ImageOps.invert(rgb)
            r2, g2, b2 = rgb.split()
            img = Image.merge("RGBA", (r2, g2, b2, a))
        else:
            img = img.convert("RGB")
            img = ImageOps.invert(img)

        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error("Invert error: %s", e, exc_info=True)
        return False


def apply_vintage(*, img_path: str, output_path: str) -> bool:
    """Sepia + noise + vignette."""
    try:
        img = Image.open(img_path).convert("RGB")
        width, height = img.size

        sepia_matrix = (
            0.393,
            0.769,
            0.189,
            0,
            0.349,
            0.686,
            0.168,
            0,
            0.272,
            0.534,
            0.131,
            0,
        )
        img = img.convert("RGB", sepia_matrix)

        img = ImageEnhance.Contrast(img).enhance(0.8)
        img = ImageEnhance.Color(img).enhance(0.6)

        pixels = img.load()
        for i in range(0, width, 3):
            for j in range(0, height, 3):
                noise = random.randint(-15, 15)
                r, g, b = pixels[i, j]
                pixels[i, j] = (
                    max(0, min(255, r + noise)),
                    max(0, min(255, g + noise)),
                    max(0, min(255, b + noise)),
                )

        vignette = Image.new("L", (width, height), 0)
        vignette_draw = ImageDraw.Draw(vignette)
        for i in range(min(width, height) // 2):
            darkness = int(255 * (i / (min(width, height) / 2)))
            vignette_draw.rectangle([i, i, width - i, height - i], outline=darkness)

        img = Image.composite(img, Image.new("RGB", img.size, (40, 30, 20)), vignette)

        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error("Vintage error: %s", e, exc_info=True)
        return False

