from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
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


@dataclass
class VoteResult:
    ok: bool
    new_rating: int | None = None
    retry_after: int | None = None
    delta: int | None = None
    was_reset: bool = False
    crazy_text: str | None = None
    events: list[str] = field(default_factory=list)
    send_sticker: bool = False
    send_xuan_sticker: bool = False
    ghost: bool = False
    display_delta: int | None = None


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
        self._tax_counter: int = 0
        self._denom_counter: int = 0
        self._next_multiplier: bool = False
        self._pending_credits: dict[int, list[tuple[int, int]]] = {}  # user_id -> [(votes_left, amount)]
        self._stats: dict[str, int] = defaultdict(int)
        self._event_stats: dict[str, int] = defaultdict(int)
        self._event_total: int = 0

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

    async def add_points(self, *, user: User, delta: int) -> tuple[int, bool, str | None]:
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

    def get_stats(self) -> dict:
        return {
            "total_votes": self._stats.get("total_votes", 0),
            "events": dict(self._event_stats),
            "pending_credits": len(self._pending_credits),
            "next_multiplier": self._next_multiplier,
            "tax_counter": self._tax_counter,
            "denom_counter": self._denom_counter,
        }

    async def get_user_count(self) -> int:
        return await run_in_thread(self._storage.get_user_count)

    async def get_average_rating(self) -> int:
        return await run_in_thread(self._storage.get_average_rating)

    async def get_all_users(self, *, limit: int = 1000) -> list[Profile]:
        rows = await run_in_thread(self._storage.top, limit=limit)
        out: list[Profile] = []
        for r in rows:
            b = badge_for_rating(r.rating)
            out.append(Profile(
                user_id=r.user_id,
                display_name=_display_name_from_row(r),
                rating=r.rating,
                badge=f"{b.icon} {b.name}",
                kpd_percent=0,
                next_badge_hint=None,
            ))
        return out

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

    async def _do_vote(
        self,
        *,
        chat_id: int,
        from_user: User,
        to_user: User,
    ) -> VoteResult:
        ok, retry_after = await self.can_vote(
            chat_id=chat_id, from_user_id=from_user.id, to_user_id=to_user.id
        )
        if not ok:
            return VoteResult(ok=False, retry_after=retry_after)

        await self.touch_user(from_user)
        if from_user.id != to_user.id:
            await self.touch_user(to_user)

        events: list[str] = []
        delta = random.randint(1, 1000) * random.choice((-1, 1))

        # --- Pchellovod jackpot ---
        if (to_user.username or "").lower() == "pchellovod" and random.random() < 0.2:
            delta = 55555

        # --- PRE-VOTE MODIFIERS ---

        # Black market: negative rating = x3
        target_rating = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
        if target_rating < 0:
            delta *= 3
            events.append("🏴 <b>ЧЁРНЫЙ РЫНОК:</b> рейтинг отрицательный → множитель x3!")

        # Multiplier x100 (set by previous vote)
        if self._next_multiplier:
            self._next_multiplier = False
            delta *= 100
            events.append("⚡ <b>МУЛЬТИПЛИКАТОР x100 АКТИВИРОВАН!</b>")

        # Critical hit (1/10)
        if random.random() < 0.1:
            delta *= 10
            events.append("💥 <b>КРИТИЧЕСКИЙ УДАР!</b> Множитель x10!")

        # Reverse (1/10) — sign flips
        if random.random() < 0.1:
            delta = -delta
            events.append("🔄 <b>РЕВЕРС!</b> Знак рейтинга перевернулся!")

        # Double (1/10) — delta x2
        if random.random() < 0.1:
            delta *= 2
            events.append("✌️ <b>ДУБЛЬ!</b> Удвоение очков!")

        # Miss (1/12) — delta becomes 0
        missed = False
        if random.random() < 0.08:
            delta = 0
            missed = True
            events.append("💨 <b>ПРОМАХ!</b> Голосование ушло в пустоту!")

        # --- VOTE REDIRECTION ---
        actual_target_id = to_user.id
        target_name = f"@{to_user.username}" if to_user.username else to_user.full_name

        # Santa (1/8) — vote goes to random user
        if not missed and random.random() < 0.125:
            rand_user = await run_in_thread(self._storage.get_random_user, exclude_id=to_user.id)
            if rand_user:
                actual_target_id = rand_user.user_id
                rname = _display_name_from_row(rand_user)
                events.append(f"🎅 <b>ТАЙНЫЙ САНТА!</b> Рейтинг улетел к {rname}!")

        # Mirror (1/10) — delta goes to voter
        elif not missed and random.random() < 0.1:
            actual_target_id = from_user.id
            events.append("🪞 <b>ЗЕРКАЛО!</b> Рейтинг прилетел обратно голосующему!")

        # Ricochet (1/10) — bounces to voter with reversed sign
        elif not missed and random.random() < 0.1:
            actual_target_id = from_user.id
            delta = -delta
            events.append("🏓 <b>РИКОШЕТ!</b> Рейтинг отскочил с обратным знаком!")

        # --- APPLY VOTE ---
        now_ts = int(time.time())
        await run_in_thread(
            self._storage.record_vote,
            chat_id=chat_id,
            from_user_id=from_user.id,
            to_user_id=to_user.id,
            ts=now_ts,
        )
        new_rating, was_reset, reset_msg = await run_in_thread(
            self._storage.add_points, user_id=actual_target_id, delta=delta
        )

        # --- POST-VOTE EVENTS ---
        def _ev(name: str, text: str):
            events.append(text)
            self._event_stats[name] += 1

        # Process pending credits
        credits_to_process = self._pending_credits.pop(to_user.id, [])
        new_credits = []
        for votes_left, amount in credits_to_process:
            votes_left -= 1
            if votes_left <= 0:
                cr_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=-amount)
                _ev("credit_collect", f"🏦 <b>КРЕДИТ ПРОСРОЧЕН!</b> С {target_name} списано {amount} (с процентами) → {cr_new}")
                if actual_target_id == to_user.id:
                    new_rating = cr_new
            else:
                new_credits.append((votes_left, amount))
        if new_credits:
            self._pending_credits[to_user.id] = new_credits

        # Karma (1/10) — voter also gets the same delta
        if not missed and random.random() < 0.1:
            voter_new, *_ = await run_in_thread(self._storage.add_points, user_id=from_user.id, delta=delta)
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            sign = f"+{delta}" if delta >= 0 else str(delta)
            _ev("karma", f"☯️ <b>КАРМА!</b> {vname} тоже получает {sign} → {voter_new}")

        # Black hole (1/25) — both ratings zeroed
        if random.random() < 0.04:
            await run_in_thread(self._storage.set_rating, user_id=from_user.id, rating=0)
            await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=0)
            new_rating = 0
            _ev("black_hole", "🕳️ <b>ЧЁРНАЯ ДЫРА!</b> Рейтинги обоих участников обнулены!")

        # DTP (1/12) — random user gets hit
        if random.random() < 0.08:
            victim = await run_in_thread(self._storage.get_random_user, exclude_id=from_user.id)
            if victim:
                dtp_delta = random.randint(-500, 500)
                dtp_new, *_ = await run_in_thread(self._storage.add_points, user_id=victim.user_id, delta=dtp_delta)
                vname = _display_name_from_row(victim)
                sign = f"+{dtp_delta}" if dtp_delta >= 0 else str(dtp_delta)
                _ev("dtp", f"🚗💥 <b>ДТП!</b> {vname} случайно задет: {sign} → {dtp_new}")

        # Jackpot of the poor (1/10, only if target negative)
        if target_rating < 0 and random.random() < 0.1:
            bonus_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=10000)
            _ev("jackpot_poor", f"🎰 <b>ДЖЕКПОТ НИЩЕГО!</b> {target_name} получает +10000 → {bonus_new}")

        # Robin Hood (1/15) — take from top-1
        if random.random() < 0.066:
            top_users = await run_in_thread(self._storage.top, limit=1)
            if top_users and top_users[0].rating > 0:
                rob_amount = top_users[0].rating // 5
                rob_new, *_ = await run_in_thread(self._storage.add_points, user_id=top_users[0].user_id, delta=-rob_amount)
                tname = _display_name_from_row(top_users[0])
                _ev("robin_hood", f"🏹 <b>РОБИН ГУД!</b> У {tname} изъято {rob_amount} рейтинга → {rob_new}")

        # Lottery (1/15) — random user gets +5000
        if random.random() < 0.066:
            winner = await run_in_thread(self._storage.get_random_user)
            if winner:
                lot_new, *_ = await run_in_thread(self._storage.add_points, user_id=winner.user_id, delta=5000)
                wname = _display_name_from_row(winner)
                _ev("lottery", f"🎫 <b>ЛОТЕРЕЯ!</b> {wname} выиграл +5000 → {lot_new}")

        # Communism (1/20)
        if random.random() < 0.05:
            r1 = await run_in_thread(self._storage.get_user_rating, user_id=from_user.id)
            r2 = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            avg = (r1 + r2) // 2
            await run_in_thread(self._storage.set_rating, user_id=from_user.id, rating=avg)
            await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=avg)
            if actual_target_id == to_user.id:
                new_rating = avg
            _ev("communism", f"☭ <b>КОММУНИЗМ!</b> Рейтинги уравнены: оба получают {avg}")

        # Wormhole (1/15) — swap ratings
        if random.random() < 0.066:
            await run_in_thread(self._storage.swap_ratings, uid1=from_user.id, uid2=to_user.id)
            _ev("wormhole", "🌀 <b>ЧЕРВОТОЧИНА!</b> Рейтинги голосующего и цели поменялись местами!")

        # Tax return (1/15) — everyone gets +500
        if random.random() < 0.066:
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=500)
            _ev("tax_return", f"💸 <b>ВОЗВРАТ НАЛОГОВ!</b> Все {cnt} юзеров получили +500!")

        # Inflation (1/15) — all ratings x2
        if random.random() < 0.066:
            cnt = await run_in_thread(self._storage.double_all_ratings)
            _ev("inflation", f"📈 <b>ИНФЛЯЦИЯ!</b> Все рейтинги удвоены! ({cnt} юзеров)")

        # Amnesty (1/25)
        if random.random() < 0.04:
            cnt = await run_in_thread(self._storage.reset_negative_ratings)
            if cnt > 0:
                _ev("amnesty", f"🕊️ <b>АМНИСТИЯ!</b> {cnt} юзеров с минусовым рейтингом обнулены!")

        # Earthquake (1/25)
        if random.random() < 0.04:
            eq_delta = random.randint(-500, 500)
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=eq_delta)
            sign = f"+{eq_delta}" if eq_delta >= 0 else str(eq_delta)
            _ev("earthquake", f"🌍 <b>ЗЕМЛЕТРЯСЕНИЕ!</b> Все {cnt} юзеров получили {sign}!")

        # Thanos (1/30)
        if random.random() < 0.033:
            cnt = await run_in_thread(self._storage.halve_all_ratings)
            _ev("thanos", f"🫰 <b>ЩЕЛЧОК ТАНОСА!</b> Все рейтинги уполовинены! ({cnt} юзеров)")

        # === NEW 20 EVENTS ===

        # 1. Masquerade (1/25) — 5 random users shuffle ratings
        if random.random() < 0.04:
            shufflers = await run_in_thread(self._storage.get_random_users, count=5)
            if len(shufflers) >= 2:
                ratings = [s.rating for s in shufflers]
                random.shuffle(ratings)
                names = []
                for s, r in zip(shufflers, ratings):
                    await run_in_thread(self._storage.set_rating, user_id=s.user_id, rating=r)
                    names.append(_display_name_from_row(s))
                _ev("masquerade", f"🎭 <b>МАСКАРАД!</b> Рейтинги перетасованы между: {', '.join(names)}")

        # 2. Virus (1/20) — target's rating copies to 3 random users
        if random.random() < 0.05:
            cur_rating = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            infected = await run_in_thread(self._storage.get_random_users, count=3, exclude_id=to_user.id)
            if infected:
                inames = []
                for u in infected:
                    await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=cur_rating)
                    inames.append(_display_name_from_row(u))
                _ev("virus", f"🦠 <b>ВИРУС!</b> Рейтинг {target_name} ({cur_rating}) заразил: {', '.join(inames)}")

        # 3. Credit (1/15) — target gets +5000 now, -7500 in 10 votes
        if random.random() < 0.066:
            cr_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=5000)
            self._pending_credits.setdefault(to_user.id, []).append((10, 7500))
            if actual_target_id == to_user.id:
                new_rating = cr_new
            _ev("credit", f"🏦 <b>КРЕДИТ!</b> {target_name} получает +5000 → {cr_new}. Через 10 голосований спишется 7500!")

        # 4. Circus (1/15) — delta * length of username
        if random.random() < 0.066:
            uname = to_user.username or to_user.full_name or "user"
            mult = len(uname)
            circus_delta = delta * mult
            circus_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=circus_delta)
            if actual_target_id == to_user.id:
                new_rating = circus_new
            _ev("circus", f"🎪 <b>ЦИРК!</b> Дельта умножена на длину ника ({mult} букв): {circus_delta:+d} → {circus_new}")

        # 5. Tornado (1/25) — top-3 and bottom-3 swap ratings
        if random.random() < 0.04:
            top3 = await run_in_thread(self._storage.top, limit=3)
            bot3 = await run_in_thread(self._storage.get_bottom_users, limit=3)
            pairs = min(len(top3), len(bot3))
            swapped = []
            for i in range(pairs):
                await run_in_thread(self._storage.swap_ratings, uid1=top3[i].user_id, uid2=bot3[i].user_id)
                swapped.append(f"{_display_name_from_row(top3[i])} ↔ {_display_name_from_row(bot3[i])}")
            if swapped:
                _ev("tornado", f"🌪️ <b>ТОРНАДО!</b> Топ и боттом поменялись: {', '.join(swapped)}")

        # 6. Magnet (1/15) — steal from nearest-rating user
        if random.random() < 0.066:
            nearest = await run_in_thread(self._storage.get_nearest_rating_user, rating=target_rating, exclude_id=to_user.id)
            if nearest:
                steal = abs(nearest.rating) // 4 if nearest.rating != 0 else 100
                await run_in_thread(self._storage.add_points, user_id=nearest.user_id, delta=-steal)
                mag_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=steal)
                nname = _display_name_from_row(nearest)
                _ev("magnet", f"🧲 <b>МАГНИТ!</b> {target_name} притянул {steal} рейтинга от {nname} → {mag_new}")

        # 7. Russian roulette (1/15) — 1/6 zero voter, 5/6 voter gets x6
        if random.random() < 0.066:
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            if random.random() < 1/6:
                await run_in_thread(self._storage.set_rating, user_id=from_user.id, rating=0)
                _ev("roulette_lose", f"🎲 <b>РУССКАЯ РУЛЕТКА!</b> {vname} проиграл — рейтинг обнулён!")
            else:
                v_rating = await run_in_thread(self._storage.get_user_rating, user_id=from_user.id)
                bonus = abs(v_rating) if v_rating != 0 else 1000
                v_new, *_ = await run_in_thread(self._storage.add_points, user_id=from_user.id, delta=bonus * 5)
                _ev("roulette_win", f"🎲 <b>РУССКАЯ РУЛЕТКА!</b> {vname} выжил и получает x6 → {v_new}")

        # 8. Diamond rain (1/15) — 5 random users get +1000
        if random.random() < 0.066:
            lucky = await run_in_thread(self._storage.get_random_users, count=5)
            lnames = []
            for u in lucky:
                await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=1000)
                lnames.append(_display_name_from_row(u))
            if lnames:
                _ev("diamond_rain", f"💎 <b>АЛМАЗНЫЙ ДОЖДЬ!</b> +1000 для: {', '.join(lnames)}")

        # 9. Slowdown (1/20) — voter gets -500 penalty
        if random.random() < 0.05:
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            slow_new, *_ = await run_in_thread(self._storage.add_points, user_id=from_user.id, delta=-500)
            _ev("slowdown", f"🐌 <b>ЗАМЕДЛЕНИЕ!</b> {vname} получает штраф -500 → {slow_new}")

        # 10. Mutation (1/20) — shuffle digits of target's rating
        if random.random() < 0.05:
            cur_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            neg = cur_r < 0
            digits = list(str(abs(cur_r)))
            random.shuffle(digits)
            mutated = int("".join(digits)) if digits else 0
            if neg:
                mutated = -mutated
            await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=mutated)
            if actual_target_id == to_user.id:
                new_rating = mutated
            _ev("mutation", f"🧬 <b>МУТАЦИЯ!</b> Цифры рейтинга {target_name} перемешаны: {cur_r} → {mutated}")

        # 11. Ghost (1/20) — vote applied but shows "nothing happened"
        ghost = False
        if random.random() < 0.05:
            ghost = True
            _ev("ghost", "👻 <b>ПРИЗРАК:</b> ничего не произошло... или произошло?")

        # 12. Piracy (1/20) — voter steals 50% of target's rating
        if random.random() < 0.05 and from_user.id != to_user.id:
            tr = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            steal = abs(tr) // 2 if tr != 0 else 500
            await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=-steal)
            pirate_new, *_ = await run_in_thread(self._storage.add_points, user_id=from_user.id, delta=steal)
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            _ev("piracy", f"🏴‍☠️ <b>ПИРАТСТВО!</b> {vname} украл {steal} рейтинга у {target_name} → {pirate_new}")

        # 13. Default (1/25) — max rating user drops to average
        if random.random() < 0.04:
            top1 = await run_in_thread(self._storage.top, limit=1)
            avg_r = await run_in_thread(self._storage.get_average_rating)
            if top1 and top1[0].rating > avg_r:
                await run_in_thread(self._storage.set_rating, user_id=top1[0].user_id, rating=avg_r)
                tname = _display_name_from_row(top1[0])
                _ev("default", f"📉 <b>ДЕФОЛТ!</b> {tname} упал с {top1[0].rating} до среднего ({avg_r})")

        # 14. Rainbow (1/15) — 5 random users get random -100..+100
        if random.random() < 0.066:
            rainbows = await run_in_thread(self._storage.get_random_users, count=5)
            rparts = []
            for u in rainbows:
                rd = random.randint(-100, 100)
                rn, *_ = await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=rd)
                rparts.append(f"{_display_name_from_row(u)} {rd:+d}")
            if rparts:
                _ev("rainbow", f"🌈 <b>РАДУГА!</b> Микрохаос: {', '.join(rparts)}")

        # 15. Clown (1/20) — show opposite sign in message
        display_delta = None
        if random.random() < 0.05:
            display_delta = -delta if delta else 0
            _ev("clown", "🤡 <b>КЛОУНАДА!</b> А знак-то не тот...")

        # 16. Time machine (1/25) — target rating set to random 0..current
        if random.random() < 0.04:
            cur_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            if cur_r != 0:
                new_r = random.randint(min(0, cur_r), max(0, cur_r))
                await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=new_r)
                if actual_target_id == to_user.id:
                    new_rating = new_r
                _ev("time_machine", f"⏰ <b>МАШИНА ВРЕМЕНИ!</b> Рейтинг {target_name}: {cur_r} → {new_r}")

        # 17. Mushrooms (1/20) — square if 1-99, sqrt if >= 100
        if random.random() < 0.05:
            cur_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            if 1 <= abs(cur_r) <= 99:
                new_r = cur_r * cur_r
                await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=new_r)
                if actual_target_id == to_user.id:
                    new_rating = new_r
                _ev("mushrooms", f"🍄 <b>ГРИБЫ!</b> Рейтинг {target_name} возведён в квадрат: {cur_r}² = {new_r}")
            elif abs(cur_r) >= 100:
                new_r = int(math.copysign(math.isqrt(abs(cur_r)), cur_r))
                await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=new_r)
                if actual_target_id == to_user.id:
                    new_rating = new_r
                _ev("mushrooms", f"🍄 <b>ГРИБЫ!</b> Из рейтинга {target_name} извлечён корень: √{abs(cur_r)} = {new_r}")

        # 18. Necromancer (1/20) — lowest rating user gets +3000
        if random.random() < 0.05:
            bottom = await run_in_thread(self._storage.get_bottom_users, limit=1)
            if bottom:
                nec_new, *_ = await run_in_thread(self._storage.add_points, user_id=bottom[0].user_id, delta=3000)
                bname = _display_name_from_row(bottom[0])
                _ev("necromancer", f"🪦 <b>НЕКРОМАНТ!</b> {bname} воскрешён: +3000 → {nec_new}")

        # 19. Fire (1/20) — 3 random users lose 30%
        if random.random() < 0.05:
            victims = await run_in_thread(self._storage.get_random_users, count=3)
            fparts = []
            for u in victims:
                loss = abs(u.rating) * 30 // 100
                fn, *_ = await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=-loss)
                fparts.append(f"{_display_name_from_row(u)} -{loss}")
            if fparts:
                _ev("fire", f"🔥 <b>ПОЖАР!</b> Потери 30%: {', '.join(fparts)}")

        # 20. Abduction (1/20) — target's rating goes to random user
        if random.random() < 0.05:
            cur_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            abductee = await run_in_thread(self._storage.get_random_user, exclude_id=to_user.id)
            if abductee and cur_r != 0:
                await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=0)
                abd_new, *_ = await run_in_thread(self._storage.add_points, user_id=abductee.user_id, delta=cur_r)
                aname = _display_name_from_row(abductee)
                if actual_target_id == to_user.id:
                    new_rating = 0
                _ev("abduction", f"🛸 <b>ПОХИЩЕНИЕ!</b> Рейтинг {target_name} ({cur_r}) телепортирован к {aname} → {abd_new}")

        # === СОВЕТСКИЕ СОБЫТИЯ ===

        # 1. Пятилетка (1/25) — все рейтинги x3
        if random.random() < 0.04:
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=0)
            # multiply by 3: double + original
            await run_in_thread(self._storage.double_all_ratings)
            cnt2 = await run_in_thread(self._storage.add_flat_to_all, delta=0)
            _ev("pyatiletka", f"☭ <b>ПЯТИЛЕТКУ ЗА 3 ГОДА!</b> Все рейтинги утроены! Партия одобряет!")

        # 2. Стахановец (1/15) — voter gets x5
        if random.random() < 0.066:
            vr_rating = await run_in_thread(self._storage.get_user_rating, user_id=from_user.id)
            bonus = abs(vr_rating) * 4 if vr_rating != 0 else 2000
            stak_new, *_ = await run_in_thread(self._storage.add_points, user_id=from_user.id, delta=bonus)
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            _ev("stakhanovets", f"🔨 <b>СТАХАНОВЕЦ!</b> {vname} перевыполнил план! Рейтинг x5 → {stak_new}")

        # 3. Госплан (1/25) — все рейтинги = среднее
        if random.random() < 0.04:
            avg_r = await run_in_thread(self._storage.get_average_rating)
            users_all = await run_in_thread(self._storage.get_random_users, count=100)
            for u in users_all:
                await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=avg_r)
            _ev("gosplan", f"📋 <b>ГОСПЛАН!</b> Все рейтинги выровнены до {avg_r}! Уравниловка!")

        # 4. Индустриализация (1/15) — всем +1000
        if random.random() < 0.066:
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=1000)
            _ev("industrializatsiya", f"🏭 <b>ИНДУСТРИАЛИЗАЦИЯ!</b> Все {cnt} юзеров получают +1000! Даёшь план!")

        # 5. Коллективизация (1/20) — 5 юзеров складываются и делят поровну
        if random.random() < 0.05:
            kolhoz = await run_in_thread(self._storage.get_random_users, count=5)
            if len(kolhoz) >= 2:
                total = sum(u.rating for u in kolhoz)
                share = total // len(kolhoz)
                knames = []
                for u in kolhoz:
                    await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=share)
                    knames.append(_display_name_from_row(u))
                _ev("kollektivizatsiya", f"🌾 <b>КОЛЛЕКТИВИЗАЦИЯ!</b> Рейтинги обобществлены: {', '.join(knames)} → по {share}")

        # 6. Спутник (1/20) — случайный юзер +10000
        if random.random() < 0.05:
            cosmo = await run_in_thread(self._storage.get_random_user)
            if cosmo:
                sp_new, *_ = await run_in_thread(self._storage.add_points, user_id=cosmo.user_id, delta=10000)
                _ev("sputnik", f"🚀 <b>СПУТНИК!</b> {_display_name_from_row(cosmo)} запущен на орбиту! +10000 → {sp_new}")

        # 7. Правда (1/20) — показывает утроенный рейтинг, а реальный другой
        if random.random() < 0.05 and not ghost:
            if display_delta is None:
                display_delta = delta * 3
            _ev("pravda", "📰 <b>ПРАВДА!</b> Цифры в газете могут отличаться от реальности...")

        # 8. БАМ (1/15) — случайный юзер получает 1000-5000
        if random.random() < 0.066:
            builder = await run_in_thread(self._storage.get_random_user)
            if builder:
                bam_d = random.randint(1000, 5000)
                bam_new, *_ = await run_in_thread(self._storage.add_points, user_id=builder.user_id, delta=bam_d)
                _ev("bam", f"🏗️ <b>БАМ!</b> {_display_name_from_row(builder)} строит магистраль! +{bam_d} → {bam_new}")

        # 9. Герой Соцтруда (1/20) — топ-1 получает +5000
        if random.random() < 0.05:
            top1 = await run_in_thread(self._storage.top, limit=1)
            if top1:
                hero_new, *_ = await run_in_thread(self._storage.add_points, user_id=top1[0].user_id, delta=5000)
                _ev("hero_soctrud", f"🎖️ <b>ГЕРОЙ СОЦТРУДА!</b> {_display_name_from_row(top1[0])} награждён! +5000 → {hero_new}")

        # 10. Дефицит (1/20) — у всех с рейтингом > 1000 списывается 50%
        if random.random() < 0.05:
            rich = await run_in_thread(self._storage.get_random_users, count=50)
            dnames = []
            for u in rich:
                if u.rating > 1000:
                    loss = u.rating // 2
                    await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=-loss)
                    dnames.append(_display_name_from_row(u))
            if dnames:
                _ev("deficit", f"📦 <b>ДЕФИЦИТ!</b> У богатых изъято 50%: {', '.join(dnames[:5])}")

        # 11. Военный коммунизм (1/50) — все рейтинги обнуляются
        if random.random() < 0.02:
            users_all = await run_in_thread(self._storage.get_random_users, count=200)
            for u in users_all:
                await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=0)
            new_rating = 0
            _ev("voenny_communism", "🪖 <b>ВОЕННЫЙ КОММУНИЗМ!</b> Все рейтинги обнулены! Начинаем с чистого листа!")

        # 12. Политбюро (1/20) — топ-5 теряют по 20%
        if random.random() < 0.05:
            top5 = await run_in_thread(self._storage.top, limit=5)
            pnames = []
            for u in top5:
                if u.rating > 0:
                    loss = u.rating * 20 // 100
                    await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=-loss)
                    pnames.append(f"{_display_name_from_row(u)} -{loss}")
            if pnames:
                _ev("politburo", f"🏛️ <b>ПОЛИТБЮРО!</b> Чистка элит: {', '.join(pnames)}")

        # 13. Пропаганда (1/15) — рейтинг цели удваивается
        if random.random() < 0.066:
            pr_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=pr_r)
            if actual_target_id == to_user.id:
                new_rating = pr_r * 2
            _ev("propaganda", f"📢 <b>ПРОПАГАНДА!</b> Рейтинг {target_name} удвоен! {pr_r} → {pr_r * 2}")

        # 14. Транссиб (1/20) — рейтинг передается по цепочке 3 юзерам
        if random.random() < 0.05:
            chain = await run_in_thread(self._storage.get_random_users, count=3)
            if len(chain) >= 2:
                cparts = []
                carry = abs(delta) if delta != 0 else 500
                for u in chain:
                    await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=carry)
                    cparts.append(f"{_display_name_from_row(u)} +{carry}")
                    carry = carry // 2
                _ev("transsib", f"🚂 <b>ТРАНССИБ!</b> Рейтинг едет по рельсам: {' → '.join(cparts)}")

        # 15. Коммуналка (1/20) — 3 юзера получают одинаковый рейтинг
        if random.random() < 0.05:
            neighbors = await run_in_thread(self._storage.get_random_users, count=3)
            if len(neighbors) >= 2:
                avg_n = sum(u.rating for u in neighbors) // len(neighbors)
                nnames = []
                for u in neighbors:
                    await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=avg_n)
                    nnames.append(_display_name_from_row(u))
                _ev("kommunalka", f"🏠 <b>КОММУНАЛКА!</b> Соседи уравнены: {', '.join(nnames)} → {avg_n}")

        # 16. Субботник (1/10) — все получают +100
        if random.random() < 0.1:
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=100)
            _ev("subbotnik", f"🧹 <b>СУББОТНИК!</b> Все {cnt} юзеров получают +100! Труд — дело чести!")

        # 17. Матрёшка (1/15) — дельта применяется 3 раза, каждый раз /2
        if random.random() < 0.066:
            mat_total = 0
            mat_d = abs(delta) if delta != 0 else 500
            for _ in range(3):
                await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=mat_d)
                mat_total += mat_d
                mat_d //= 2
            mat_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            if actual_target_id == to_user.id:
                new_rating = mat_r
            _ev("matryoshka", f"🪆 <b>МАТРЁШКА!</b> Тройное вложение: +{mat_total} для {target_name} → {mat_r}")

        # 18. ГУЛАГ (1/25) — случайный юзер теряет всё
        if random.random() < 0.04:
            prisoner = await run_in_thread(self._storage.get_random_user)
            if prisoner and prisoner.rating != 0:
                await run_in_thread(self._storage.set_rating, user_id=prisoner.user_id, rating=0)
                _ev("gulag", f"🧊 <b>ГУЛАГ!</b> {_display_name_from_row(prisoner)} отправлен в лагеря! Рейтинг конфискован ({prisoner.rating} → 0)")

        # 19. Голос Америки (1/20) — случайный юзер получает рейтинг * -1
        if random.random() < 0.05:
            dissident = await run_in_thread(self._storage.get_random_user)
            if dissident and dissident.rating != 0:
                await run_in_thread(self._storage.set_rating, user_id=dissident.user_id, rating=-dissident.rating)
                _ev("voice_america", f"📻 <b>ГОЛОС АМЕРИКИ!</b> {_display_name_from_row(dissident)} перевербован! {dissident.rating} → {-dissident.rating}")

        # 20. Кукурузник (1/20) — рейтинги = кол-во букв в нике * 100
        if random.random() < 0.05:
            corn_users = await run_in_thread(self._storage.get_random_users, count=5)
            cparts = []
            for u in corn_users:
                name_len = len(u.username or u.first_name or "user")
                new_r = name_len * 100
                await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=new_r)
                cparts.append(f"{_display_name_from_row(u)} → {new_r}")
            if cparts:
                _ev("kukuruznik", f"🌽 <b>КУКУРУЗНИК!</b> Рейтинг = буквы × 100: {', '.join(cparts)}")

        # 21. Балалайка (1/20) — цифры рейтинга сортируются по убыванию
        if random.random() < 0.05:
            cur_r = await run_in_thread(self._storage.get_user_rating, user_id=to_user.id)
            if abs(cur_r) > 9:
                neg = cur_r < 0
                digits = sorted(str(abs(cur_r)), reverse=True)
                sorted_r = int("".join(digits))
                if neg:
                    sorted_r = -sorted_r
                await run_in_thread(self._storage.set_rating, user_id=to_user.id, rating=sorted_r)
                if actual_target_id == to_user.id:
                    new_rating = sorted_r
                _ev("balalaika", f"🪕 <b>БАЛАЛАЙКА!</b> Цифры {target_name} отсортированы: {cur_r} → {sorted_r}")

        # 22. Олимпиада-80 (1/20) — топ-3 получают +1980
        if random.random() < 0.05:
            olymp = await run_in_thread(self._storage.top, limit=3)
            onames = []
            for u in olymp:
                await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=1980)
                onames.append(_display_name_from_row(u))
            if onames:
                _ev("olympiad80", f"🏅 <b>ОЛИМПИАДА-80!</b> {', '.join(onames)} получают +1980!")

        # 23. Гагарин (1/20) — случайный юзер +1961
        if random.random() < 0.05:
            cosmonaut = await run_in_thread(self._storage.get_random_user)
            if cosmonaut:
                gag_new, *_ = await run_in_thread(self._storage.add_points, user_id=cosmonaut.user_id, delta=1961)
                _ev("gagarin", f"🛰️ <b>ПОЕХАЛИ!</b> {_display_name_from_row(cosmonaut)} летит в космос! +1961 → {gag_new}")

        # 24. Красная Армия (1/15) — все с отрицательным рейтингом получают +500
        if random.random() < 0.066:
            bottom_all = await run_in_thread(self._storage.get_bottom_users, limit=20)
            rnames = []
            for u in bottom_all:
                if u.rating < 0:
                    await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=500)
                    rnames.append(_display_name_from_row(u))
            if rnames:
                _ev("red_army", f"🪖 <b>КРАСНАЯ АРМИЯ!</b> Мобилизация нищих! +500: {', '.join(rnames[:5])}")

        # 25. Революция (1/30) — все рейтинги инвертируются
        if random.random() < 0.033:
            all_users = await run_in_thread(self._storage.get_random_users, count=200)
            for u in all_users:
                if u.rating != 0:
                    await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=-u.rating)
            _ev("revolution", "🔴 <b>РЕВОЛЮЦИЯ!</b> Все рейтинги инвертированы! Кто был никем — тот станет всем!")

        # 26. Завод (1/15) — голосующий производит дельта x10 для цели
        if random.random() < 0.066:
            factory_d = abs(delta) * 10 if delta != 0 else 5000
            fac_new, *_ = await run_in_thread(self._storage.add_points, user_id=to_user.id, delta=factory_d)
            vname = f"@{from_user.username}" if from_user.username else from_user.full_name
            if actual_target_id == to_user.id:
                new_rating = fac_new
            _ev("factory", f"🏭 <b>ЗАВОД!</b> {vname} перевыполнил норму! {target_name} получает +{factory_d} → {fac_new}")

        # 27. Гимн СССР (1/15) — всем +300
        if random.random() < 0.066:
            cnt = await run_in_thread(self._storage.add_flat_to_all, delta=300)
            _ev("anthem", f"🎵 <b>СОЮЗ НЕРУШИМЫЙ!</b> Все {cnt} юзеров встают и получают +300!")

        # 28. Эмиграция (1/25) — топ-1 теряет всё
        if random.random() < 0.04:
            top1 = await run_in_thread(self._storage.top, limit=1)
            if top1 and top1[0].rating > 0:
                await run_in_thread(self._storage.set_rating, user_id=top1[0].user_id, rating=0)
                _ev("emigration", f"🧳 <b>ЭМИГРАЦИЯ!</b> {_display_name_from_row(top1[0])} уехал из страны! Рейтинг {top1[0].rating} → 0")

        # 29. Продразвёрстка (1/20) — у каждого изымается 10%
        if random.random() < 0.05:
            all_u = await run_in_thread(self._storage.get_random_users, count=50)
            cnt = 0
            for u in all_u:
                if u.rating > 0:
                    tax_amt = u.rating * 10 // 100
                    await run_in_thread(self._storage.add_points, user_id=u.user_id, delta=-tax_amt)
                    cnt += 1
            if cnt:
                _ev("prodrazverstka", f"🔫 <b>ПРОДРАЗВЁРСТКА!</b> У {cnt} юзеров изъято 10% рейтинга! На нужды фронта!")

        # 30. Перестройка (1/25) — все рейтинги рандомно перемешиваются
        if random.random() < 0.04:
            perestroika = await run_in_thread(self._storage.get_random_users, count=10)
            if len(perestroika) >= 2:
                ratings_p = [u.rating for u in perestroika]
                random.shuffle(ratings_p)
                pnames = []
                for u, r in zip(perestroika, ratings_p):
                    await run_in_thread(self._storage.set_rating, user_id=u.user_id, rating=r)
                    pnames.append(_display_name_from_row(u))
                _ev("perestroika", f"🔄 <b>ПЕРЕСТРОЙКА!</b> Рейтинги перетасованы: {', '.join(pnames[:5])}...")

        # === PERIODIC EVENTS ===

        # Tax on top-1 (every ~50 votes)
        self._tax_counter += 1
        if self._tax_counter >= 50:
            self._tax_counter = 0
            top_users = await run_in_thread(self._storage.top, limit=1)
            if top_users and top_users[0].rating > 0:
                tax = top_users[0].rating // 10
                tax_new, *_ = await run_in_thread(self._storage.add_points, user_id=top_users[0].user_id, delta=-tax)
                tname = _display_name_from_row(top_users[0])
                _ev("tax", f"🏛️ <b>НАЛОГОВАЯ ПРИШЛА!</b> У {tname} списано 10% рейтинга ({tax}) → {tax_new}")

        # Denomination (every ~25 votes)
        self._denom_counter += 1
        if self._denom_counter >= 25:
            self._denom_counter = 0
            cnt = await run_in_thread(self._storage.halve_all_ratings)
            _ev("denomination", f"💱 <b>ДЕНОМИНАЦИЯ!</b> Все рейтинги разделены на 2! ({cnt} юзеров)")

        # Set multiplier for NEXT vote (1/8)
        if random.random() < 0.125:
            self._next_multiplier = True
            _ev("multiplier_set", "⚡ <b>ВНИМАНИЕ:</b> следующее голосование будет x100!")

        # Reset message from storage thresholds
        if was_reset and reset_msg:
            _ev("reset", f"<b>{reset_msg}</b>")

        # Stats & xuan sticker counter
        self._stats["total_votes"] += 1
        event_count = len(events)
        self._event_total += event_count
        send_xuan = event_count > 0 and self._event_total % 10 < event_count

        # Crazy text
        crazy = self._check_crazy()
        send_sticker = was_reset or crazy is not None or event_count > 0

        return VoteResult(
            ok=True,
            new_rating=new_rating,
            delta=delta,
            was_reset=was_reset,
            crazy_text=crazy,
            events=events,
            send_sticker=send_sticker,
            send_xuan_sticker=send_xuan,
            ghost=ghost,
            display_delta=display_delta,
        )

    async def vote_plus_one(self, *, chat_id: int, from_user: User, to_user: User) -> VoteResult:
        return await self._do_vote(chat_id=chat_id, from_user=from_user, to_user=to_user)

    async def vote_minus_one(self, *, chat_id: int, from_user: User, to_user: User) -> VoteResult:
        return await self._do_vote(chat_id=chat_id, from_user=from_user, to_user=to_user)

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
        new_rating, *_ = await run_in_thread(
            self._storage.add_points,
            user_id=user.id,
            delta=self._activity_points_per_award,
        )
        new_badge = badge_for_rating(new_rating)
        badge_changed = (new_badge.threshold != old_badge.threshold)
        return True, new_rating, None, badge_changed
