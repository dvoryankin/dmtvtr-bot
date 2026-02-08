from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True, slots=True)
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
                CREATE TABLE IF NOT EXISTS activity (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    last_ts INTEGER NOT NULL,
                    PRIMARY KEY(chat_id, user_id)
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

    def add_points(self, *, user_id: int, delta: int, now_ts: int | None = None) -> int:
        now_ts = int(time.time()) if now_ts is None else now_ts
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET rating = rating + ?, updated_at=? WHERE user_id=?",
                (delta, now_ts, user_id),
            )
            row = conn.execute("SELECT rating FROM users WHERE user_id=?", (user_id,)).fetchone()
            return int(row["rating"]) if row else 0

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
