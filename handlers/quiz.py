from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

router = Router(name="quiz")

SPECS = [
    ("backend", "Backend-разработка", "Серверная логика, API, базы данных."),
    ("frontend", "Frontend-разработка", "Интерфейсы, анимации, UX."),
    ("devops", "DevOps / SRE", "CI/CD, мониторинг, автоматизация."),
    ("datascience", "Data Science / ML", "Модели, эксперименты, инсайты из данных."),
    ("security", "Инфобезопасность", "Защита систем, пентесты."),
    ("mobile", "Мобильная разработка", "iOS, Android, кроссплатформа."),
    ("qa", "QA / Тестирование", "Качество, автотесты."),
    ("architecture", "Системная архитектура", "Проектирование, масштабирование."),
    ("product", "Product Management", "Стратегия, приоритеты, метрики."),
    ("techwriting", "Тех. писатель", "Документация, гайды."),
    ("embedded", "Embedded / IoT", "Микроконтроллеры, прошивки."),
    ("gamedev", "Геймдев", "Движки, физика, графика."),
    ("cloud", "Cloud / Инфра", "Облака, IaC, сервисы."),
    ("dataeng", "Data Engineering", "Пайплайны, ETL, хранилища."),
]

QUESTIONS = [
    {"t": "Мне нравится разбираться, как что-то работает изнутри, а не просто пользоваться готовым.", "w": {"backend": 2, "devops": 1, "architecture": 2, "embedded": 3, "security": 1, "dataeng": 1}},
    {"t": "Я получаю удовольствие, когда интерфейс выглядит идеально до пикселя.", "w": {"frontend": 3, "mobile": 2, "gamedev": 1, "product": 1, "backend": -1}},
    {"t": "Я могу часами искать одну ошибку и не раздражаюсь.", "w": {"qa": 3, "backend": 1, "security": 2, "embedded": 1, "devops": 1}},
    {"t": "Мне интересно находить закономерности в больших объёмах данных.", "w": {"datascience": 3, "dataeng": 2, "security": 1, "backend": 1, "architecture": 1}},
    {"t": "Я люблю объяснять сложные вещи простым языком.", "w": {"techwriting": 3, "product": 2, "qa": 1, "frontend": 1}},
    {"t": "Меня привлекает идея управлять серверами и инфраструктурой.", "w": {"devops": 3, "cloud": 3, "embedded": 1, "architecture": 1, "backend": 1}},
    {"t": "Я думаю о том, как злоумышленник мог бы взломать систему.", "w": {"security": 3, "devops": 1, "architecture": 1, "backend": 1, "qa": 1}},
    {"t": "Мне нравится создавать то, что люди могут потрогать или увидеть.", "w": {"frontend": 2, "mobile": 3, "gamedev": 2, "embedded": 2, "product": 1}},
    {"t": "Я предпочитаю работать один и погружаться в задачу.", "w": {"backend": 2, "embedded": 2, "datascience": 1, "architecture": 1, "product": -2, "techwriting": -1}},
    {"t": "Математика и статистика — мои сильные стороны.", "w": {"datascience": 3, "dataeng": 2, "architecture": 1, "security": 1, "gamedev": 1, "backend": 1}},
    {"t": "Мне нравится автоматизировать рутинные процессы.", "w": {"devops": 3, "dataeng": 2, "backend": 2, "qa": 2, "cloud": 1}},
    {"t": "Я интересуюсь трендами в дизайне и UX.", "w": {"frontend": 3, "mobile": 2, "product": 2, "gamedev": 1, "techwriting": 1}},
    {"t": "Мне важно понимать, зачем продукт нужен пользователю.", "w": {"product": 3, "frontend": 1, "mobile": 1, "techwriting": 1, "qa": 1, "architecture": 1}},
    {"t": "Мне было бы интересно паять платы или программировать микроконтроллеры.", "w": {"embedded": 3, "gamedev": 1, "devops": 1, "security": 1}},
    {"t": "Я умею расставлять приоритеты и управлять ожиданиями.", "w": {"product": 3, "architecture": 2, "techwriting": 1, "qa": 1, "devops": 1}},
    {"t": "Мне нравится проектировать системы, даже если я сам их не буду писать.", "w": {"architecture": 3, "backend": 2, "cloud": 2, "devops": 1, "dataeng": 1}},
    {"t": "Я скорее перфекционист — хочу, чтобы всё работало без сбоев.", "w": {"qa": 2, "devops": 2, "security": 1, "embedded": 1, "backend": 1, "architecture": 1}},
    {"t": "Мне комфортно общаться с нетехническими людьми.", "w": {"product": 3, "techwriting": 2, "qa": 1, "frontend": 1, "mobile": 1, "backend": -1, "embedded": -1}},
    {"t": "Я люблю игры и мечтал бы создавать свои.", "w": {"gamedev": 3, "frontend": 1, "mobile": 1, "embedded": 1}},
    {"t": "Я готов дежурить ночью, если упал продакшн.", "w": {"devops": 3, "cloud": 2, "backend": 1, "security": 1, "architecture": 1}},
    {"t": "Я люблю документировать свои решения и процессы.", "w": {"techwriting": 3, "qa": 2, "architecture": 1, "product": 1, "devops": 1}},
    {"t": "Мне интересно, как устроена работа с большими потоками данных.", "w": {"dataeng": 3, "datascience": 2, "backend": 2, "cloud": 1, "architecture": 1}},
    {"t": "Я хочу видеть результат своей работы на экране телефона.", "w": {"mobile": 3, "frontend": 2, "gamedev": 1, "product": 1}},
    {"t": "Я хорошо замечаю баги, несоответствия и мелкие детали.", "w": {"qa": 3, "security": 2, "frontend": 1, "techwriting": 1}},
    {"t": "Мне нравится оптимизировать код так, чтобы он работал быстрее.", "w": {"backend": 3, "embedded": 2, "gamedev": 2, "architecture": 1, "dataeng": 1}},
    {"t": "Я слежу за новостями об облачных технологиях (AWS, GCP, Azure).", "w": {"cloud": 3, "devops": 2, "architecture": 1, "dataeng": 1, "backend": 1}},
    {"t": "Мне важнее надёжность системы, чем скорость разработки.", "w": {"security": 2, "qa": 2, "devops": 1, "architecture": 2, "embedded": 1, "cloud": 1, "product": -1}},
    {"t": "Я хотел бы принимать стратегические решения о развитии продукта.", "w": {"product": 3, "architecture": 2, "techwriting": 1, "frontend": 1, "datascience": 1}},
]

# {user_id: {"answers": [int|None, ...], "msg_id": int}}
_sessions: dict[int, dict] = {}


def _progress_bar(cur: int, total: int) -> str:
    filled = int(cur / total * 10)
    return "▓" * filled + "░" * (10 - filled)


def _question_kb(qi: int, selected: int | None = None) -> InlineKeyboardMarkup:
    labels = ["1", "2", "3", "4", "5"]
    btns = []
    for i, label in enumerate(labels):
        val = i + 1
        text = f"• {label} •" if selected == val else label
        btns.append(InlineKeyboardButton(text=text, callback_data=f"quiz:{qi}:{val}"))
    nav = []
    if qi > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"quiz_nav:prev:{qi}"))
    nav.append(InlineKeyboardButton(text="Далее →" if qi < len(QUESTIONS) - 1 else "Результаты →", callback_data=f"quiz_nav:next:{qi}"))
    return InlineKeyboardMarkup(inline_keyboard=[btns, [InlineKeyboardButton(text="Совсем нет          ↔          Точно да", callback_data="quiz_noop")], nav])


def _question_text(qi: int) -> str:
    q = QUESTIONS[qi]
    return (
        f"<b>Вопрос {qi + 1}/{len(QUESTIONS)}</b>\n"
        f"{_progress_bar(qi + 1, len(QUESTIONS))}\n\n"
        f"{q['t']}"
    )


def _calc_results(answers: list[int]) -> list[tuple[str, str, str, int]]:
    raw = {}
    max_p = {}
    min_p = {}
    for sid, name, desc in SPECS:
        raw[sid] = 0
        max_p[sid] = 0
        min_p[sid] = 0
    for qi, a in enumerate(answers):
        val = a if a else 3
        for sid, w in QUESTIONS[qi]["w"].items():
            raw[sid] += val * w
            if w > 0:
                max_p[sid] += 5 * w
            else:
                min_p[sid] += 5 * w
    results = []
    for sid, name, desc in SPECS:
        rng = max_p[sid] - min_p[sid]
        pct = round((raw[sid] - min_p[sid]) / rng * 100) if rng > 0 else 50
        pct = max(0, min(100, pct))
        results.append((sid, name, desc, pct))
    results.sort(key=lambda x: -x[3])
    return results


def _bar(pct: int) -> str:
    filled = int(pct / 100 * 12)
    return "█" * filled + "░" * (12 - filled)


def _results_text(answers: list[int]) -> str:
    results = _calc_results(answers)
    fit = round((results[0][3] + results[1][3] + results[2][3]) / 3)

    if fit >= 80:
        verdict = "IT — определённо ваше!"
    elif fit >= 60:
        verdict = "У вас хороший потенциал в IT."
    elif fit >= 40:
        verdict = "IT может быть вашим, стоит попробовать конкретные направления."
    else:
        verdict = "Возможно, IT — не самый очевидный путь."

    lines = [
        f"<b>🎯 IT Fit Score: {fit}%</b>",
        f"<i>{verdict}</i>",
        "",
        "<b>Топ специализаций:</b>",
    ]

    for i, (sid, name, desc, pct) in enumerate(results):
        if pct >= 70:
            icon = "🟢"
        elif pct >= 50:
            icon = "🟡"
        elif pct >= 30:
            icon = "🟠"
        else:
            icon = "⚪"
        line = f"{icon} <b>{pct}%</b> {name}"
        if i < 3:
            line += f"\n     <i>{desc}</i>"
        lines.append(line)

    return "\n".join(lines)


@router.message(Command("quiz", "квиз", "тест"))
async def cmd_quiz(message: Message) -> None:
    if not message.from_user:
        return
    uid = message.from_user.id
    _sessions[uid] = {"answers": [None] * len(QUESTIONS), "msg_id": None}
    text = _question_text(0)
    kb = _question_kb(0)
    sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    _sessions[uid]["msg_id"] = sent.message_id


@router.callback_query(F.data == "quiz_noop")
async def quiz_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    uid = callback.from_user.id
    session = _sessions.get(uid)
    if not session:
        await callback.answer("Начни квиз заново: /quiz")
        return

    parts = callback.data.split(":")
    qi = int(parts[1])
    val = int(parts[2])
    session["answers"][qi] = val

    # Update current question to show selection
    try:
        await callback.message.edit_text(
            _question_text(qi),
            reply_markup=_question_kb(qi, selected=val),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("quiz_nav:"))
async def quiz_nav(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    uid = callback.from_user.id
    session = _sessions.get(uid)
    if not session:
        await callback.answer("Начни квиз заново: /quiz")
        return

    parts = callback.data.split(":")
    action = parts[1]
    qi = int(parts[2])

    if action == "next":
        if session["answers"][qi] is None:
            await callback.answer("Выбери ответ!")
            return
        if qi < len(QUESTIONS) - 1:
            nqi = qi + 1
            try:
                await callback.message.edit_text(
                    _question_text(nqi),
                    reply_markup=_question_kb(nqi, selected=session["answers"][nqi]),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            # Show results
            if any(a is None for a in session["answers"]):
                await callback.answer("Не все вопросы отвечены!")
                return
            text = _results_text(session["answers"])
            restart_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Пройти заново", callback_data="quiz_restart")]
            ])
            try:
                await callback.message.edit_text(text, reply_markup=restart_kb, parse_mode="HTML")
            except Exception:
                pass
            del _sessions[uid]
    elif action == "prev":
        if qi > 0:
            nqi = qi - 1
            try:
                await callback.message.edit_text(
                    _question_text(nqi),
                    reply_markup=_question_kb(nqi, selected=session["answers"][nqi]),
                    parse_mode="HTML",
                )
            except Exception:
                pass
    await callback.answer()


@router.callback_query(F.data == "quiz_restart")
async def quiz_restart(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    uid = callback.from_user.id
    _sessions[uid] = {"answers": [None] * len(QUESTIONS), "msg_id": callback.message.message_id}
    try:
        await callback.message.edit_text(
            _question_text(0),
            reply_markup=_question_kb(0),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()
