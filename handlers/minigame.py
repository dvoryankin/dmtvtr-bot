from __future__ import annotations

import random
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.context import AppContext
from utils.asyncio_utils import run_in_thread

router = Router(name="minigame")

# {game_key: session_data}
_games: dict[str, dict] = {}

_WIRE_COLORS = ["🔴 Красный", "🔵 Синий", "🟢 Зелёный", "🟡 Жёлтый", "⚪ Белый"]

_BOMB_VARIANTS = [
    {
        "intro": "💣 {target} заминирован! Перережь правильный провод или...",
        "win": "✅ <b>Правильный провод!</b> {target} спасён. +{reward} рейтинга!",
        "fail": [
            "💥 <b>БАБАХ!</b> {target} весь в говне и моче! -{penalty} рейтинга",
            "💥 <b>ВЗРЫВ!</b> {target} покрыт субстанцией неизвестного происхождения. -{penalty}",
            "💥 <b>БУМ!</b> Бомба из канализации! {target} обделался. -{penalty}",
        ],
    },
    {
        "intro": "🧨 У {target} над головой ведро с неизвестной жидкостью! Дёрни за верёвку...",
        "win": "✅ <b>Ведро пустое!</b> {target} цел. +{reward}!",
        "fail": [
            "🪣 <b>ПЛЮХ!</b> {target} облит прокисшим кефиром и рыбным соусом. -{penalty}",
            "🪣 <b>ХЛЮП!</b> Это не кефир... {target} пахнет как вокзальный туалет. -{penalty}",
        ],
    },
    {
        "intro": "🚽 {target} сидит на минированном унитазе! Обрежь провод...",
        "win": "✅ <b>Унитаз обезврежен!</b> {target} встал чистым. +{reward}!",
        "fail": [
            "🚽 <b>ФОНТАН!</b> Унитаз взорвался! {target} с ног до головы в... ну вы поняли. -{penalty}",
            "🚽 <b>ГЕЙЗЕР!</b> Столб канализационной воды! {target} утонул в позоре. -{penalty}",
        ],
    },
    {
        "intro": "🎪 Над {target} торт 200кг! Разрежь правильный провод...",
        "win": "✅ <b>Торт пролетел мимо!</b> {target} чист. +{reward}!",
        "fail": [
            "🎂 <b>ШМЯК!</b> Торт из протухших яиц и селёдки! {target} воняет на весь чат. -{penalty}",
            "🎂 <b>ПЛЮХ!</b> 200кг майонеза с чесноком! {target} в шоке. -{penalty}",
        ],
    },
    {
        "intro": "🍺 {target} стоит рядом с заминированной полторашкой Багбира! Левая кнопка или правая?",
        "win": "✅ <b>Пивасик не взорвался!</b> {target} выпил и получает +{reward} рейтинга! Вкусно!",
        "fail": [
            "🍺💥 <b>БАБАХ!</b> Полторашка Багбира взорвалась! {target} и все вокруг забрызганы просроченным пивом! -{penalty} рейтинга!\n\n🤮 Багбир оказался просроченный, все шатаются!",
            "🍺💥 <b>ФОНТАН БАГБИРА!</b> 4.5 литра просрочки разлетелись по чату! {target} утонул в пене! -{penalty}!\n\n🫠 Запах стоит неделю.",
        ],
    },
]


def make_game(chat_id: int, voter_id: int, target_name: str, target_id: int) -> tuple[str, InlineKeyboardMarkup, str] | None:
    """Create a bomb minigame. Returns (text, kb, game_key) or None."""
    variant = random.choice(_BOMB_VARIANTS)
    vid = _BOMB_VARIANTS.index(variant)

    # Beer variant: 2 buttons (left/right)
    if vid == 4:
        num_wires = 2
        labels = ["👈 Левая", "👉 Правая"]
    else:
        num_wires = random.randint(3, 5)
        labels = _WIRE_COLORS[:num_wires]

    correct = random.randint(0, num_wires - 1)
    game_key = f"{chat_id}:{target_id}:{random.randint(1000,9999)}"

    _games[game_key] = {
        "target_name": target_name,
        "target_id": target_id,
        "voter_id": voter_id,
        "correct": correct,
        "variant": vid,
        "chat_id": chat_id,
        "splash": vid == 4,  # beer splashes everyone
    }

    text = f"🎮 <b>МИНИ-ИГРА!</b>\n\n{variant['intro'].format(target=target_name)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"bomb:{game_key}:{i}")]
        for i, label in enumerate(labels)
    ])
    return text, kb, game_key


@router.callback_query(F.data.startswith("bomb:"))
async def bomb_answer(callback: CallbackQuery, ctx: AppContext) -> None:
    if not callback.from_user or not callback.message:
        return

    # Parse: bomb:chat_id:target_id:rand:wire_index
    data = callback.data[5:]  # remove "bomb:"
    parts = data.rsplit(":", 1)
    game_key = parts[0]
    wire = int(parts[1])

    session = _games.get(game_key)
    if not session:
        await callback.answer("Игра уже закончилась")
        return

    variant = _BOMB_VARIANTS[session["variant"]]
    target_name = session["target_name"]
    target_id = session["target_id"]
    penalty = random.randint(500, 2000)
    reward = random.randint(300, 1500)

    if wire == session["correct"]:
        text = variant["win"].format(target=target_name, reward=reward)
        # Add reward
        await run_in_thread(ctx.rating._storage.add_points, user_id=target_id, delta=reward)
    else:
        text = random.choice(variant["fail"]).format(target=target_name, penalty=penalty)
        # Apply penalty to target
        await run_in_thread(ctx.rating._storage.add_points, user_id=target_id, delta=-penalty)

        # Beer variant: splash everyone in chat
        if session["splash"]:
            from ratings.storage import RatingStorage
            splash_users = await run_in_thread(
                ctx.rating._storage.get_random_users, chat_id=session["chat_id"], count=5, exclude_id=target_id
            )
            if splash_users:
                splash_penalty = random.randint(100, 500)
                snames = []
                for u in splash_users:
                    await run_in_thread(ctx.rating._storage.add_points, user_id=u.user_id, delta=-splash_penalty)
                    name = u.username or u.first_name or str(u.user_id)
                    snames.append(name)
                text += f"\n\n🍺 Забрызгало: {', '.join(snames)} (по -{splash_penalty})"

    try:
        await callback.message.edit_text(text, parse_mode="HTML")
    except Exception:
        pass

    _games.pop(game_key, None)
    await callback.answer()
