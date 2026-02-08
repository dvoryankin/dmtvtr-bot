from __future__ import annotations

import logging
import os
import subprocess

from PIL import Image

from demotivator.layout import LayoutConfig, build_layout_params


def extract_first_frame(*, video_path: str, output_jpg: str) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vframes",
        "1",
        "-q:v",
        "2",
        output_jpg,
    ]
    subprocess.run(cmd, capture_output=True, check=False)
    return os.path.exists(output_jpg) and os.path.getsize(output_jpg) > 0


def create_demotivator_video(
    *,
    vid_path: str,
    text: str,
    output_path: str,
    layout_cfg: LayoutConfig,
    max_duration_seconds: int = 30,
) -> bool:
    """Create a demotivator video with a static background and overlayed input video."""
    frame_path = vid_path + ".jpg"
    bg_path = vid_path + "_bg.png"

    try:
        logging.info("Video demotivator: input=%s output=%s", vid_path, output_path)

        if not extract_first_frame(video_path=vid_path, output_jpg=frame_path):
            logging.error("Failed to extract first frame")
            return False

        frame = Image.open(frame_path)
        w, h = frame.size
        logging.info("Video dimensions: %sx%s", w, h)

        bg, t_w, t_h, p_x, p_y = build_layout_params(
            base_w=w,
            base_h=h,
            text=text,
            for_video=True,
            cfg=layout_cfg,
        )
        bg.save(bg_path)

        filter_complex = f"[1:v]scale={t_w}:{t_h}[vid];[0:v][vid]overlay={p_x}:{p_y}:shortest=1"

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            bg_path,
            "-i",
            vid_path,
            "-filter_complex",
            filter_complex,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(max_duration_seconds),
            output_path,
        ]

        logging.info("Starting ffmpeg: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            logging.error("FFmpeg failed (%s): %s", result.returncode, result.stderr.decode(errors="ignore"))
            return False

        if not os.path.exists(output_path):
            logging.error("Output file not created")
            return False

        size = os.path.getsize(output_path)
        logging.info("Output created: %s (%s bytes)", output_path, size)
        return size > 1000

    except Exception as e:
        logging.error("Video demotivator error: %s", e, exc_info=True)
        return False
    finally:
        for f in (frame_path, bg_path):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

