from __future__ import annotations

import random
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.context import AppContext
from utils.asyncio_utils import run_in_thread

router = Router(name="minigame")

# {game_key: session_data}
_games: dict[str, dict] = {}

_WIRE_COLORS = ["🔴 Красный", "🔵 Синий", "🟢 Зелёный", "🟡 Жёлтый", "⚪ Белый"]

_BOMB_VARIANTS = [
    # === КЛАССИКА ===
    {"intro": "💣 {target} заминирован! Перережь правильный провод или...",
     "win": "✅ <b>Правильный провод!</b> {target} спасён. +{reward}!",
     "fail": ["💥 <b>БАБАХ!</b> {target} весь в говне и моче! -{penalty}", "💥 <b>ВЗРЫВ!</b> {target} покрыт субстанцией неизвестного происхождения. -{penalty}", "💥 <b>БУМ!</b> Бомба из канализации! {target} обделался. -{penalty}"]},
    {"intro": "🧨 У {target} над головой ведро с неизвестной жидкостью! Дёрни за верёвку...",
     "win": "✅ <b>Ведро пустое!</b> {target} цел. +{reward}!",
     "fail": ["🪣 <b>ПЛЮХ!</b> {target} облит прокисшим кефиром и рыбным соусом. -{penalty}", "🪣 <b>ХЛЮП!</b> Это не кефир... {target} пахнет как вокзальный туалет. -{penalty}"]},
    {"intro": "🚽 {target} сидит на минированном унитазе! Обрежь провод...",
     "win": "✅ <b>Унитаз обезврежен!</b> {target} встал чистым. +{reward}!",
     "fail": ["🚽 <b>ФОНТАН!</b> Унитаз взорвался! {target} с ног до головы в... ну вы поняли. -{penalty}", "🚽 <b>ГЕЙЗЕР!</b> Столб канализационной воды! {target} утонул в позоре. -{penalty}"]},
    {"intro": "🎪 Над {target} торт 200кг! Разрежь правильный провод...",
     "win": "✅ <b>Торт пролетел мимо!</b> {target} чист. +{reward}!",
     "fail": ["🎂 <b>ШМЯК!</b> Торт из протухших яиц и селёдки! {target} воняет на весь чат. -{penalty}", "🎂 <b>ПЛЮХ!</b> 200кг майонеза с чесноком! {target} в шоке. -{penalty}"]},
    {"intro": "🍺 {target} стоит рядом с заминированной полторашкой Багбира! Левая или правая?",
     "win": "✅ <b>Пивасик не взорвался!</b> {target} выпил и получает +{reward}! Вкусно!",
     "fail": ["🍺💥 <b>БАБАХ!</b> Полторашка Багбира взорвалась! {target} и все вокруг забрызганы просрочкой! -{penalty}!\n\n🤮 Багбир просроченный, все шатаются!", "🍺💥 <b>ФОНТАН БАГБИРА!</b> 4.5 литра просрочки по чату! {target} утонул в пене! -{penalty}!\n\n🫠 Запах на неделю."],
     "buttons": ["👈 Левая", "👉 Правая"], "splash": True},
    # === ЕДАНАПИТКИ ===
    {"intro": "🌭 {target} привязан к гигантской шаурме! Она тикает! Какой соус обезвредит бомбу?",
     "win": "✅ <b>Правильный соус!</b> Шаурма обезврежена и {target} даже перекусил. +{reward}!",
     "fail": ["🌯💥 <b>ШАУРМА ВЗОРВАЛАСЬ!</b> {target} с ног до головы в чесночном соусе и просроченной капусте! -{penalty}", "🌯💥 <b>БАБАХ!</b> Шаурма из ларька у метро разлетелась! {target} пахнет как тот самый ларёк. -{penalty}"],
     "buttons": ["🧄 Чесночный", "🌶 Острый", "🥛 Сметанный"]},
    {"intro": "🍕 {target} заперт в коробке с ядерной пиццей! Выбери кусок чтобы разминировать...",
     "win": "✅ <b>Пицца обезврежена!</b> {target} съел кусок и доволен. +{reward}!",
     "fail": ["🍕💥 <b>ПИЦЦА ВЗОРВАЛАСЬ!</b> {target} покрыт расплавленным сыром и анчоусами! -{penalty}", "🍕💥 <b>БУМ!</b> Ананасы с пиццы разлетелись как шрапнель! {target} в ужасе. -{penalty}"]},
    {"intro": "🥒 {target} нашёл подозрительную банку огурцов. Открыть или нет?",
     "win": "✅ <b>Огурцы отличные!</b> {target} закусил и получает +{reward}!",
     "fail": ["🥒💥 <b>РАССОЛ ВЗОРВАЛСЯ!</b> Банка 1987 года! {target} облит мутной жижей! -{penalty}", "🥒💀 <b>ОГУРЦЫ ОЖИЛИ!</b> Плесень обрела сознание и атаковала {target}! -{penalty}"],
     "buttons": ["🫙 Открыть", "🚫 Не трогать", "🔨 Разбить"]},
    {"intro": "🍜 {target} перед тарелкой подозрительного борща! Какую ложку взять?",
     "win": "✅ <b>Борщ оказался бабушкин!</b> {target} наелся и счастлив. +{reward}!",
     "fail": ["🍜💥 <b>ЭТО БЫЛ НЕ БОРЩ!</b> {target} хлебнул суп из носков! -{penalty}", "🍜🤮 <b>БОРЩ ОЖИЛ!</b> Свёкла начала мстить! {target} красный с ног до головы! -{penalty}"]},
    {"intro": "🧀 {target} нашёл сыр в мышеловке! Как достать?",
     "win": "✅ <b>Сыр добыт!</b> {target} ест пармезан как король. +{reward}!",
     "fail": ["🧀💥 <b>ХЛОП!</b> Мышеловка размером с медведя! {target} зажат и обмазан плавленым сырком. -{penalty}", "🐭 <b>КРЫСЫ!</b> Из мышеловки выбежала армия крыс! {target} визжит. -{penalty}"],
     "buttons": ["🤏 Аккуратно", "💪 Рывком", "🧲 Магнитом"]},
    # === ЖИВОТНЫЕ ===
    {"intro": "🐔 {target} окружён боевыми курицами! Выбери оружие для защиты...",
     "win": "✅ <b>Курицы отступили!</b> {target} победил и получает +{reward}!",
     "fail": ["🐔💥 <b>АТАКА КУРИЦ!</b> {target} заклёван и покрыт перьями! -{penalty}", "🐔💩 <b>КУРИЦЫ ПОБЕДИЛИ!</b> {target} обосран с высоты куриного полёта! -{penalty}"],
     "buttons": ["🗡 Меч", "🛡 Щит", "🌽 Кукуруза", "🏃 Бежать"]},
    {"intro": "🦆 На {target} летит стая уток с бомбами! Как уклониться?",
     "win": "✅ <b>Утки промахнулись!</b> {target} цел. +{reward}!",
     "fail": ["🦆💣 <b>ПРЯМОЕ ПОПАДАНИЕ!</b> Утки сбросили груз прямо на {target}! -{penalty}", "🦆💩 <b>КОВРОВАЯ БОМБАРДИРОВКА!</b> {target} покрыт утиным... содержимым. -{penalty}"],
     "buttons": ["⬅️ Влево", "➡️ Вправо", "⬇️ Лечь"]},
    {"intro": "🐙 {target} схвачен гигантским осьминогом! Какое щупальце отрубить?",
     "win": "✅ <b>Осьминог отпустил!</b> {target} свободен. +{reward}!",
     "fail": ["🐙💦 <b>ЧЕРНИЛА!</b> Осьминог плюнул чернилами! {target} чёрный с ног до головы! -{penalty}", "🐙 <b>СИЛЬНЕЕ СЖАЛ!</b> Осьминог обиделся и обнял {target} ещё крепче! -{penalty}"]},
    {"intro": "🐝 На {target} летит рой пчёл! Что делать?",
     "win": "✅ <b>Пчёлы улетели!</b> {target} цел и с мёдом. +{reward}!",
     "fail": ["🐝💥 <b>ЖЖЖЖ!</b> {target} ужален 47 раз! Опух как воздушный шар! -{penalty}", "🐝🍯 <b>ПЧЁЛЫ РЕШИЛИ ОСТАТЬСЯ!</b> {target} теперь живой улей. -{penalty}"],
     "buttons": ["🏃 Бежать", "🧊 Замереть", "🔥 Огонь", "🍯 Дать мёд"]},
    {"intro": "🐊 {target} на краю бассейна с крокодилами! Как перебраться?",
     "win": "✅ <b>Перебрался!</b> {target} на другом берегу. +{reward}!",
     "fail": ["🐊 <b>ХРУМ!</b> Крокодил съел штаны {target}! -{penalty}", "🐊💦 <b>ПЛЮХ!</b> {target} свалился в бассейн! Крокодилы в восторге! -{penalty}"],
     "buttons": ["🏊 Вплавь", "🦘 Прыжком", "🐊 По крокодилам"]},
    # === ТЕХНИКА ===
    {"intro": "💻 Ноутбук {target} заминирован! Нажми правильную клавишу...",
     "win": "✅ <b>Ctrl+Z спас!</b> {target} и его данные в безопасности. +{reward}!",
     "fail": ["💻💥 <b>СИНИЙ ЭКРАН СМЕРТИ!</b> Ноутбук взорвался! {target} в осколках клавиатуры! -{penalty}", "💻🔥 <b>rm -rf /!</b> Всё удалено! {target} потерял всё включая достоинство! -{penalty}"],
     "buttons": ["⌨️ Ctrl+Z", "⌨️ Alt+F4", "⌨️ Delete", "⌨️ Enter"]},
    {"intro": "📱 Телефон {target} на вибро и тикает! Свайпнуть куда?",
     "win": "✅ <b>Правильный свайп!</b> Телефон обезврежен. {target} получает +{reward}!",
     "fail": ["📱💥 <b>ВЗРЫВ АККУМУЛЯТОРА!</b> {target} без бровей! -{penalty}", "📱🔥 <b>ТЕЛЕФОН РАСПЛАВИЛСЯ!</b> {target} с куском пластика на лице! -{penalty}"],
     "buttons": ["⬆️ Вверх", "⬇️ Вниз", "⬅️ Влево", "➡️ Вправо"]},
    {"intro": "🖨 Принтер {target} заминирован! Что напечатать чтоб разминировать?",
     "win": "✅ <b>Принтер доволен!</b> Напечатал портрет {target} и успокоился. +{reward}!",
     "fail": ["🖨💥 <b>ЗАМЯТИЕ БУМАГИ!</b> Принтер взорвался тонером! {target} весь чёрный! -{penalty}", "🖨📄 <b>БЕСКОНЕЧНАЯ ПЕЧАТЬ!</b> Принтер завалил {target} бумагой! -{penalty}"],
     "buttons": ["📄 Пустой лист", "🖼 Фото кота", "📊 Отчёт"]},
    # === ТРАНСПОРТ ===
    {"intro": "🛒 {target} в заминированной тележке из Пятёрочки! Какое колесо открутить?",
     "win": "✅ <b>Тележка обезврежена!</b> {target} едет дальше. +{reward}!",
     "fail": ["🛒💥 <b>КОЛЕСО ОТЛЕТЕЛО!</b> {target} улетел вместе с тележкой в стену из консервов! -{penalty}", "🛒🥫 <b>ЛАВИНА!</b> Полки обрушились на {target}! Погребён под тушёнкой! -{penalty}"],
     "splash": True},
    {"intro": "🛗 {target} застрял в лифте с бомбой! Какой этаж нажать?",
     "win": "✅ <b>Двери открылись!</b> {target} на свободе. +{reward}!",
     "fail": ["🛗💥 <b>ЛИФТ РУХНУЛ!</b> {target} приземлился в подвал с крысами! -{penalty}", "🛗🔔 <b>ЗАСТРЯЛ НАВЕЧНО!</b> {target} слушает музыку лифта до конца времён! -{penalty}"],
     "buttons": ["1️⃣", "2️⃣", "3️⃣", "🔝"]},
    {"intro": "🚗 Тормоза у {target} заминированы! Какую педаль жать?",
     "win": "✅ <b>Остановился!</b> {target} жив и невредим. +{reward}!",
     "fail": ["🚗💥 <b>ВРЕЗАЛСЯ В СТОЛБ!</b> {target} вылетел через лобовое! -{penalty}", "🚗🌊 <b>В РЕКУ!</b> {target} уехал в пруд с утками! -{penalty}"],
     "buttons": ["🦶 Левая", "🦶 Правая", "🤚 Ручник"]},
    # === БЫТ ===
    {"intro": "🚿 Душ {target} заминирован! Какой кран крутить?",
     "win": "✅ <b>Тёплая водичка!</b> {target} чист и доволен. +{reward}!",
     "fail": ["🚿🥶 <b>ЛЕДЯНОЙ ДУШ!</b> {target} орёт как резаный! Вода -2°C! -{penalty}", "🚿🔥 <b>КИПЯТОК!</b> {target} варёный как рак! -{penalty}"],
     "buttons": ["🔵 Синий", "🔴 Красный"]},
    {"intro": "🧸 У {target} в руках заминированный плюшевый мишка! Что делать?",
     "win": "✅ <b>Мишка просто пукнул!</b> {target} и мишка друзья. +{reward}!",
     "fail": ["🧸💥 <b>МИШКА ВЗОРВАЛСЯ!</b> {target} в синтепоне и ужасе! -{penalty}", "🧸👻 <b>МИШКА ОЖИЛ!</b> И он ЗЛОЙ! {target} убегает! -{penalty}"],
     "buttons": ["🤗 Обнять", "🏃 Бросить", "🔪 Распороть"]},
    {"intro": "🧹 {target} нашёл заминированный пылесос! Какую кнопку жать?",
     "win": "✅ <b>Пылесос работает!</b> {target} убрался и получает +{reward}!",
     "fail": ["🧹💥 <b>ПЫЛЕСОС РАБОТАЕТ НАОБОРОТ!</b> {target} засыпан пылью 10-летней давности! -{penalty}", "🧹🌪 <b>ПЫЛЕСОС-УРАГАН!</b> {target} засосало внутрь! -{penalty}"],
     "buttons": ["🟢 ВКЛ", "🔴 ВЫКЛ", "🔄 ТУРБО"]},
    {"intro": "🪑 Стул {target} заминирован! Куда сесть?",
     "win": "✅ <b>Стул крепкий!</b> {target} сидит удобно. +{reward}!",
     "fail": ["🪑💥 <b>СТУЛ КАТАПУЛЬТА!</b> {target} улетел в потолок! -{penalty}", "🪑🔧 <b>НОЖКИ СЛОМАЛИСЬ!</b> {target} упал лицом в пол! -{penalty}"],
     "buttons": ["💺 Осторожно", "🏋️ С размаху", "🧍 Стоять"]},
    # === МИСТИКА ===
    {"intro": "🔮 {target} нашёл проклятый хрустальный шар! Какое заклинание сказать?",
     "win": "✅ <b>Шар показал будущее!</b> {target} теперь пророк. +{reward}!",
     "fail": ["🔮💥 <b>ШАР ВЗОРВАЛСЯ!</b> {target} покрыт осколками и проклятиями! -{penalty}", "🔮👻 <b>ИЗ ШАРА ВЫЛЕЗ ДЕМОН!</b> {target} одержим! -{penalty}"],
     "buttons": ["✨ Абракадабра", "🧙 Экспеллиармус", "💀 Авада Кедавра"]},
    {"intro": "🪦 {target} разбудил мумию! Как усыпить обратно?",
     "win": "✅ <b>Мумия уснула!</b> {target} герой-археолог. +{reward}!",
     "fail": ["🪦💥 <b>МУМИЯ ОБНЯЛА!</b> {target} замотан в бинты! -{penalty}", "🪦🏃 <b>МУМИЯ БЫСТРЕЕ!</b> {target} пойман и проклят на 3000 лет! -{penalty}"],
     "buttons": ["🎵 Колыбельная", "🥊 Удар", "📖 Заклинание"]},
    {"intro": "👽 {target} похищен инопланетянами! Какую кнопку нажать на пульте НЛО?",
     "win": "✅ <b>Телепортация домой!</b> {target} вернулся. +{reward}!",
     "fail": ["👽💥 <b>АНАЛЬНЫЙ ЗОНД!</b> {target} больше не сможет сидеть! -{penalty}", "👽🌀 <b>ТЕЛЕПОРТАЦИЯ В ТУАЛЕТ!</b> {target} материализовался в выгребной яме! -{penalty}"],
     "buttons": ["🔴 Красная", "🟢 Зелёная", "🔵 Синяя"]},
    # === СПОРТ ===
    {"intro": "⚽ На {target} летит заминированный мяч! Как отбить?",
     "win": "✅ <b>ГОЛ!</b> {target} отбил как Пеле. +{reward}!",
     "fail": ["⚽💥 <b>МЯЧ ВЗОРВАЛСЯ!</b> {target} без штанов! -{penalty}", "⚽🤕 <b>В ЛИЦО!</b> {target} с отпечатком мяча на лбу! -{penalty}"],
     "buttons": ["🦶 Ногой", "🤲 Руками", "🗣 Головой"]},
    {"intro": "🏋️ {target} поднимает заминированную штангу! Сколько повторений?",
     "win": "✅ <b>Штанга не взорвалась!</b> {target} — качок года. +{reward}!",
     "fail": ["🏋️💥 <b>ШТАНГА ВЗОРВАЛАСЬ!</b> Блины разлетелись! {target} под завалом! -{penalty}", "🏋️🤦 <b>УРОНИЛ НА НОГУ!</b> {target} хромает неделю! -{penalty}"],
     "buttons": ["1️⃣ Один раз", "5️⃣ Пять раз", "💯 Сто раз"]},
    # === АБСУРД ===
    {"intro": "🧲 {target} притянут гигантским магнитом к заминированному холодильнику! Что достать?",
     "win": "✅ <b>Достал нормальную еду!</b> {target} ест и кайфует. +{reward}!",
     "fail": ["🧲💥 <b>ХОЛОДИЛЬНИК ВЗОРВАЛСЯ!</b> {target} покрыт протухшими продуктами 2019 года! -{penalty}", "🧲🦠 <b>ЧТО-ТО ЖИВОЕ!</b> Из холодильника вылезла плесень с зубами! {target} в ужасе! -{penalty}"],
     "buttons": ["🥛 Молоко", "🍖 Мясо", "🧊 Лёд", "❓ Наугад"]},
    {"intro": "🎤 {target} на сцене с заминированным микрофоном! Что спеть?",
     "win": "✅ <b>Публика в восторге!</b> {target} — звезда! +{reward}!",
     "fail": ["🎤💥 <b>МИКРОФОН ВЗОРВАЛСЯ!</b> {target} без голоса и бровей! -{penalty}", "🎤📢 <b>ФИДБЭК!</b> Ушам всех пришёл конец! {target} оглох! -{penalty}"],
     "splash": True, "buttons": ["🎵 Катюшу", "🎵 Мурку", "🎵 Рик-ролл"]},
    {"intro": "🪞 {target} смотрит в заминированное зеркало! Что увидит?",
     "win": "✅ <b>Красавчик!</b> Зеркало показало {target} на 10 лет моложе. +{reward}!",
     "fail": ["🪞💥 <b>ЗЕРКАЛО ЛОПНУЛО!</b> 7 лет неудачи для {target}! -{penalty}", "🪞👹 <b>ИЗ ЗЕРКАЛА ВЫЛЕЗЛО ОНО!</b> {target} орёт и убегает! -{penalty}"],
     "buttons": ["👀 Посмотреть", "🙈 Закрыть глаза"]},
    {"intro": "🎰 {target} нашёл заминированный игровой автомат! Дёрни рычаг...",
     "win": "✅ <b>ДЖЕКПОТ!</b> {target} выиграл! +{reward}!",
     "fail": ["🎰💥 <b>АВТОМАТ ВЗОРВАЛСЯ!</b> {target} засыпан монетами! Больно! -{penalty}", "🎰🤡 <b>ТРИ КЛОУНА!</b> Из автомата полезли клоуны! {target} в панике! -{penalty}"],
     "buttons": ["🎰 Дёрнуть", "🏃 Уйти"]},
    {"intro": "🧯 Огнетушитель {target} — это бомба! Куда направить?",
     "win": "✅ <b>Пена безопасная!</b> {target} всех спас. +{reward}!",
     "fail": ["🧯💥 <b>ЭТО БЫЛ НЕ ОГНЕТУШИТЕЛЬ!</b> {target} выстрелил себе в лицо краской! -{penalty}", "🧯🌊 <b>ЦУНАМИ ПЕНЫ!</b> Весь чат утонул в пене! -{penalty}"],
     "splash": True},
    {"intro": "📦 {target} получил подозрительную посылку с Алиэкспресса! Открыть?",
     "win": "✅ <b>Внутри AirPods!</b> Настоящие! {target} в наушниках. +{reward}!",
     "fail": ["📦💥 <b>ПОСЫЛКА ВЗОРВАЛАСЬ!</b> Внутри был глиттер! {target} блестит неделю! -{penalty}", "📦🐍 <b>ЗМЕЯ!</b> Из посылки выползла кобра! {target} на люстре! -{penalty}"],
     "buttons": ["📦 Открыть", "🔙 Вернуть", "🔨 Потрясти"]},
    {"intro": "🎈 {target} держит подозрительный воздушный шарик! Что делать?",
     "win": "✅ <b>Шарик просто красивый!</b> {target} радуется как ребёнок. +{reward}!",
     "fail": ["🎈💥 <b>БАХ!</b> Шарик был с краской! {target} разноцветный! -{penalty}", "🎈💨 <b>ГАЗОВАЯ АТАКА!</b> Шарик был с сероводородом! Все задыхаются! -{penalty}"],
     "splash": True, "buttons": ["🤗 Держать", "📌 Лопнуть", "🎁 Подарить"]},
    {"intro": "🗑 {target} открыл мусорное ведро, а оно тикает! Какую крышку закрыть?",
     "win": "✅ <b>Ведро обезврежено!</b> {target} — сапёр года. +{reward}!",
     "fail": ["🗑💥 <b>МУСОР ВЗОРВАЛСЯ!</b> {target} покрыт гнилыми бананами и вчерашней рыбой! -{penalty}", "🗑🦨 <b>СКУНС!</b> В ведре жил скунс! {target} воняет месяц! -{penalty}"],
     "buttons": ["🔵 Синяя", "🟢 Зелёная", "🔴 Красная"]},
    {"intro": "🧴 {target} нашёл заминированный шампунь! Какую кнопку нажать?",
     "win": "✅ <b>Волосы шикарные!</b> {target} как из рекламы. +{reward}!",
     "fail": ["🧴💥 <b>ЭТО БЫЛ КЛЕЙ!</b> {target} лысый! Волосы остались в руках! -{penalty}", "🧴🟢 <b>ЗЕЛЁНКА!</b> {target} зелёный как Шрек! -{penalty}"],
     "buttons": ["💆 Намылить", "🚿 Смыть", "👃 Понюхать"]},
    {"intro": "🧲 {target} приклеился к заминированному магниту на холодильник! Как оторвать?",
     "win": "✅ <b>Оторвался!</b> {target} свободен. +{reward}!",
     "fail": ["🧲💥 <b>МАГНИТ ПРИТЯНУЛ ВСЁ ЖЕЛЕЗНОЕ!</b> На {target} прилетели вилки, ножи и сковородка! -{penalty}", "🧲🔧 <b>ПРИЛИПЛО НАВСЕГДА!</b> {target} теперь часть холодильника! -{penalty}"],
     "buttons": ["💪 Дёрнуть", "🧈 Маслом", "🔌 Размагнитить"]},
    {"intro": "🎁 {target} получил подарок от анонима! Внутри тикает! Развернуть?",
     "win": "✅ <b>Внутри котёнок!</b> {target} растроган. +{reward}!",
     "fail": ["🎁💥 <b>БОМБА-СЮРПРИЗ!</b> Внутри был конфетти из навоза! {target} фу! -{penalty}", "🎁🤡 <b>ХЛОПУШКА ИЗ АДА!</b> {target} оглох и в серпантине! -{penalty}"],
     "buttons": ["🎁 Открыть", "🏃 Выбросить", "🐕 Дать собаке"]},
    {"intro": "🚰 Кран у {target} тикает! Какой вентиль крутить?",
     "win": "✅ <b>Вода нормальная!</b> {target} попил и доволен. +{reward}!",
     "fail": ["🚰💥 <b>ФОНТАН!</b> Из крана ударил гейзер! {target} мокрый с потолка! -{penalty}", "🚰🟤 <b>ЭТО НЕ ВОДА!</b> Из крана полилась ржавчина! {target} рыжий! -{penalty}"],
     "buttons": ["🔵 Холодный", "🔴 Горячий"]},
    {"intro": "🪤 {target} шагнул на заминированный коврик! Куда прыгать?",
     "win": "✅ <b>Приземлился на подушку!</b> {target} мягкий и целый. +{reward}!",
     "fail": ["🪤💥 <b>КОВРИК-КАТАПУЛЬТА!</b> {target} вылетел в окно! -{penalty}", "🪤🕳 <b>ЛЮКИ ОТКРЫЛИСЬ!</b> {target} провалился в подвал! -{penalty}"],
     "buttons": ["⬅️ Влево", "➡️ Вправо", "⬆️ Вверх"]},
    {"intro": "🧃 {target} нашёл подозрительный сок! Какую трубочку воткнуть?",
     "win": "✅ <b>Сок вкусный!</b> {target} пьёт и радуется. +{reward}!",
     "fail": ["🧃💥 <b>ЭТО БЫЛ УКСУС!</b> {target} кривится неделю! -{penalty}", "🧃🤮 <b>СОК ИЗ НОСКОВ!</b> {target} блюёт радугой! -{penalty}"],
     "buttons": ["🟡 Жёлтая", "🟢 Зелёная", "🔴 Красная"]},
]


def make_game(chat_id: int, voter_id: int, target_name: str, target_id: int) -> tuple[str, InlineKeyboardMarkup, str] | None:
    """Create a bomb minigame. Returns (text, kb, game_key) or None."""
    variant = random.choice(_BOMB_VARIANTS)
    vid = _BOMB_VARIANTS.index(variant)

    if "buttons" in variant:
        labels = variant["buttons"]
    else:
        num_wires = random.randint(3, 5)
        labels = _WIRE_COLORS[:num_wires]

    correct = random.randint(0, len(labels) - 1)
    game_key = f"{chat_id}:{target_id}:{random.randint(1000,9999)}"

    _games[game_key] = {
        "target_name": target_name,
        "target_id": target_id,
        "voter_id": voter_id,
        "correct": correct,
        "variant": vid,
        "chat_id": chat_id,
        "splash": variant.get("splash", False),
    }

    text = f"🎮 <b>МИНИ-ИГРА!</b>\n\n{variant['intro'].format(target=target_name)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"bomb:{game_key}:{i}")]
        for i, label in enumerate(labels)
    ])
    return text, kb, game_key


import time
from collections import defaultdict

_lal_history: dict[int, list[float]] = defaultdict(list)
_lal_bans: dict[int, float] = {}
_LAL_COOLDOWN = 60
_LAL_SPAM_COUNT = 3
_LAL_BAN_SECONDS = 300


@router.message(Command("lal"))
async def cmd_lal(message: Message, ctx: AppContext) -> None:
    if not message.from_user:
        return
    uid = message.from_user.id
    is_pchellovod = (message.from_user.username or "").lower() == "pchellovod"
    now = time.time()

    if not is_pchellovod:
        if uid in _lal_bans and now < _lal_bans[uid]:
            remaining = int(_lal_bans[uid] - now)
            await message.answer(f"Ты забанен. Осталось {remaining} сек.")
            return
        _lal_history[uid] = [t for t in _lal_history[uid] if now - t < 120]
        _lal_history[uid].append(now)
        if len(_lal_history[uid]) >= _LAL_SPAM_COUNT:
            _lal_bans[uid] = now + _LAL_BAN_SECONDS
            _lal_history[uid] = []
            await message.answer("Вафлист, хуле ты сайт ковыряешь?\nБан на 5 минут.")
            return
        if len(_lal_history[uid]) >= 2 and now - _lal_history[uid][-2] < _LAL_COOLDOWN:
            await message.answer(f"Кулдаун {_LAL_COOLDOWN} сек. Подожди.")
            return

    if message.reply_to_message and message.reply_to_message.from_user:
        to_user = message.reply_to_message.from_user
        target_name = to_user.username if to_user.username else to_user.full_name
        target_id = to_user.id
    else:
        rand_user = await run_in_thread(
            ctx.rating._storage.get_random_user, chat_id=message.chat.id, exclude_id=message.from_user.id
        )
        if not rand_user:
            await message.answer("Некого минировать!")
            return
        target_name = rand_user.username or rand_user.first_name or str(rand_user.user_id)
        target_id = rand_user.user_id
    result = make_game(message.chat.id, message.from_user.id, target_name, target_id)
    if result:
        text, kb, _key = result
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


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
