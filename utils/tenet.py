from __future__ import annotations

import logging
import os
import subprocess
from typing import NamedTuple

from PIL import Image


class Antipode(NamedTuple):
    lat: float
    lon: float


def calculate_antipode(*, lat: float, lon: float) -> Antipode:
    anti_lat = -lat
    anti_lon = lon + 180 if lon <= 0 else lon - 180
    return Antipode(lat=anti_lat, lon=anti_lon)


def mirror_image(*, img_path: str, output_path: str) -> bool:
    try:
        img = Image.open(img_path)
        mirrored = img.transpose(Image.FLIP_LEFT_RIGHT)
        if mirrored.mode == "RGBA":
            mirrored = mirrored.convert("RGB")
        mirrored.save(output_path, "JPEG", quality=95)
        logging.info("Mirrored image saved to %s", output_path)
        return True
    except Exception as e:
        logging.error("Mirror image error: %s", e, exc_info=True)
        return False


def reverse_video(*, vid_path: str, output_path: str, max_duration: int = 30) -> bool:
    """Reverse a video or GIF (play backwards)."""
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            vid_path,
            "-t",
            str(max_duration),
            "-vf",
            "reverse",
            "-af",
            "areverse",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ]
        logging.info("Reversing video: %s", vid_path)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)

        if result.returncode != 0:
            # Retry without audio (some inputs have no audio stream).
            cmd_no_audio = [
                "ffmpeg",
                "-y",
                "-i",
                vid_path,
                "-t",
                str(max_duration),
                "-vf",
                "reverse",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-an",
                "-movflags",
                "+faststart",
                "-pix_fmt",
                "yuv420p",
                output_path,
            ]
            result = subprocess.run(
                cmd_no_audio, capture_output=True, text=True, timeout=300, check=False
            )
            if result.returncode != 0:
                logging.error("FFmpeg reverse error: %s", result.stderr)
                return False

        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except subprocess.TimeoutExpired:
        logging.error("Video reverse timeout")
        return False
    except Exception as e:
        logging.error("Reverse video error: %s", e, exc_info=True)
        return False


def reverse_text(text: str) -> str:
    return text[::-1]


def reverse_audio(*, audio_path: str, output_path: str) -> bool:
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            audio_path,
            "-af",
            "areverse",
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode != 0:
            logging.error("Audio reverse error: %s", result.stderr)
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logging.error("Reverse audio error: %s", e, exc_info=True)
        return False


def reverse_pdf(*, pdf_path: str, output_path: str) -> bool:
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        logging.error("PyPDF2 not installed")
        return False

    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        for page in reversed(reader.pages):
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        logging.info("Reversed PDF: %s pages", len(reader.pages))
        return True
    except Exception as e:
        logging.error("PDF reverse error: %s", e, exc_info=True)
        return False

