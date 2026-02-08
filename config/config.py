from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an int, got: {raw!r}") from e


@dataclass(frozen=True, slots=True)
class Settings:
    token: str
    groq_api_key: str

    base_dir: Path
    log_file: Path

    fallback_avatar: Path
    overload_image_light: Path
    overload_image_heavy: Path
    max_concurrent_processes: int

    rating_db_path: Path
    vote_cooldown_seconds: int

    font_paths: tuple[str, ...]
    unicode_font_paths: tuple[str, ...]

    @classmethod
    def from_env(cls, *, base_dir: Path) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

        max_concurrent_processes = _env_int("MAX_CONCURRENT_PROCESSES", 2)
        vote_cooldown_seconds = _env_int("VOTE_COOLDOWN_SECONDS", 12 * 60 * 60)

        rating_db_path = Path(os.getenv("RATING_DB_PATH", str(base_dir / "ratings.sqlite3")))

        font_paths = (
            str(base_dir / "times.ttf"),
            "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        )

        unicode_font_paths = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        )

        return cls(
            token=token,
            groq_api_key=groq_api_key,
            base_dir=base_dir,
            log_file=base_dir / "bot.log",
            fallback_avatar=base_dir / "123.png",
            overload_image_light=base_dir / "2.jpg",
            overload_image_heavy=base_dir / "3.png",
            max_concurrent_processes=max_concurrent_processes,
            rating_db_path=rating_db_path,
            vote_cooldown_seconds=vote_cooldown_seconds,
            font_paths=font_paths,
            unicode_font_paths=unicode_font_paths,
        )

