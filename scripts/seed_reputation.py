from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from config.config import Settings
from utils.logging_setup import configure_logging


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return conn


def seed_reputation(
    *,
    db_path: Path,
    min_rating: int,
    max_rating: int,
    only_zero: bool,
    dry_run: bool,
) -> tuple[int, int]:
    rng = random.Random()
    now_ts = int(time.time())

    with _connect(db_path) as conn:
        if only_zero:
            rows = conn.execute("SELECT user_id FROM users WHERE rating=0").fetchall()
        else:
            rows = conn.execute("SELECT user_id FROM users").fetchall()

        candidates = len(rows)
        if candidates == 0:
            return 0, 0

        updated = 0
        for r in rows:
            user_id = int(r["user_id"])
            target = rng.randint(min_rating, max_rating)
            if dry_run:
                updated += 1
                continue
            conn.execute(
                "UPDATE users SET rating=?, updated_at=? WHERE user_id=?",
                (target, now_ts, user_id),
            )
            updated += 1

        return updated, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed random reputation for users in ratings.sqlite3")
    parser.add_argument("--min", dest="min_rating", type=int, default=1, help="Minimum rating (default: 1)")
    parser.add_argument("--max", dest="max_rating", type=int, default=249, help="Maximum rating (default: 249)")
    parser.add_argument("--all", action="store_true", help="Seed all users (not only users with rating=0)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB, only count")
    args = parser.parse_args()

    if args.min_rating < 0 or args.max_rating < 0 or args.min_rating > args.max_rating:
        raise SystemExit("Invalid range: require 0 <= min <= max")

    load_dotenv()
    base_dir = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(base_dir=base_dir)
    configure_logging(log_file=settings.log_file)

    db_path = settings.rating_db_path
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    updated, candidates = seed_reputation(
        db_path=db_path,
        min_rating=int(args.min_rating),
        max_rating=int(args.max_rating),
        only_zero=not bool(args.all),
        dry_run=bool(args.dry_run),
    )

    scope = "rating=0" if not args.all else "all"
    logging.info("Seeded users: updated=%s, candidates=%s (scope=%s, range=%s..%s, dry_run=%s)", updated, candidates, scope, args.min_rating, args.max_rating, args.dry_run)


if __name__ == "__main__":
    main()

