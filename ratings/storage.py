from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True)
class UserRow:
    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    rating: int


class RatingStorage:
    def __init__(self, *, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    rating INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_votes_triplet
                ON votes(chat_id, from_user_id, to_user_id, ts)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_votes_from_user
                ON votes(from_user_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_votes_to_user
                ON votes(to_user_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    last_ts INTEGER NOT NULL,
                    PRIMARY KEY(chat_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    type TEXT,
                    title TEXT,
                    username TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def upsert_user(
        self,
        *,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        now_ts: int | None = None,
    ) -> None:
        now_ts = int(time.time()) if now_ts is None else now_ts
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, username, first_name, last_name, rating, created_at, updated_at)
                VALUES(?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    updated_at=excluded.updated_at
                """,
                (user_id, username, first_name, last_name, now_ts, now_ts),
            )

    def add_points(self, *, user_id: int, delta: int, now_ts: int | None = None) -> tuple[int, bool, str | None]:
        """Return (new_rating, was_reset, reset_msg)."""
        now_ts = int(time.time()) if now_ts is None else now_ts
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET rating = rating + ?, updated_at=? WHERE user_id=?",
                (delta, now_ts, user_id),
            )
            row = conn.execute("SELECT rating FROM users WHERE user_id=?", (user_id,)).fetchone()
            rating = int(row["rating"]) if row else 0
            # 2 000 000 — полное обнуление
            if rating >= 2_000_000:
                conn.execute("UPDATE users SET rating = 0, updated_at=? WHERE user_id=?", (now_ts, user_id))
                return 0, True, "💀 ПОЛНОЕ ОБНУЛЕНИЕ! 2 000 000 достигнут!"
            # 1 500 000 (±10000) — откат на 750k
            if 1_490_000 <= rating <= 1_510_000:
                new_r = rating - 750_000
                conn.execute("UPDATE users SET rating = ?, updated_at=? WHERE user_id=?", (new_r, now_ts, user_id))
                return new_r, True, f"⚠️ ЧАСТИЧНОЕ ОБНУЛЕНИЕ! 1.5M зона — откат на 750k!"
            # 1 000 000 (±10000) — откат на 500k
            if 990_000 <= rating <= 1_010_000:
                new_r = rating - 500_000
                conn.execute("UPDATE users SET rating = ?, updated_at=? WHERE user_id=?", (new_r, now_ts, user_id))
                return new_r, True, f"⚠️ ЧАСТИЧНОЕ ОБНУЛЕНИЕ! 1M зона — откат на 500k!"
            return rating, False, None

    def get_user(self, *, user_id: int) -> UserRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, username, first_name, last_name, rating FROM users WHERE user_id=?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return UserRow(
                user_id=int(row["user_id"]),
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                rating=int(row["rating"]),
            )

    def top(self, *, limit: int) -> list[UserRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, first_name, last_name, rating
                FROM users
                ORDER BY rating DESC, updated_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            UserRow(
                user_id=int(r["user_id"]),
                username=r["username"],
                first_name=r["first_name"],
                last_name=r["last_name"],
                rating=int(r["rating"]),
            )
            for r in rows
        ]

    def top_by_chat(self, *, chat_id: int, limit: int) -> list[UserRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.user_id, u.username, u.first_name, u.last_name, u.rating
                FROM users u
                WHERE u.user_id IN (
                    SELECT from_user_id FROM votes WHERE chat_id = ?
                    UNION
                    SELECT to_user_id FROM votes WHERE chat_id = ?
                    UNION
                    SELECT user_id FROM activity WHERE chat_id = ?
                )
                ORDER BY u.rating DESC, u.updated_at ASC
                LIMIT ?
                """,
                (chat_id, chat_id, chat_id, limit),
            ).fetchall()
        return [
            UserRow(user_id=int(r["user_id"]), username=r["username"], first_name=r["first_name"], last_name=r["last_name"], rating=int(r["rating"]))
            for r in rows
        ]

    def user_count_by_chat(self, *, chat_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT uid) AS c FROM (
                    SELECT from_user_id AS uid FROM votes WHERE chat_id = ?
                    UNION
                    SELECT to_user_id AS uid FROM votes WHERE chat_id = ?
                    UNION
                    SELECT user_id AS uid FROM activity WHERE chat_id = ?
                )
                """,
                (chat_id, chat_id, chat_id),
            ).fetchone()
            return int(row["c"]) if row else 0

    def get_user_rating(self, *, user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT rating FROM users WHERE user_id=?", (user_id,)).fetchone()
            return int(row["rating"]) if row else 0

    def get_random_user(self, *, exclude_id: int | None = None) -> UserRow | None:
        with self._connect() as conn:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT user_id, username, first_name, last_name, rating FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT 1",
                    (exclude_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT user_id, username, first_name, last_name, rating FROM users ORDER BY RANDOM() LIMIT 1",
                ).fetchone()
            if not row:
                return None
            return UserRow(user_id=int(row["user_id"]), username=row["username"], first_name=row["first_name"], last_name=row["last_name"], rating=int(row["rating"]))

    def halve_all_ratings(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET rating = rating / 2 WHERE rating != 0")
            return cur.rowcount

    def double_all_ratings(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET rating = rating * 2 WHERE rating != 0")
            return cur.rowcount

    def reset_negative_ratings(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET rating = 0 WHERE rating < 0")
            return cur.rowcount

    def add_flat_to_all(self, *, delta: int) -> int:
        with self._connect() as conn:
            cur = conn.execute("UPDATE users SET rating = rating + ?", (delta,))
            return cur.rowcount

    def set_rating(self, *, user_id: int, rating: int) -> None:
        now_ts = int(time.time())
        with self._connect() as conn:
            conn.execute("UPDATE users SET rating = ?, updated_at = ? WHERE user_id = ?", (rating, now_ts, user_id))

    def get_bottom_users(self, *, limit: int = 1) -> list[UserRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id, username, first_name, last_name, rating FROM users ORDER BY rating ASC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [UserRow(user_id=int(r["user_id"]), username=r["username"], first_name=r["first_name"], last_name=r["last_name"], rating=int(r["rating"])) for r in rows]

    def get_random_users(self, *, count: int, exclude_id: int | None = None) -> list[UserRow]:
        with self._connect() as conn:
            if exclude_id is not None:
                rows = conn.execute(
                    "SELECT user_id, username, first_name, last_name, rating FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT ?",
                    (exclude_id, count),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT user_id, username, first_name, last_name, rating FROM users ORDER BY RANDOM() LIMIT ?",
                    (count,),
                ).fetchall()
        return [UserRow(user_id=int(r["user_id"]), username=r["username"], first_name=r["first_name"], last_name=r["last_name"], rating=int(r["rating"])) for r in rows]

    def get_nearest_rating_user(self, *, rating: int, exclude_id: int) -> UserRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, username, first_name, last_name, rating FROM users WHERE user_id != ? ORDER BY ABS(rating - ?) ASC LIMIT 1",
                (exclude_id, rating),
            ).fetchone()
            if not row:
                return None
            return UserRow(user_id=int(row["user_id"]), username=row["username"], first_name=row["first_name"], last_name=row["last_name"], rating=int(row["rating"]))

    def get_average_rating(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(AVG(rating), 0) AS avg_r FROM users").fetchone()
            return int(row["avg_r"])

    def get_user_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(1) AS c FROM users").fetchone()
            return int(row["c"])

    def swap_ratings(self, *, uid1: int, uid2: int) -> None:
        now_ts = int(time.time())
        with self._connect() as conn:
            r1 = conn.execute("SELECT rating FROM users WHERE user_id=?", (uid1,)).fetchone()
            r2 = conn.execute("SELECT rating FROM users WHERE user_id=?", (uid2,)).fetchone()
            if r1 and r2:
                conn.execute("UPDATE users SET rating=?, updated_at=? WHERE user_id=?", (int(r2["rating"]), now_ts, uid1))
                conn.execute("UPDATE users SET rating=?, updated_at=? WHERE user_id=?", (int(r1["rating"]), now_ts, uid2))

    def last_vote_ts(self, *, chat_id: int, from_user_id: int, to_user_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(ts) AS ts
                FROM votes
                WHERE chat_id=? AND from_user_id=? AND to_user_id=?
                """,
                (chat_id, from_user_id, to_user_id),
            ).fetchone()
            ts = row["ts"] if row else None
            return int(ts) if ts is not None else None

    def record_vote(self, *, chat_id: int, from_user_id: int, to_user_id: int, ts: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO votes(chat_id, from_user_id, to_user_id, ts) VALUES(?, ?, ?, ?)",
                (chat_id, from_user_id, to_user_id, ts),
            )

    def vote_counts(self, *, user_id: int) -> tuple[int, int]:
        """Return (given, received) counts for /plus votes."""
        with self._connect() as conn:
            given = conn.execute(
                "SELECT COUNT(1) AS c FROM votes WHERE from_user_id=?",
                (user_id,),
            ).fetchone()["c"]
            received = conn.execute(
                "SELECT COUNT(1) AS c FROM votes WHERE to_user_id=?",
                (user_id,),
            ).fetchone()["c"]
            return int(given or 0), int(received or 0)

    def last_activity_ts(self, *, chat_id: int, user_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_ts FROM activity WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            if not row:
                return None
            return int(row["last_ts"])

    def record_activity(self, *, chat_id: int, user_id: int, ts: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity(chat_id, user_id, last_ts)
                VALUES(?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET last_ts=excluded.last_ts
                """,
                (chat_id, user_id, ts),
            )

    def upsert_chat(
        self,
        *,
        chat_id: int,
        chat_type: str | None,
        title: str | None,
        username: str | None,
        now_ts: int | None = None,
    ) -> None:
        now_ts = int(time.time()) if now_ts is None else now_ts
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats(chat_id, type, title, username, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    type=excluded.type,
                    title=excluded.title,
                    username=excluded.username,
                    updated_at=excluded.updated_at
                """,
                (chat_id, chat_type, title, username, now_ts, now_ts),
            )

    def list_chat_ids(self) -> list[int]:
        with self._connect() as conn:
            try:
                rows = conn.execute("SELECT chat_id FROM chats ORDER BY chat_id").fetchall()
                if rows:
                    return [int(r["chat_id"]) for r in rows]
            except sqlite3.OperationalError:
                # Older DB without the chats table.
                rows = []

            rows = conn.execute(
                """
                SELECT DISTINCT chat_id
                FROM votes
                UNION
                SELECT DISTINCT chat_id
                FROM activity
                ORDER BY chat_id
                """
            ).fetchall()
            return [int(r["chat_id"]) for r in rows]
