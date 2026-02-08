from __future__ import annotations

import logging
import os
import time


def cleanup_old_temp_files(*, prefix: str = "temp_", max_age_seconds: int = 3600) -> None:
    """Remove temp files in current working directory that are older than max_age_seconds."""
    try:
        current_time = time.time()
        removed = 0

        for filename in os.listdir("."):
            if not filename.startswith(prefix):
                continue
            filepath = os.path.join(".", filename)
            try:
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    removed += 1
            except Exception:
                continue

        if removed:
            logging.info("Cleaned up %s old temp files", removed)
    except Exception as e:
        logging.error("Cleanup error: %s", e, exc_info=True)

