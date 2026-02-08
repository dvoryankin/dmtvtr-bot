from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from aiogram.types import User

from ratings.badges import badge_for_rating, next_badge
from ratings.storage import RatingStorage, UserRow
from utils.asyncio_utils import run_in_thread


@dataclass(frozen=True)
class Profile:
    user_id: int
    display_name: str
    rating: int
    badge: str
    kpd_percent: int
    next_badge_hint: str | None


def _display_name_from_row(row: UserRow) -> str:
    if row.username:
        return f"@{row.username}"
    parts = [p for p in (row.first_name, row.last_name) if p]
    return " ".join(parts) if parts else str(row.user_id)


class RatingService:
    def __init__(
        self,
        *,
        db_path: Path,
        vote_cooldown_seconds: int,
        activity_points_per_award: int,
        activity_cooldown_seconds: int,
    ) -> None:
        self._storage = RatingStorage(db_path=db_path)
        self._vote_cooldown_seconds = vote_cooldown_seconds
        self._activity_points_per_award = activity_points_per_award
        self._activity_cooldown_seconds = activity_cooldown_seconds

    def init_db(self) -> None:
        self._storage.init_db()

    async def list_chat_ids(self) -> list[int]:
        return await run_in_thread(self._storage.list_chat_ids)

    async def touch_chat(
        self,
        *,
        chat_id: int,
        chat_type: str | None,
        title: str | None,
        username: str | None,
    ) -> None:
        await run_in_thread(
            self._storage.upsert_chat,
            chat_id=chat_id,
            chat_type=chat_type,
            title=title,
            username=username,
        )

    async def touch_user(self, user: User) -> None:
        await run_in_thread(
            self._storage.upsert_user,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

    async def add_points(self, *, user: User, delta: int) -> int:
        await self.touch_user(user)
        return await run_in_thread(self._storage.add_points, user_id=user.id, delta=delta)

    async def kpd_percent(self, *, user_id: int) -> int:
        """A simplified КПД metric based on /plus votes only.

        КПД = received / (received + given) * 100
        """
        given, received = await run_in_thread(self._storage.vote_counts, user_id=user_id)
        total = given + received
        if total <= 0:
            return 0
        return int(received * 100 / total)

    async def profile(self, *, user: User) -> Profile:
        await self.touch_user(user)
        row = await run_in_thread(self._storage.get_user, user_id=user.id)
        rating = row.rating if row else 0

        kpd = await self.kpd_percent(user_id=user.id)
        badge = badge_for_rating(rating, kpd_percent=kpd)
        nxt = next_badge(rating)
        hint = None
        if nxt is not None:
            hint = f"До лычки {nxt.icon} {nxt.name}: {nxt.threshold - rating}"

        display_name = _display_name_from_row(row) if row else (f"@{user.username}" if user.username else user.full_name)
        return Profile(
            user_id=user.id,
            display_name=display_name,
            rating=rating,
            badge=f"{badge.icon} {badge.name}",
            kpd_percent=kpd,
            next_badge_hint=hint,
        )

    async def top(self, *, limit: int = 10) -> list[Profile]:
        rows = await run_in_thread(self._storage.top, limit=limit)
        out: list[Profile] = []
        for r in rows:
            kpd = await self.kpd_percent(user_id=r.user_id)
            b = badge_for_rating(r.rating, kpd_percent=kpd)
            out.append(
                Profile(
                    user_id=r.user_id,
                    display_name=_display_name_from_row(r),
                    rating=r.rating,
                    badge=f"{b.icon} {b.name}",
                    kpd_percent=kpd,
                    next_badge_hint=None,
                )
            )
        return out

    async def can_vote(self, *, chat_id: int, from_user_id: int, to_user_id: int) -> tuple[bool, int]:
        now_ts = int(time.time())
        last_ts = await run_in_thread(
            self._storage.last_vote_ts,
            chat_id=chat_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )
        if last_ts is None:
            return True, 0

        elapsed = now_ts - last_ts
        if elapsed >= self._vote_cooldown_seconds:
            return True, 0
        return False, self._vote_cooldown_seconds - elapsed

    async def vote_plus_one(
        self,
        *,
        chat_id: int,
        from_user: User,
        to_user: User,
    ) -> tuple[bool, int | None, int | None]:
        """Return (ok, new_rating, retry_after_seconds)."""
        if from_user.id == to_user.id:
            return False, None, None

        ok, retry_after = await self.can_vote(
            chat_id=chat_id, from_user_id=from_user.id, to_user_id=to_user.id
        )
        if not ok:
            return False, None, retry_after

        await self.touch_user(from_user)
        await self.touch_user(to_user)

        now_ts = int(time.time())
        await run_in_thread(
            self._storage.record_vote,
            chat_id=chat_id,
            from_user_id=from_user.id,
            to_user_id=to_user.id,
            ts=now_ts,
        )
        new_rating = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=1)
        return True, new_rating, None

    async def can_award_activity(self, *, chat_id: int, user_id: int) -> tuple[bool, int]:
        if self._activity_points_per_award <= 0:
            return False, 0

        now_ts = int(time.time())
        last_ts = await run_in_thread(
            self._storage.last_activity_ts,
            chat_id=chat_id,
            user_id=user_id,
        )
        if last_ts is None:
            return True, 0

        elapsed = now_ts - last_ts
        if elapsed >= self._activity_cooldown_seconds:
            return True, 0
        return False, self._activity_cooldown_seconds - elapsed

    async def award_activity(self, *, chat_id: int, user: User) -> tuple[bool, int | None, int | None, bool]:
        """Return (awarded, new_rating, retry_after_seconds, badge_changed)."""
        if self._activity_points_per_award <= 0:
            return False, None, None, False

        await self.touch_user(user)
        row = await run_in_thread(self._storage.get_user, user_id=user.id)
        old_rating = row.rating if row else 0
        old_badge = badge_for_rating(old_rating)

        ok, retry_after = await self.can_award_activity(chat_id=chat_id, user_id=user.id)
        if not ok:
            return False, None, retry_after, False

        now_ts = int(time.time())
        await run_in_thread(
            self._storage.record_activity,
            chat_id=chat_id,
            user_id=user.id,
            ts=now_ts,
        )
        new_rating = await run_in_thread(
            self._storage.add_points,
            user_id=user.id,
            delta=self._activity_points_per_award,
        )
        new_badge = badge_for_rating(new_rating)
        badge_changed = (new_badge.threshold != old_badge.threshold)
        return True, new_rating, None, badge_changed
