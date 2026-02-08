from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from dotenv import load_dotenv

from config.config import Settings
from ratings.badges import badge_for_rating
from ratings.service import RatingService
from utils.logging_setup import configure_logging


def _truncate_title(title: str, *, limit: int = 16) -> str:
    # Telegram custom admin titles are limited to 16 characters.
    normalized = " ".join((title or "").split())
    return normalized[:limit]


async def _set_admin_title(
    bot: Bot,
    *,
    chat_id: int,
    user_id: int,
    title_with_emoji: str,
    title_plain: str,
    dry_run: bool,
) -> tuple[bool, str | None]:
    title_with_emoji = _truncate_title(title_with_emoji)
    title_plain = _truncate_title(title_plain)

    if dry_run:
        logging.info("DRY RUN: set title chat=%s user=%s title=%r", chat_id, user_id, title_with_emoji)
        return True, None

    try:
        ok = await bot.set_chat_administrator_custom_title(
            chat_id=chat_id,
            user_id=user_id,
            custom_title=title_with_emoji,
        )
        return ok, None if ok else "Telegram вернул False"
    except TelegramForbiddenError:
        return False, "forbidden (нужны права can_promote_members)"
    except TelegramBadRequest as e:
        msg = (e.message or "").strip()
        if "ADMIN_RANK_EMOJI_NOT_ALLOWED" in msg.upper():
            try:
                ok = await bot.set_chat_administrator_custom_title(
                    chat_id=chat_id,
                    user_id=user_id,
                    custom_title=title_plain,
                )
                return ok, None if ok else "Telegram вернул False"
            except TelegramBadRequest as e2:
                msg2 = (e2.message or "").strip()
                return False, msg2 or type(e2).__name__
            except TelegramForbiddenError:
                return False, "forbidden (нужны права can_promote_members)"
            except TelegramAPIError:
                return False, "Telegram API error"

        return False, msg or type(e).__name__
    except TelegramAPIError:
        return False, "Telegram API error"


async def _sync_chat_titles(
    bot: Bot,
    *,
    rating: RatingService,
    chat_id: int,
    dry_run: bool,
) -> None:
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError as e:
        logging.warning("Chat %s: cannot fetch chat: %s", chat_id, type(e).__name__)
        return

    if chat.type != "supergroup":
        logging.info("Chat %s: skip (type=%s)", chat_id, chat.type)
        return

    me = await bot.me()
    try:
        my_cm = await bot.get_chat_member(chat_id, me.id)
    except TelegramAPIError as e:
        logging.warning("Chat %s: cannot fetch bot member: %s", chat_id, type(e).__name__)
        return

    if my_cm.status not in {"administrator", "creator"}:
        logging.info("Chat %s: skip (bot is not admin)", chat_id)
        return
    if my_cm.status == "administrator" and not getattr(my_cm, "can_promote_members", False):
        logging.info("Chat %s: skip (bot has no can_promote_members)", chat_id)
        return

    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramAPIError as e:
        logging.warning("Chat %s: cannot list admins: %s", chat_id, type(e).__name__)
        return

    ok_count = 0
    skipped_creator = 0
    skipped_not_editable = 0
    skipped_bots = 0
    fail_count = 0

    for cm in admins:
        u = cm.user
        if u.is_bot:
            skipped_bots += 1
            continue
        if cm.status == "creator":
            skipped_creator += 1
            continue
        if cm.status == "administrator" and not getattr(cm, "can_be_edited", False):
            skipped_not_editable += 1
            continue

        try:
            p = await rating.profile(user=u)
        except Exception:
            logging.exception("Chat %s: failed to load profile for user %s", chat_id, u.id)
            fail_count += 1
            continue

        badge = badge_for_rating(p.rating, kpd_percent=p.kpd_percent)
        ok, err = await _set_admin_title(
            bot,
            chat_id=chat_id,
            user_id=u.id,
            title_with_emoji=f"{badge.icon} {badge.name}",
            title_plain=badge.name,
            dry_run=dry_run,
        )
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            logging.info("Chat %s: title set failed for user %s: %s", chat_id, u.id, err)

    logging.info(
        "Chat %s: done. ok=%s, skipped_creator=%s, skipped_not_editable=%s, skipped_bots=%s, failed=%s",
        chat_id,
        ok_count,
        skipped_creator,
        skipped_not_editable,
        skipped_bots,
        fail_count,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sync admin titles to rating badges.")
    parser.add_argument("--chat-id", type=int, default=None, help="Sync only this chat id")
    parser.add_argument("--dry-run", action="store_true", help="Do not change titles, only log actions")
    args = parser.parse_args()

    load_dotenv()
    base_dir = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(base_dir=base_dir)
    configure_logging(log_file=settings.log_file)

    if not settings.token:
        raise RuntimeError("BOT_TOKEN is not set (check .env)")

    rating = RatingService(
        db_path=settings.rating_db_path,
        vote_cooldown_seconds=settings.vote_cooldown_seconds,
        activity_points_per_award=settings.activity_points_per_award,
        activity_cooldown_seconds=settings.activity_cooldown_seconds,
    )
    rating.init_db()

    bot = Bot(token=settings.token)
    try:
        if args.chat_id is not None:
            await _sync_chat_titles(bot, rating=rating, chat_id=args.chat_id, dry_run=bool(args.dry_run))
            return

        chat_ids = await rating.list_chat_ids()
        if not chat_ids:
            logging.info("No chats found in DB (votes/activity tables are empty). Nothing to sync.")
            return

        for chat_id in chat_ids:
            await _sync_chat_titles(bot, rating=rating, chat_id=int(chat_id), dry_run=bool(args.dry_run))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
