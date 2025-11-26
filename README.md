# Демотиватор Бот для Telegram

Telegram бот для создания демотиваторов с поддержкой:
- Цветных эмоджи (Twemoji)
- Видео и анимированных стикеров
- Эффектов (инверсия, винтаж)
- AI-генерации текста (Groq)
- Рандомных стикеров из паков

## Возможности

### Команды
- `/d [текст]` — создать демотиватор
- `/dd [текст]` — аналог
- `/д [текст]` — русский вариант
- `/дд [текст]` — русский вариант
- `/inv [текст]` — инверсия цветов
- `/vin [текст]` — винтажная обработка
- `/help` — справка

### Способы использования

**1. Ответ командой на сообщение**
```
[Отправь фото/видео/стикер/текст]
Ответь на него: /д крутой текст
→ Получишь демотиватор
```

**2. Фото с подписью**
```
Отправь фото с подписью: /д текст
→ Автоматически создаст демотиватор
```

**3. Команда без реплая**
```
Просто отправь: /д
→ Рандомный стикер + AI-текст

Или: /д свой текст
→ Рандомный стикер + твой текст
```

### Что обрабатывает
- ✅ Фото, видео, гифки
- ✅ Стикеры (статичные, анимированные WEBM, TGS)
- ✅ Видео-кружки
- ✅ Текстовые сообщения (с аватаркой)
- ✅ Эмоджи (цветные!)

## Установка

### 1. Требования

**Система:** Ubuntu 20.04+ (или Debian)

**Зависимости:**
```bash
apt update
apt install -y python3.8 python3.8-venv python3-pip ffmpeg \
    libcairo2-dev pkg-config python3-dev fonts-dejavu \
    fonts-noto fonts-noto-color-emoji
```

### 2. Создай бота

1. Найди [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`
3. Следуй инструкциям
4. Скопируй токен

### 3. Установка бота

```bash
# Создай директорию
mkdir -p /root/bots
cd /root/bots

# Скопируй bot.py в /root/bots/

# Создай виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установи зависимости
pip install aiogram==3.15.0 pillow pilmoji groq lottie cairosvg

# Создай файл с картинкой-заглушкой
# Положи любую картинку как 123.png в /root/bots/
```

### 4. Настрой токены

**В bot.py найди и замени:**

```python
# Токен бота
TOKEN = "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"

# API ключ Groq (опционально, для AI-генерации)
GROQ_API_KEY = "gsk_ТВОЙ_КЛЮЧ_GROQ"
```

**Получить Groq API ключ:**
1. Иди на https://console.groq.com/
2. Зарегистрируйся (бесплатно)
3. Создай API key
4. Скопируй в bot.py

### 5. Настрой стикерпаки

**В функции `get_random_fallback_image` найди список:**

```python
sticker_packs = [
    "sp031fedcbc4e438a8984a76e28c81713d_by_stckrRobot",
    "pchellovod85434_by_sportsmem_bot",
    # ... твои паки
]
```

**Как найти ID стикерпака:**
1. Открой стикер в Telegram
2. Нажми на название пака
3. URL будет `t.me/addstickers/ИМЯ_ПАКА`
4. Скопируй `ИМЯ_ПАКА` в список

### 6. Создай systemd сервис

```bash
cat > /etc/systemd/system/dmtvtr-bot.service << 'EOF'
[Unit]
Description=Telegram demotivator bot (dmtvtr_bot)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bots
ExecStart=/root/bots/venv/bin/python /root/bots/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### 7. Запусти бота

```bash
# Включи и запусти сервис
systemctl daemon-reload
systemctl enable dmtvtr-bot
systemctl start dmtvtr-bot

# Проверь статус
systemctl status dmtvtr-bot

# Смотри логи
journalctl -u dmtvtr-bot -f
```

## Управление ботом

### Основные команды

```bash
# Запустить
systemctl start dmtvtr-bot

# Остановить
systemctl stop dmtvtr-bot

# Перезапустить
systemctl restart dmtvtr-bot

# Статус
systemctl status dmtvtr-bot

# Логи (живые)
journalctl -u dmtvtr-bot -f

# Последние 100 строк логов
journalctl -u dmtvtr-bot -n 100

# Логи за сегодня
journalctl -u dmtvtr-bot --since today
```

### Обновление кода

```bash
cd /root/bots

# Останови бота
systemctl stop dmtvtr-bot

# Сделай бэкап
cp bot.py bot_backup_$(date +%Y%m%d_%H%M).py

# Обнови код (скопируй новый bot.py)

# Запусти
systemctl start dmtvtr-bot

# Проверь логи
journalctl -u dmtvtr-bot -f
```

### Ручной запуск (для отладки)

```bash
cd /root/bots
source venv/bin/activate
python bot.py
```

## Структура файлов

```
/root/bots/
├── bot.py              # Основной код бота
├── 123.png             # Картинка-заглушка
├── times.ttf           # Шрифт Times New Roman (опционально)
├── bot.log             # Логи бота
├── venv/               # Виртуальное окружение
└── temp_*              # Временные файлы (автоудаление)
```

## Настройка функций

### Отступы в демотиваторе

**Файл:** `bot.py`  
**Функция:** `build_layout_params`  
**Строки:** ~290-295

```python
pad_top = 40          # Отступ сверху картинки
pad_side = 40         # Отступ по бокам
gap_to_text = 50      # От картинки до текста
gap_after_text = 40   # После текста
```

### Вероятность 123.png vs стикер

**Файл:** `bot.py`  
**Функция:** `get_random_fallback_image`  
**Строка:** ~450

```python
if random.random() < 0.2 and os.path.exists(FALLBACK_AVATAR):
    # 20% шанс на 123.png, 80% на стикер
```

### Размеры видео/фото

**Файл:** `bot.py`  
**Функция:** `build_layout_params`  
**Строка:** ~275

```python
max_side = 720 if for_video else 1024
# Видео макс 720px, фото макс 1024px
```

### Длительность видео

**Файл:** `bot.py`  
**Функция:** `create_demotivator_video`  
**Строка:** ~430

```python
"-t", "30",  # Максимум 30 секунд
```

### Размер шрифта подписи

**Файл:** `bot.py`  
**Функция:** `build_layout_params`  
**Строка:** ~288

```python
font_size = max(20, int(total_w / 12))
# Размер зависит от ширины, минимум 20px
```

### AI промпты для генерации

**Файл:** `bot.py`  
**Функция:** `generate_demotivator_text`  
**Строки:** ~110-120

```python
prompts = [
    "Напиши короткую саркастическую фразу...",
    "Придумай философскую фразу...",
    # Добавь свои промпты
]
```

### Креативность AI

**Файл:** `bot.py`  
**Функция:** `generate_demotivator_text`  
**Строка:** ~127

```python
temperature=1.2,  # Чем выше (до 2.0) - тем креативнее
```

## Troubleshooting

### Бот не запускается

```bash
# Проверь логи
journalctl -u dmtvtr-bot -n 50

# Попробуй запустить вручную
cd /root/bots
source venv/bin/activate
python bot.py
```

**Частые ошибки:**

1. **ModuleNotFoundError**
   ```bash
   source venv/bin/activate
   pip install aiogram pillow pilmoji groq lottie cairosvg
   ```

2. **IndentationError**
   - Проверь отступы в bot.py (должны быть пробелы, не табы)

3. **Token is invalid**
   - Проверь токен в bot.py
   - Убедись что бот не заблокирован

### Эмоджи не отображаются

```bash
# Установи шрифты
apt install fonts-noto-color-emoji fonts-dejavu

# Перезапусти
systemctl restart dmtvtr-bot
```

### Видео не обрабатывается

```bash
# Проверь ffmpeg
ffmpeg -version

# Если нет - установи
apt install ffmpeg

# Проверь логи
journalctl -u dmtvtr-bot | grep "ffmpeg"
```

### Нет места на диске

```bash
# Проверь место
df -h

# Очисти
apt clean
apt autoremove
journalctl --vacuum-size=100M

# Удали старые бэкапы
cd /root/bots
rm bot_backup_*.py
```

### AI не генерирует текст

1. Проверь API ключ Groq в bot.py
2. Проверь лимиты: https://console.groq.com/
3. Смотри логи: `journalctl -u dmtvtr-bot | grep "Groq"`

### Стикеры не скачиваются

1. Проверь ID стикерпака (правильное имя)
2. Убедись что пак публичный
3. Смотри логи: `journalctl -u dmtvtr-bot | grep "sticker"`

## Производительность

### Рекомендуемые характеристики сервера

- **CPU:** 1 vCore
- **RAM:** 1-2 GB
- **Диск:** 10 GB
- **Интернет:** Стабильное соединение

### Лимиты

- **Groq API:** 30 запросов/мин, 14,400/день (бесплатно)
- **Telegram Bot API:** без лимитов для личных ботов
- **FFmpeg:** ограничен только CPU/RAM

## Разработка

### Структура кода

```
bot.py
├── Импорты и константы
├── Инициализация (bot, dp, groq_client)
├── Утилиты
│   ├── get_font() - шрифты
│   ├── has_emoji() - проверка эмоджи
│   ├── fit_text() - разбивка текста
│   └── generate_demotivator_text() - AI генерация
├── Обработка изображений
│   ├── apply_invert() - инверсия
│   ├── apply_vintage() - винтаж
│   ├── generate_text_image() - текст → картинка
│   └── get_random_fallback_image() - рандом стикер
├── Создание демотиваторов
│   ├── build_layout_params() - разметка
│   ├── create_demotivator_image() - фото
│   └── create_demotivator_video() - видео
└── Хэндлеры
    ├── cmd_help() - /help
    ├── handle_media_with_caption() - фото с подписью
    └── handle_command() - команды с реплаем
```

### Добавление новых эффектов

1. Создай функцию `apply_новый_эффект(img_path, output_path)`
2. Добавь команду в `cmd_list` и `cmd_prefixes`
3. Добавь проверку в `handle_command`:
   ```python
   elif txt.lower().startswith("/новая"):
       effect = "новый_эффект"
   ```
4. Добавь в `create_demotivator_image`:
   ```python
   elif effect == 'новый_эффект':
       apply_новый_эффект(temp_path, temp_path)
   ```

### Логирование

Уровни логов:
- `INFO` - основные события
- `WARNING` - предупреждения
- `ERROR` - ошибки с трейсбеком

Лог файл: `/root/bots/bot.log`

## Лицензия

MIT License - используй как хочешь.

## Автор

Разработано с помощью Claude (Anthropic).

## Поддержка

При проблемах:
1. Проверь логи: `journalctl -u dmtvtr-bot -n 100`
2. Проверь статус: `systemctl status dmtvtr-bot`
3. Попробуй ручной запуск: `python bot.py`
