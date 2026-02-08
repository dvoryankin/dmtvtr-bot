from __future__ import annotations

from pathlib import Path
import logging


def configure_logging(*, log_file: Path, level: int = logging.INFO) -> None:
    # basicConfig is a no-op if handlers already exist; keep it simple and explicit.
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

