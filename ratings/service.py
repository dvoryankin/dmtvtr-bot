from __future__ import annotations

import random
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


_CRAZY_TEXTS = [
    "Внимание! Ваш рейтинг был замечен спецслужбами 7 стран",
    "Ваш социальный кредит пересчитан. Слава Партии",
    "Рейтинговая комиссия ООН выражает вам благодарность",
    "Ваш рейтинг виден из космоса. NASA подтверждает",
    "По данным разведки, ваш рейтинг влияет на курс биткоина",
    "Пентагон засекретил ваш рейтинг. Уровень допуска: COSMIC TOP SECRET",
    "Ваш рейтинг был упомянут в пророчествах Нострадамуса",
    "Совет старейшин одобряет ваш рейтинговый путь",
    "Рептилоиды с Нибиру следят за вашим рейтингом",
    "Ваш рейтинг нарушает законы термодинамики",
    "Илон Маск хочет купить ваш рейтинг за 44 миллиарда",
    "Квантовый компьютер Google не смог предсказать ваш рейтинг",
    "ФСБ открыло дело по факту вашего рейтинга",
    "Масоны включили вас в список избранных по рейтингу",
    "Ваш рейтинг зарегистрирован в Книге рекордов Гиннесса (отдел паранормального)",
    "Шаманы Тувы провели обряд на ваш рейтинг",
    "Матрица дала сбой при обработке вашего рейтинга",
    "Британские учёные доказали: ваш рейтинг лечит депрессию",
    "Ваш рейтинг запрещён в 14 странах",
    "По вашему рейтингу защитили кандидатскую диссертацию",
    "Нейросеть отказалась анализировать ваш рейтинг. Причина: страх",
    "Ваш рейтинг вызвал раскол в Ватикане",
    "Древние свитки предсказывали именно этот рейтинг",
    "МВФ пересмотрел прогноз мировой экономики из-за вашего рейтинга",
    "Ваш рейтинг — причина аномалий на Бермудском треугольнике",
    "Ваш рейтинг подключён к единому реестру душ",
    "Чак Норрис однажды видел ваш рейтинг. Он заплакал",
    "Ваш рейтинг облучён гамма-лучами. Не трогайте его руками",
    "Росреестр зарегистрировал ваш рейтинг как объект недвижимости",
    "Ваш рейтинг включён в программу защиты свидетелей",
    "Жириновский предсказывал именно этот рейтинг в 2007 году",
    "Ваш рейтинг вызвал ошибку 404 в базе данных реальности",
    "Шойгу лично проверил ваш рейтинг и остался доволен",
    "Ваш рейтинг конвертирован в 0.0003 биткоина. Поздравляем",
    "Совет Безопасности ООН экстренно собрался из-за вашего рейтинга",
    "Ваш рейтинг замечен на тёмной стороне Луны",
    "Центробанк рассматривает ваш рейтинг как залог под ипотеку",
    "Ваш рейтинг зафиксирован на Скрижалях Судьбы",
    "Древние египтяне построили пирамиду в честь вашего рейтинга",
    "Ваш рейтинг отправлен на экспертизу в Хогвартс",
    "Соседи написали жалобу на ваш рейтинг в управляющую компанию",
    "Ваш рейтинг включён в учебник по квантовой физике как аномалия",
    "Роскомнадзор пытается заблокировать ваш рейтинг. Безуспешно",
    "В параллельной вселенной ваш рейтинг — президент",
    "Ваш рейтинг был обнаружен при раскопках в Помпеях",
    "Астрологи объявили неделю вашего рейтинга",
    "Ваш рейтинг внесён в Красную книгу как вымирающий вид",
    "Путин в курсе вашего рейтинга. Без комментариев",
    "Ваш рейтинг прошёл через 5 стадий принятия",
    "На вашем рейтинге обнаружены следы внеземной цивилизации",
    "Ваш рейтинг застрахован в Ллойдс на 2 миллиона фунтов",
    "Разработчики Cyberpunk 2077 скопировали баги с вашего рейтинга",
    "Ваш рейтинг услышан радиотелескопом в созвездии Андромеды",
    "Дед Мороз добавил ваш рейтинг в список непослушных",
    "Ваш рейтинг вышел на IPO. Акции упали на 98%",
    "Голуби передают ваш рейтинг азбукой Морзе",
    "МЧС объявило штормовое предупреждение из-за вашего рейтинга",
    "Ваш рейтинг обнаружен в утечке Пентагона",
    "Папа Римский благословил ваш рейтинг. Аминь",
    "Ваш рейтинг вызвал переполнение стека на серверах Google",
    "Нобелевский комитет рассматривает номинацию вашего рейтинга",
    "По вашему рейтингу сняли документалку на Netflix",
    "Ваш рейтинг — единственное, что работает в этой стране",
    "Наркоконтроль проверяет ваш рейтинг на запрещённые вещества",
    "Ваш рейтинг зарегистрирован как религия в 3 странах",
    "Сатурн вошёл в ретроград из-за вашего рейтинга",
    "Ваш рейтинг использовался как пароль к ядерному чемоданчику",
    "Китай строит Великую стену вокруг вашего рейтинга",
    "Ваш рейтинг прослушивается. Говорите после сигнала",
    "Пенсионный фонд РФ конфисковал ваш рейтинг",
    "Учёные MIT написали 400-страничную диссертацию о вашем рейтинге",
    "Ваш рейтинг передан на хранение в Форт-Нокс",
    "Дальнобойщики передают привет вашему рейтингу по рации",
    "Ваш рейтинг объявлен памятником культурного наследия ЮНЕСКО",
    "Бабушки у подъезда обсуждают ваш рейтинг уже третий день",
]


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
        self._vote_counter: int = 0
        self._next_crazy: int = random.randint(15, 25)

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

    async def add_points(self, *, user: User, delta: int) -> tuple[int, bool]:
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

    def _check_crazy(self) -> str | None:
        self._vote_counter += 1
        if self._vote_counter >= self._next_crazy:
            self._vote_counter = 0
            self._next_crazy = random.randint(15, 25)
            return random.choice(_CRAZY_TEXTS)
        return None

    async def vote_plus_one(
        self,
        *,
        chat_id: int,
        from_user: User,
        to_user: User,
    ) -> tuple[bool, int | None, int | None, int | None, bool, str | None]:
        """Return (ok, new_rating, retry_after_seconds, delta, was_reset, crazy_text)."""
        is_pchellovod = (from_user.username or "").lower() == "pchellovod"
        if from_user.id == to_user.id and not is_pchellovod:
            return False, None, None, None, False, None

        ok, retry_after = await self.can_vote(
            chat_id=chat_id, from_user_id=from_user.id, to_user_id=to_user.id
        )
        if not ok:
            return False, None, retry_after, None, False, None

        await self.touch_user(from_user)
        if from_user.id != to_user.id:
            await self.touch_user(to_user)

        delta = random.randint(1, 1000) * random.choice((-1, 1))
        if (to_user.username or "").lower() == "pchellovod" and random.random() < 0.2:
            delta = 55555
        now_ts = int(time.time())
        await run_in_thread(
            self._storage.record_vote,
            chat_id=chat_id,
            from_user_id=from_user.id,
            to_user_id=to_user.id,
            ts=now_ts,
        )
        new_rating, was_reset = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=delta)
        crazy = self._check_crazy()
        return True, new_rating, None, delta, was_reset, crazy

    async def vote_minus_one(
        self,
        *,
        chat_id: int,
        from_user: User,
        to_user: User,
    ) -> tuple[bool, int | None, int | None, int | None, bool, str | None]:
        """Return (ok, new_rating, retry_after_seconds, delta, was_reset, crazy_text)."""
        is_pchellovod = (from_user.username or "").lower() == "pchellovod"
        if from_user.id == to_user.id and not is_pchellovod:
            return False, None, None, None, False, None

        ok, retry_after = await self.can_vote(
            chat_id=chat_id, from_user_id=from_user.id, to_user_id=to_user.id
        )
        if not ok:
            return False, None, retry_after, None, False, None

        await self.touch_user(from_user)
        if from_user.id != to_user.id:
            await self.touch_user(to_user)

        delta = random.randint(1, 1000) * random.choice((-1, 1))
        if (to_user.username or "").lower() == "pchellovod" and random.random() < 0.2:
            delta = 55555
        now_ts = int(time.time())
        await run_in_thread(
            self._storage.record_vote,
            chat_id=chat_id,
            from_user_id=from_user.id,
            to_user_id=to_user.id,
            ts=now_ts,
        )
        new_rating, was_reset = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=delta)
        crazy = self._check_crazy()
        return True, new_rating, None, delta, was_reset, crazy

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
        new_rating, _ = await run_in_thread(
            self._storage.add_points,
            user_id=user.id,
            delta=self._activity_points_per_award,
        )
        new_badge = badge_for_rating(new_rating)
        badge_changed = (new_badge.threshold != old_badge.threshold)
        return True, new_rating, None, badge_changed
