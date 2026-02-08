from __future__ import annotations

import logging
import os
import subprocess


def convert_tgs_to_mp4_simple(*, tgs_path: str, output_mp4: str) -> bool:
    """Convert a TGS sticker to a short MP4 using lottie (cairo) + ffmpeg."""
    logging.info("TGS conversion started: %s -> %s", tgs_path, output_mp4)

    try:
        import gzip
        import json
        import shutil
        import tempfile

        from lottie import parsers
        from lottie.exporters.cairo import export_png

        with gzip.open(tgs_path, "rb") as f:
            data = json.load(f)
            anim = parsers.tgs.parse_tgs(data)

        temp_dir = tempfile.mkdtemp(prefix="tgs_frames_")
        try:
            fps = 30
            duration = anim.out_point / anim.frame_rate
            frame_count = int(duration * fps)
            logging.info("Rendering frames: %s (fps=%s, duration=%.2fs)", frame_count, fps, duration)

            # Render up to 3 seconds (90 frames at 30 fps).
            for i in range(min(frame_count, 90)):
                t = (i / fps) * anim.frame_rate
                frame_path = f"{temp_dir}/{i:04d}.png"
                export_png(anim, frame_path, t, 512, 512)

            cmd = [
                "ffmpeg",
                "-y",
                "-framerate",
                str(fps),
                "-i",
                f"{temp_dir}/%04d.png",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-t",
                "3",
                output_mp4,
            ]
            result = subprocess.run(cmd, capture_output=True, check=False)
            if result.returncode != 0:
                logging.error("FFmpeg error: %s", result.stderr.decode(errors="ignore"))
                return False

            return os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 1000
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    except Exception as e:
        logging.error("TGS mp4 error: %s", e, exc_info=True)
        return False

