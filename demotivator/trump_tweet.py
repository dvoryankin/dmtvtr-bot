from __future__ import annotations

import logging
import os

from aiogram import Bot
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji


async def download_user_avatar(*, bot: Bot, user_id: int, output_path: str) -> bool:
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            await bot.download(photos.photos[0][-1], destination=output_path)
            return True
        return False
    except Exception as e:
        logging.error("Failed to download avatar: %s", e, exc_info=True)
        return False


def create_trump_tweet_image(*, text: str, output_path: str, avatar_path: str | None = None) -> bool:
    """Render a twitter-like card."""
    try:
        logging.info("Creating Trump tweet image: %s", output_path)

        try:
            font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_username = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
        except Exception:
            font_name = ImageFont.load_default()
            font_username = ImageFont.load_default()
            font_text = ImageFont.load_default()

        max_width = 520
        words = text.split()
        lines: list[str] = []
        current_line: list[str] = []

        temp_img = Image.new("RGB", (1, 1))
        with Pilmoji(temp_img) as pilmoji:
            for word in words:
                test_line = " ".join(current_line + [word])
                width, _ = pilmoji.getsize(test_line, font=font_text)
                if width <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                    current_line = [word]

            if current_line:
                lines.append(" ".join(current_line))

        lines = lines[:15]

        header_height = 100
        text_height = len(lines) * 26
        footer_height = 80
        padding = 50

        img_height = header_height + text_height + footer_height + padding
        img_width = 600

        img = Image.new("RGB", (img_width, img_height), color="#15202b")

        tweet_height = img_height - 50
        tweet_box = Image.new("RGB", (560, tweet_height), color="white")
        img.paste(tweet_box, (20, 25))

        draw = ImageDraw.Draw(img)

        avatar_size = 48
        avatar_x, avatar_y = 40, 45

        if avatar_path and os.path.exists(avatar_path):
            try:
                avatar_img = Image.open(avatar_path).convert("RGB")
                avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

                mask = Image.new("L", (avatar_size, avatar_size), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)

                img.paste(avatar_img, (avatar_x, avatar_y), mask)
            except Exception as e:
                logging.error("Avatar error: %s", e, exc_info=True)
                draw.ellipse(
                    [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
                    fill="#1d9bf0",
                )
        else:
            draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill="#1d9bf0")

        draw.text((100, 50), "Donald J. Trump", font=font_name, fill="#0f1419")

        check_x, check_y = 270, 52
        draw.ellipse([check_x, check_y, check_x + 16, check_y + 16], fill="#1d9bf0")
        draw.text((check_x + 3, check_y - 1), "✓", font=font_username, fill="white")

        draw.text((100, 72), "@realDonaldTrump", font=font_username, fill="#536471")

        y_pos = 115
        with Pilmoji(img) as pilmoji:
            for line in lines:
                pilmoji.text((40, y_pos), line, font=font_text, fill="#0f1419")
                y_pos += 26

        draw.text((40, y_pos + 20), "just now", font=font_username, fill="#536471")

        icons_y = img_height - 45
        icon_color = "#536471"
        icon_size = 18

        x1 = 50
        draw.ellipse([x1, icons_y, x1 + icon_size, icons_y + icon_size], outline=icon_color, width=2)
        draw.polygon([(x1 + 3, icons_y + icon_size), (x1 + 3, icons_y + icon_size + 4), (x1 + 7, icons_y + icon_size)], fill=icon_color)

        x2 = 140
        draw.line([(x2, icons_y + 6), (x2 + 14, icons_y + 6)], fill=icon_color, width=2)
        draw.polygon([(x2 + 14, icons_y + 3), (x2 + 18, icons_y + 6), (x2 + 14, icons_y + 9)], fill=icon_color)
        draw.line([(x2, icons_y + 12), (x2 + 14, icons_y + 12)], fill=icon_color, width=2)
        draw.polygon([(x2, icons_y + 9), (x2 - 4, icons_y + 12), (x2, icons_y + 15)], fill=icon_color)

        x3 = 230
        draw.ellipse([x3, icons_y + 2, x3 + 7, icons_y + 9], outline=icon_color, width=2)
        draw.ellipse([x3 + 7, icons_y + 2, x3 + 14, icons_y + 9], outline=icon_color, width=2)
        draw.polygon([(x3, icons_y + 7), (x3 + 14, icons_y + 7), (x3 + 7, icons_y + 16)], outline=icon_color, width=2)

        x4 = 320
        draw.rectangle([x4 + 3, icons_y + 8, x4 + 13, icons_y + 16], outline=icon_color, width=2)
        draw.line([(x4 + 8, icons_y + 8), (x4 + 8, icons_y + 2)], fill=icon_color, width=2)
        draw.polygon([(x4 + 5, icons_y + 4), (x4 + 8, icons_y), (x4 + 11, icons_y + 4)], fill=icon_color)

        x5 = 410
        draw.rectangle([x5, icons_y + 2, x5 + 12, icons_y + 18], outline=icon_color, width=2)
        draw.polygon([(x5, icons_y + 18), (x5 + 6, icons_y + 14), (x5 + 12, icons_y + 18)], fill=icon_color)

        img.save(output_path)
        return os.path.exists(output_path)

    except Exception as e:
        logging.error("Tweet image error: %s", e, exc_info=True)
        return False
