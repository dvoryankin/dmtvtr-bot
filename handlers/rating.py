from __future__ import annotations

import logging
import random

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import Message, User

from app.context import AppContext
from ratings.badges import BADGES, badge_for_rating


router = Router(name="rating")


def _format_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


def _badges_help() -> str:
    return (
        "Звания (как в Ответах Mail.ru):\n"
        "- Новичок: <1\n"
        "- Ученик: 1–249\n"
        "- Знаток: 250–499\n"
        "- Профи: 500–999\n"
        "- Мастер: 1000–2499\n"
        "- Гуру: 2500–4999\n"
        "- Мыслитель: 5000–9999\n"
        "- Мудрец: 10000–19999\n"
        "- Просветленный: 20000–49999\n"
        "- 50000–99999:\n"
        "  - Гений (КПД >= 25%)\n"
        "  - Оракул (КПД < 25%)\n"
        "- 100000+:\n"
        "  - Высший разум (КПД >= 30%)\n"
        "  - Искусственный интеллект (КПД < 30%)\n\n"
        "КПД в боте = получено / (получено + поставлено) * 100% (по /plus)."
    )


def _normalize_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _find_badge_by_name(name: str):
    n = _normalize_name(name)
    for b in BADGES:
        if _normalize_name(b.name) == n:
            return b
    return None


async def _is_admin(bot: Bot, *, chat_id: int, user_id: int) -> bool:
    try:
        cm = await bot.get_chat_member(chat_id, user_id)
        return cm.status in {"administrator", "creator"}
    except Exception:
        return False


async def _can_promote(bot: Bot, *, chat_id: int, user_id: int) -> bool:
    """Whether user can promote admins in this chat (creator or admin with can_promote_members)."""
    try:
        cm = await bot.get_chat_member(chat_id, user_id)
        if cm.status == "creator":
            return True
        if cm.status != "administrator":
            return False
        return bool(getattr(cm, "can_promote_members", False))
    except Exception:
        return False


def _truncate_title(title: str, *, limit: int = 16) -> str:
    # Telegram custom admin titles are limited to 16 characters.
    normalized = " ".join((title or "").split())
    return normalized[:limit]


async def _try_set_admin_title(
    bot: Bot,
    *,
    chat_id: int,
    user_id: int,
    custom_title: str,
    fallback_title: str | None = None,
) -> tuple[bool, str | None]:
    """Try to set Telegram admin custom title; returns (ok, error_text)."""
    custom_title = _truncate_title(custom_title)
    fallback_title = _truncate_title(fallback_title) if fallback_title else None

    try:
        ok = await bot.set_chat_administrator_custom_title(
            chat_id=chat_id, user_id=user_id, custom_title=custom_title
        )
        return ok, None if ok else "Telegram вернул False"
    except TelegramForbiddenError:
        return False, "боту нужны права администратора (can_promote_members), чтобы менять титулы"
    except TelegramBadRequest as e:
        msg = (e.message or "").strip()
        if "ADMIN_RANK_EMOJI_NOT_ALLOWED" in msg.upper():
            if fallback_title and fallback_title != custom_title:
                try:
                    ok = await bot.set_chat_administrator_custom_title(
                        chat_id=chat_id, user_id=user_id, custom_title=fallback_title
                    )
                    return ok, None if ok else "Telegram вернул False"
                except TelegramBadRequest as e2:
                    msg2 = (e2.message or "").strip()
                    return False, f"не получилось: {msg2 or type(e2).__name__}"
                except TelegramForbiddenError:
                    return (
                        False,
                        "боту нужны права администратора (can_promote_members), чтобы менять титулы",
                    )
                except TelegramAPIError:
                    return False, "ошибка Telegram API при установке титула"
            return (
                False,
                "Telegram запретил эмодзи в титуле. Поставь текстовый титул (без эмодзи) или используй /promote "
                "и тогда бот будет ставить титулы без эмодзи автоматически.",
            )
        if "not enough rights to change custom title of the user" in msg.lower():
            return (
                False,
                "не хватает прав, чтобы менять admin title. Нужно: бот = админ в супергруппе + право "
                "'Добавлять админов' (can_promote_members). Также Telegram даёт менять титулы только тем админам, "
                "которых бот может редактировать (can_be_edited=true).",
            )
        return False, f"не получилось: {msg or type(e).__name__}"
    except TelegramAPIError as e:
        return False, f"ошибка Telegram API: {type(e).__name__}"


async def _sync_title_for_user(
    *,
    bot: Bot,
    ctx: AppContext,
    chat_id: int,
    user: User,
) -> tuple[bool, str | None]:
    profile = await ctx.rating.profile(user=user)
    badge = badge_for_rating(profile.rating, kpd_percent=profile.kpd_percent)
    ok, err = await _try_set_admin_title(
        bot,
        chat_id=chat_id,
        user_id=user.id,
        custom_title=f"{badge.icon} {badge.name}",
        fallback_title=badge.name,
    )
    return ok, err


@router.message(Command("profile", "rank", "rating"))
async def cmd_profile(message: Message, ctx: AppContext) -> None:
    if not message.from_user:
        return
    p = await ctx.rating.profile(user=message.from_user)
    lines = [
        f"Профиль: {p.display_name}",
        f"Рейтинг: {p.rating}",
        f"Лычка: {p.badge}",
        f"КПД: {p.kpd_percent}%",
    ]
    if p.next_badge_hint:
        lines.append(p.next_badge_hint)
    await message.answer("\n".join(lines))


@router.message(Command("top", "leaderboard", "toprating", "toprep"))
async def cmd_top(message: Message, ctx: AppContext) -> None:
    limit = 10
    parts = (message.text or "").split()
    if len(parts) >= 2:
        try:
            limit = int(parts[1])
        except ValueError:
            await message.answer("Формат: /top [N], например /top 20")
            return

    limit = max(1, min(limit, 50))

    top = await ctx.rating.top(limit=limit)
    if not top:
        await message.answer("Пока пусто. Начни пользоваться ботом или поставь кому-нибудь /plus.")
        return

    lines = [f"Топ рейтинга (топ {limit}):"]
    for i, p in enumerate(top, start=1):
        lines.append(f"{i}. {p.display_name} — {p.rating} ({p.badge})")
    await message.answer("\n".join(lines))


@router.message(Command("badges", "лычки"))
async def cmd_badges(message: Message) -> None:
    await message.answer(_badges_help())


@router.message(Command("plus", "плюс"))
async def cmd_plus(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь на сообщение человека командой /plus.")
        return

    to_user = message.reply_to_message.from_user
    ok, new_rating, retry_after = await ctx.rating.vote_plus_one(
        chat_id=message.chat.id,
        from_user=message.from_user,
        to_user=to_user,
    )
    if not ok:
        if retry_after is None:
            await message.answer("Нельзя поставить /plus самому себе.")
        else:
            target = f"@{to_user.username}" if to_user.username else to_user.full_name
            await message.answer(
                "Слишком часто: ты уже ставил /plus этому человеку в этом чате.\n"
                f"Кому: {target}\n"
                f"Повторить можно через {_format_seconds(retry_after)}.\n\n"
                "Другие участники могут ставить /plus ему без этого ограничения."
            )
        return

    profile = await ctx.rating.profile(user=to_user)
    await message.answer(f"+1 {profile.display_name} → {new_rating} ({profile.badge})")

    # If this is a supergroup and both are admins, try to reflect badge as Telegram admin title.
    if message.chat.type in {"group", "supergroup"}:
        ok_title, err = await _sync_title_for_user(
            bot=bot, ctx=ctx, chat_id=message.chat.id, user=to_user
        )
        if not ok_title and err:
            logging.info("Title sync failed: %s", err)


@router.message(Command("title", "титул", "лычка"))
async def cmd_title(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return
    if message.chat.type != "supergroup":
        await message.answer("Титулы работают только в супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут менять титулы.")
        return

    target = message.reply_to_message.from_user if (message.reply_to_message and message.reply_to_message.from_user) else message.from_user

    # Preflight: check bot permissions and whether this admin is editable by the bot.
    me = await bot.me()
    my_cm = await bot.get_chat_member(message.chat.id, me.id)
    if my_cm.status not in {"administrator", "creator"}:
        await message.answer("❌ Бот должен быть админом, чтобы ставить титулы.")
        return
    if my_cm.status == "administrator" and not getattr(my_cm, "can_promote_members", False):
        await message.answer("❌ Дай боту право 'Добавлять админов' (can_promote_members) и повтори.")
        return

    t_cm = await bot.get_chat_member(message.chat.id, target.id)
    if t_cm.status == "creator":
        await message.answer("❌ Нельзя менять титул создателя чата через бота.")
        return
    if t_cm.status != "administrator":
        await message.answer("❌ Титул можно поставить только администратору.")
        return
    if not getattr(t_cm, "can_be_edited", False):
        await message.answer(
            "❌ Telegram не даёт боту менять титул этого админа (can_be_edited=false). "
            "Нужно, чтобы админ был назначен через бота, либо ставь титул вручную."
        )
        return

    ok, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=target)
    if ok:
        p = await ctx.rating.profile(user=target)
        await message.answer(f"✅ Титул обновлён: {p.display_name} → {p.badge}")
    else:
        await message.answer(f"❌ Не получилось обновить титул: {err}")


@router.message(Command("synctitles", "sync_titles", "sync_lychki", "синклычки"))
async def cmd_sync_titles(message: Message, bot: Bot, ctx: AppContext) -> None:
    if not message.from_user:
        return
    if message.chat.type != "supergroup":
        await message.answer("Титулы работают только в супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут запускать синхронизацию титулов.")
        return

    me = await bot.me()
    my_cm = await bot.get_chat_member(message.chat.id, me.id)
    if my_cm.status not in {"administrator", "creator"}:
        await message.answer("❌ Бот должен быть админом, чтобы менять титулы.")
        return
    if my_cm.status == "administrator" and not getattr(my_cm, "can_promote_members", False):
        await message.answer("❌ Дай боту право 'Добавлять админов' (can_promote_members), иначе титулы не поменять.")
        return

    admins = await bot.get_chat_administrators(message.chat.id)

    ok_count = 0
    skipped_creator = 0
    skipped_not_editable = 0
    fail: list[str] = []
    for cm in admins:
        u = cm.user
        if u.is_bot and u.id == me.id:
            continue
        if cm.status == "creator":
            skipped_creator += 1
            continue
        if cm.status == "administrator" and not getattr(cm, "can_be_edited", False):
            skipped_not_editable += 1
            continue

        ok, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=u)
        if ok:
            ok_count += 1
        else:
            if err:
                fail.append(f"{u.id}: {err}")

    lines = [f"Готово. Обновлено титулов: {ok_count}."]
    if skipped_creator:
        lines.append(f"Пропущено (создатель): {skipped_creator}.")
    if skipped_not_editable:
        lines.append(
            "Пропущено (Telegram не даёт боту менять титул этих админов, can_be_edited=false): "
            f"{skipped_not_editable}."
        )
        lines.append(
            "Чтобы бот мог менять титулы, админов нужно назначить через бота: "
            "сними админку вручную и выдай заново командой /promote (в ответ на сообщение)."
        )
    if fail:
        lines.append(f"Ошибок: {len(fail)} (первые 5):")
        for x in fail[:5]:
            lines.append(f"- {x}")
    await message.answer("\n".join(lines))


@router.message(Command("award", "выдать"))
async def cmd_award_badge(message: Message, bot: Bot, ctx: AppContext) -> None:
    """Admin helper: bump rating up to a specific badge threshold and sync title."""
    if not message.from_user:
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе/супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут выдавать лычки.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответь на сообщение человека: `/award Мыслитель`.\n\n" + _badges_help(), parse_mode="Markdown")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажи лычку: `/award Мыслитель`.\n\n" + _badges_help(), parse_mode="Markdown")
        return

    badge_name = args[1]
    badge = _find_badge_by_name(badge_name)
    if badge is None:
        await message.answer("Не знаю такую лычку.\n\n" + _badges_help())
        return

    target = message.reply_to_message.from_user
    p_before = await ctx.rating.profile(user=target)
    if p_before.rating < badge.threshold:
        delta = badge.threshold - p_before.rating
        new_rating = await ctx.rating.add_points(user=target, delta=delta)
        logging.info("Awarded %s points to %s (new=%s)", delta, target.id, new_rating)

    p_after = await ctx.rating.profile(user=target)
    ok_title, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=target)
    if ok_title:
        await message.answer(f"✅ Выдано: {p_after.display_name} → {p_after.rating} ({p_after.badge})")
    else:
        await message.answer(
            f"✅ Рейтинг обновлён: {p_after.display_name} → {p_after.rating} ({p_after.badge})\n"
            f"❌ Титул не обновился: {err}"
        )


@router.message(Command("seedrep", "seedrating", "рандомрепа", "рандомрейтинг"))
async def cmd_seed_rep(message: Message, bot: Bot, ctx: AppContext) -> None:
    """One-time helper: seed random starting rating for admins (only for users with 0 rating)."""
    if not message.from_user:
        return
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе/супергруппе.")
        return
    if not await _is_admin(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только админы могут раздавать стартовый рейтинг.")
        return

    # Defaults: first two ranks (Новичок/Ученик) => 1..249
    min_rating = 1
    max_rating = 249

    args = (message.text or "").split()
    if len(args) == 3:
        try:
            min_rating = int(args[1])
            max_rating = int(args[2])
        except ValueError:
            await message.answer("Формат: `/seedrep 1 249` (два числа).", parse_mode="Markdown")
            return

    if min_rating < 0 or max_rating < 0 or min_rating > max_rating or max_rating > 249:
        await message.answer("Диапазон должен быть 0..249 и min <= max. Пример: `/seedrep 1 249`.", parse_mode="Markdown")
        return

    admins = await bot.get_chat_administrators(message.chat.id)
    me = await bot.me()

    seeded = 0
    skipped_nonzero = 0
    failed = 0

    for cm in admins:
        u = cm.user
        if u.is_bot:
            continue
        if u.id == me.id:
            continue

        try:
            p = await ctx.rating.profile(user=u)
            if p.rating != 0:
                skipped_nonzero += 1
                continue

            target = random.randint(min_rating, max_rating)
            if target <= 0:
                # Keep Novichok if configured so.
                skipped_nonzero += 1
                continue

            await ctx.rating.add_points(user=u, delta=target)
            seeded += 1

            # Try to sync title immediately (if possible).
            if message.chat.type == "supergroup" and cm.status in {"administrator", "creator"}:
                await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=u)
        except Exception:
            failed += 1

    await message.answer(
        "🎲 Стартовый рейтинг раздан.\n"
        f"Выдано: {seeded}\n"
        f"Пропущено (уже был рейтинг != 0): {skipped_nonzero}\n"
        f"Ошибок: {failed}\n\n"
        "Можно повторить: `/seedrep 1 249`",
        parse_mode="Markdown",
    )


@router.message(Command("promote", "промоут", "админ"))
async def cmd_promote(message: Message, bot: Bot, ctx: AppContext) -> None:
    """Promote a user to admin via the bot so it can later manage their custom title."""
    if not message.from_user:
        return
    if message.chat.type != "supergroup":
        await message.answer("Эта команда работает только в супергруппе.")
        return
    if not await _can_promote(bot, chat_id=message.chat.id, user_id=message.from_user.id):
        await message.answer("Только создатель чата или админ с правом 'Добавлять админов' может запускать /promote.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer(
            "Ответь на сообщение человека: `/promote`.\n"
            "Опционально: `/promote invite|mod|admin` (по умолчанию: invite).",
            parse_mode="Markdown",
        )
        return

    target = message.reply_to_message.from_user
    if target.is_bot:
        await message.answer("Ботов не промоутим.")
        return

    args = (message.text or "").split(maxsplit=1)
    mode = (args[1].strip().lower() if len(args) > 1 else "invite")
    if mode in {"минимум", "min"}:
        mode = "invite"
    if mode in {"мод", "moderator"}:
        mode = "mod"
    if mode in {"админ", "full"}:
        mode = "admin"
    if mode not in {"invite", "mod", "admin"}:
        await message.answer(
            "Не понял режим. Доступно: invite, mod, admin.\n"
            "Пример: `/promote mod`",
            parse_mode="Markdown",
        )
        return

    # Preflight: bot permissions.
    me = await bot.me()
    my_cm = await bot.get_chat_member(message.chat.id, me.id)
    if my_cm.status not in {"administrator", "creator"}:
        await message.answer("❌ Бот должен быть админом, чтобы промоутить людей.")
        return
    if my_cm.status == "administrator" and not getattr(my_cm, "can_promote_members", False):
        await message.answer("❌ Дай боту право 'Добавлять админов' (can_promote_members) и повтори.")
        return

    rights = {
        "invite": dict(can_invite_users=True),
        "mod": dict(
            can_delete_messages=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_invite_users=True,
        ),
        "admin": dict(
            can_manage_chat=True,
            can_change_info=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_video_chats=True,
        ),
    }[mode]

    try:
        ok = await bot.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            is_anonymous=False,
            can_manage_chat=rights.get("can_manage_chat", False),
            can_change_info=rights.get("can_change_info", False),
            can_delete_messages=rights.get("can_delete_messages", False),
            can_manage_video_chats=rights.get("can_manage_video_chats", False),
            can_restrict_members=rights.get("can_restrict_members", False),
            can_invite_users=rights.get("can_invite_users", False),
            can_pin_messages=rights.get("can_pin_messages", False),
            can_promote_members=False,
        )
    except TelegramBadRequest as e:
        await message.answer(f"❌ Не получилось промоутить: {e.message}")
        return
    except TelegramAPIError as e:
        await message.answer(f"❌ Ошибка Telegram API: {type(e).__name__}")
        return

    if not ok:
        await message.answer("❌ Telegram вернул False при промоуте.")
        return

    ok_title, err = await _sync_title_for_user(bot=bot, ctx=ctx, chat_id=message.chat.id, user=target)
    p = await ctx.rating.profile(user=target)
    if ok_title:
        await message.answer(f"✅ Промоут + титул: {p.display_name} → {p.badge}")
    else:
        await message.answer(
            f"✅ Промоут выполнен: {p.display_name}\n"
            f"❌ Титул не обновился: {err}"
        )
