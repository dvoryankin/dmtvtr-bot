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


def _question_kb(qi: int) -> InlineKeyboardMarkup:
    labels = ["1", "2", "3", "4", "5"]
    btns = []
    for i, label in enumerate(labels):
        btns.append(InlineKeyboardButton(text=label, callback_data=f"quiz:{qi}:{i+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[btns, [InlineKeyboardButton(text="Совсем нет          ↔          Точно да", callback_data="quiz_noop")]])


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

    nqi = qi + 1
    if nqi < len(QUESTIONS):
        try:
            await callback.message.edit_text(
                _question_text(nqi),
                reply_markup=_question_kb(nqi),
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        text = _results_text(session["answers"])
        restart_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Пройти заново", callback_data="quiz_restart")]
        ])
        try:
            await callback.message.edit_text(text, reply_markup=restart_kb, parse_mode="HTML")
        except Exception:
            pass
        del _sessions[uid]
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


# ========== MEME QUIZZES ==========

_meme_sessions: dict[int, dict] = {}

BREAD_RESULTS = {
    "baget": ("\U0001f956 Багет", "Ты элегантен, утончён и немного хрупок. Ломаешься под давлением, но выглядишь на миллион. Идеально сочетаешься с вином и чувством собственного превосходства."),
    "baton": ("\U0001f35e Батон", "Ты — классика. Надёжный, понятный, всегда в тему. Тебя знают все, и ты норм с этим. Не фаворит, но без тебя стол пуст."),
    "borodinsky": ("\U0001f7eb Бородинский", "Ты — глубина и интеллект. Тяжёлый, с кориандром и сложным характером. Не все тебя понимают, но те кто понял — не променяют."),
    "lavash": ("\U0001fad3 Лаваш", "Ты гибкий, адаптивный и сочетаешься вообще со всем. Тебя можно свернуть, развернуть, порвать — ты всё равно остаёшься собой."),
    "croissant": ("\U0001f950 Круассан", "Драматичный, многослойный, требующий внимания. Снаружи хрустящий, внутри мягкий. Утром ты — звезда, к вечеру — уже не тот."),
    "suhar": ("\U0001f358 Сухарь", "Сухой юмор, эмоциональная недоступность, хруст. Ты — то, что осталось от чьей-то несъеденной жизни, и ты окей с этим."),
    "ciabatta": ("\U0001fad3 Чиабатта", "Ты прикидываешься простым, но на самом деле хипстер до мозга костей. Дырки в тебе — не баги, а фичи."),
    "bulka": ("\U0001f9c1 Булка с маком", "Сладкий, немного хаотичный, мак застревает в зубах окружающих. Ты — тот кто приносит радость, но после тебя надо убираться."),
}

BREAD_QUESTIONS = [
    {"t": "Выберите звук, который вас описывает:", "a": [
        ("хрусть", {"baget": 2, "suhar": 3, "croissant": 1}),
        ("шмяк", {"baton": 2, "bulka": 2, "lavash": 1}),
        ("пшшш", {"ciabatta": 2, "lavash": 2}),
        ("мням", {"croissant": 2, "bulka": 3}),
    ]},
    {"t": "Что вы делаете, когда никто не видит?", "a": [
        ("Разговариваю с холодильником", {"bulka": 2, "borodinsky": 1}),
        ("Стою и смотрю в стену", {"suhar": 3, "borodinsky": 2}),
        ("Танцую", {"croissant": 3, "baget": 1}),
        ("Ем хлеб", {"baton": 3, "lavash": 1}),
    ]},
    {"t": "Выберите бесполезный предмет:", "a": [
        ("Зонтик для кошки", {"bulka": 2, "croissant": 2}),
        ("Чайник без дна", {"suhar": 2, "ciabatta": 2}),
        ("Шапка для коленки", {"lavash": 2, "baget": 1}),
        ("Кирпич из пенопласта", {"borodinsky": 2, "baton": 2}),
    ]},
    {"t": "Какой у вас потолок?", "a": [
        ("Белый и скучный", {"baton": 3, "suhar": 1}),
        ("Натяжной с подсветкой", {"croissant": 3, "baget": 2}),
        ("Не помню, давно не смотрел", {"borodinsky": 2, "ciabatta": 1}),
        ("У меня нет потолка", {"lavash": 2, "bulka": 2}),
    ]},
    {"t": "Вас попросили описать себя одним словом:", "a": [
        ("Надёжный", {"baton": 3, "borodinsky": 1}),
        ("Хрустящий", {"baget": 3, "suhar": 2}),
        ("Сложный", {"borodinsky": 3, "croissant": 1}),
        ("Мягкий", {"lavash": 2, "bulka": 2, "ciabatta": 1}),
    ]},
    {"t": "Что у вас в карманах прямо сейчас?", "a": [
        ("Ничего, я чист", {"lavash": 2, "baton": 1}),
        ("Крошки", {"suhar": 3, "baget": 1}),
        ("Список дел на 2019 год", {"borodinsky": 2, "ciabatta": 2}),
        ("Что-то липкое", {"bulka": 3, "croissant": 1}),
    ]},
    {"t": "Ваша реакция на комплимент:", "a": [
        ("Краснею и молчу", {"borodinsky": 2, "baton": 2}),
        ("Знаю, спасибо", {"baget": 3, "croissant": 2}),
        ("Подозрительно щурюсь", {"suhar": 3, "ciabatta": 1}),
        ("Обнимаю в ответ", {"bulka": 3, "lavash": 1}),
    ]},
]

BITE_RESULTS = {
    "giraffe": ("\U0001f992 Жираф", "Ты кусаешь высоко — амбициозно и с размахом. Тебе нужна стремянка, но это тебя не останавливает. Жираф в шоке, но уважает."),
    "hamster": ("\U0001f439 Хомяк", "Ты нежно пощипываешь. Микро-укусы, почти незаметные. Хомяк даже не понял что произошло. Ты — кусающий интроверт."),
    "crocodile": ("\U0001f40a Крокодил", "Ты кусаешь того, кто кусает. Ирония уровня бог. Крокодил впервые в жизни оказался по другую сторону челюсти."),
    "cat": ("\U0001f431 Кот", "Месть. Чистая, холодная месть за все разы, когда коты кусали тебя. Кот возмущён, но в глубине души понимает."),
    "capybara": ("\U0001fab4 Капибара", "Ты укусил и сразу пожалел. Капибара посмотрела на тебя своими добрыми глазами, и ты заплакал. Ты должен ей за моральный ущерб."),
    "duck": ("\U0001f986 Утка", "Ты хаотичен и непредсказуем. Утка? Серьёзно? Никто не ожидал, и в этом твоя сила."),
    "bear": ("\U0001f43b Медведь", "У тебя нет инстинкта самосохранения. Ты кусаешь медведя и считаешь это нормальным. Мы беспокоимся о тебе."),
    "fish": ("\U0001f41f Рыба", "Ты кусаешь рыбу. Мокро, скользко, непонятно зачем. Но тебе виднее. Рыба не может кричать."),
}

BITE_QUESTIONS = [
    {"t": "Как сильно вы кусаете?", "a": [
        ("Нежно, почти целую", {"hamster": 3, "capybara": 2}),
        ("Средне, чтоб запомнили", {"cat": 2, "duck": 2}),
        ("Со всей силы", {"bear": 3, "crocodile": 2}),
        ("Зубов нет, десной", {"fish": 3, "giraffe": 1}),
    ]},
    {"t": "Почему вы кусаете?", "a": [
        ("От скуки", {"duck": 3, "fish": 1}),
        ("Из мести", {"cat": 3, "crocodile": 2}),
        ("Это моя личность", {"bear": 2, "giraffe": 2}),
        ("Мне сказали что это тест", {"hamster": 2, "capybara": 2}),
    ]},
    {"t": "Вас кусали в детстве?", "a": [
        ("Да, и я запомнил", {"cat": 3, "crocodile": 1}),
        ("Нет, я был первым", {"bear": 3, "duck": 1}),
        ("Не помню, но шрамы есть", {"giraffe": 2, "fish": 2}),
        ("Мы не говорим об этом", {"capybara": 2, "hamster": 2}),
    ]},
    {"t": "Что вы делаете после укуса?", "a": [
        ("Убегаю", {"hamster": 3, "duck": 2}),
        ("Извиняюсь", {"capybara": 3, "fish": 1}),
        ("Кусаю ещё раз", {"bear": 3, "crocodile": 2}),
        ("Ничего не было", {"cat": 2, "giraffe": 2}),
    ]},
    {"t": "В какое время суток вы кусаете?", "a": [
        ("Утром, пока жертва спит", {"cat": 3, "hamster": 1}),
        ("Днём, при свидетелях", {"bear": 2, "giraffe": 3}),
        ("Вечером, романтично", {"capybara": 2, "duck": 2}),
        ("Ночью, в темноте", {"crocodile": 3, "fish": 2}),
    ]},
    {"t": "Ваша кусачая суперсила:", "a": [
        ("Невидимый укус", {"hamster": 2, "fish": 2}),
        ("Укус сквозь время", {"giraffe": 3, "duck": 1}),
        ("Укус который лечит", {"capybara": 3, "cat": 1}),
        ("Укус-разрушитель", {"bear": 2, "crocodile": 3}),
    ]},
    {"t": "Ваше кусачее кредо:", "a": [
        ("Кусай или будь укушен", {"crocodile": 3, "bear": 1}),
        ("Кусаю, значит существую", {"giraffe": 2, "cat": 2}),
        ("Не кусаю, а дегустирую", {"capybara": 2, "hamster": 2, "fish": 1}),
        ("КУСЬ", {"duck": 3, "bear": 2}),
    ]},
]

MEME_QUIZZES = {
    "bread": {"title": "\U0001f35e Какой вы хлеб?", "questions": BREAD_QUESTIONS, "results": BREAD_RESULTS},
    "bite": {"title": "\U0001f9b7 Какое животное вы кусаете?", "questions": BITE_QUESTIONS, "results": BITE_RESULTS},
}


def _mq_text(qid: str, qi: int) -> str:
    quiz = MEME_QUIZZES[qid]
    q = quiz["questions"][qi]
    total = len(quiz["questions"])
    filled = int((qi + 1) / total * 10)
    bar = "\u2593" * filled + "\u2591" * (10 - filled)
    return f"<b>{quiz['title']}</b>\n{bar} {qi + 1}/{total}\n\n{q['t']}"


def _mq_kb(qid: str, qi: int) -> InlineKeyboardMarkup:
    q = MEME_QUIZZES[qid]["questions"][qi]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"mq:{qid}:{qi}:{i}")]
        for i, (text, _) in enumerate(q["a"])
    ])


def _mq_result(qid: str, scores: dict[str, int]) -> str:
    quiz = MEME_QUIZZES[qid]
    best = max(scores, key=scores.get) if scores else list(quiz["results"].keys())[0]
    name, desc = quiz["results"][best]
    return f"<b>{quiz['title']}</b>\n\n<b>{name}</b>\n\n{desc}"


@router.message(Command("bread", "hleb"))
async def cmd_bread(message: Message) -> None:
    if not message.from_user:
        return
    _meme_sessions[message.from_user.id] = {"qid": "bread", "scores": {}}
    await message.answer(_mq_text("bread", 0), reply_markup=_mq_kb("bread", 0), parse_mode="HTML")


@router.message(Command("bite", "kus"))
async def cmd_bite(message: Message) -> None:
    if not message.from_user:
        return
    _meme_sessions[message.from_user.id] = {"qid": "bite", "scores": {}}
    await message.answer(_mq_text("bite", 0), reply_markup=_mq_kb("bite", 0), parse_mode="HTML")


@router.callback_query(F.data.startswith("mq:"))
async def mq_answer(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    uid = callback.from_user.id
    session = _meme_sessions.get(uid)
    if not session:
        await callback.answer("Начни тест заново")
        return
    parts = callback.data.split(":")
    qid, qi, ai = parts[1], int(parts[2]), int(parts[3])
    if session["qid"] != qid:
        await callback.answer("Начни тест заново")
        return
    _, answer_scores = MEME_QUIZZES[qid]["questions"][qi]["a"][ai]
    for rid, pts in answer_scores.items():
        session["scores"][rid] = session["scores"].get(rid, 0) + pts
    nqi = qi + 1
    if nqi < len(MEME_QUIZZES[qid]["questions"]):
        try:
            await callback.message.edit_text(_mq_text(qid, nqi), reply_markup=_mq_kb(qid, nqi), parse_mode="HTML")
        except Exception:
            pass
    else:
        text = _mq_result(qid, session["scores"])
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="\U0001f504 Ещё раз", callback_data=f"mr:{qid}")]])
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
        _meme_sessions.pop(uid, None)
    await callback.answer()


@router.callback_query(F.data.startswith("mr:"))
async def mq_restart(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    qid = callback.data.split(":")[1]
    _meme_sessions[callback.from_user.id] = {"qid": qid, "scores": {}}
    try:
        await callback.message.edit_text(_mq_text(qid, 0), reply_markup=_mq_kb(qid, 0), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()
