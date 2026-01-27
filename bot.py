import os
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()
import subprocess
import random
from groq import Groq
from pathlib import Path
from shutil import copy2

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
from pilmoji import Pilmoji

# API ключ Groq (из переменной окружения)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Токен бота (из переменной окружения)
TOKEN = os.getenv("BOT_TOKEN", "")

BASE_DIR = Path(__file__).resolve().parent
log_file = BASE_DIR / "bot.log"

# Заглушка для аватарки
FALLBACK_AVATAR = str(BASE_DIR / "123.png")

# Настройка шрифтов (порядок поиска)
FONT_PATHS = [
    str(BASE_DIR / "times.ttf"),
    "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]

# Шрифты с поддержкой Unicode
UNICODE_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

bot = Bot(token=TOKEN)
dp = Dispatcher()

OVERLOAD_IMAGE_2 = "/root/bots/2.jpg"
OVERLOAD_IMAGE_3 = "/root/bots/3.png"
MAX_CONCURRENT_PROCESSES = 2

def check_server_load():
    """Проверяет нагрузку на сервер"""
    try:
        result = subprocess.run(['pgrep', '-c', 'ffmpeg'], capture_output=True, text=True)
        count = int(result.stdout.strip()) if result.returncode == 0 else 0
        can_process = count < MAX_CONCURRENT_PROCESSES
        
        logging.info(f"Load check: {count} processes, limit {MAX_CONCURRENT_PROCESSES}, can_process={can_process}")
        
        return can_process, count
    except Exception as e:
        logging.warning(f"Failed to check load: {e}")
        return True, 0  # Если ошибка проверки - разрешаем

async def send_overload_message(message: Message, process_count: int):
    """Отправляет сообщение о перегрузке"""
    try:
        logging.info(f"Sending overload message for {process_count} processes")
        
        if process_count <= MAX_CONCURRENT_PROCESSES + 1:
            image_path = OVERLOAD_IMAGE_2
            caption = f"⚠️ Сервер загружен ({process_count} процессов)\nПопробуй через секунду"
            logging.info(f"Using light overload image: {image_path}")
        else:
            image_path = OVERLOAD_IMAGE_3
            caption = f"⚠️ Сервер перегружен ({process_count} процессов)\nПодожди немного"
            logging.info(f"Using heavy overload image: {image_path}")
        
        logging.info(f"Image exists: {os.path.exists(image_path)}")
        
        if os.path.exists(image_path):
            await message.answer_photo(
                FSInputFile(image_path),
                caption=caption
            )
            logging.info("Overload image sent successfully")
        else:
            logging.error(f"Overload image not found: {image_path}")
            await message.answer(f"⚠️ Сервер перегружен ({process_count} процессов)")
    except Exception as e:
        logging.error(f"Failed to send overload message: {e}", exc_info=True)
        await message.answer("⚠️ Слишком много запросов")


# --- Совместимость с Python 3.8 ---
try:
    _to_thread = asyncio.to_thread
    async def run_in_thread(func, *args, **kwargs):
        return await _to_thread(func, *args, **kwargs)
except AttributeError:
    async def run_in_thread(func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args, **kwargs)


# ---------------- ФУНКЦИИ: ШРИФТЫ И ТЕКСТ ----------------

def get_font(size: int) -> ImageFont.ImageFont:
    for font_path in FONT_PATHS:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return ImageFont.load_default()

def get_unicode_font(size: int) -> ImageFont.ImageFont:
    """Возвращает шрифт с поддержкой Unicode"""
    for font_path in UNICODE_FONT_PATHS:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return get_font(size)

def has_emoji(text: str) -> bool:
    """Проверяет содержит ли текст эмоджи"""
    for char in text:
        code = ord(char)
        if (0x1F300 <= code <= 0x1F9FF or
            0x2600 <= code <= 0x26FF or
            0x2700 <= code <= 0x27BF or
            0xFE00 <= code <= 0xFE0F or
            0x1F000 <= code <= 0x1F02F or
            0x1F0A0 <= code <= 0x1F0FF or
            0x1F100 <= code <= 0x1F64F or
            0x1F680 <= code <= 0x1F6FF or
            0x1F900 <= code <= 0x1F9FF or
            0x1FA00 <= code <= 0x1FA6F or
            0x1FA70 <= code <= 0x1FAFF or
            0x2300 <= code <= 0x23FF or
            0x25A0 <= code <= 0x25FF):
            return True
    return False

def fit_text(text: str, font: ImageFont.ImageFont, max_width: int, img: Image.Image):
    """Разбивает текст на строки с учетом pilmoji"""
    lines = []
    words = text.split()
    current_line = ""
    
    with Pilmoji(img) as pilmoji:
        for word in words:
            if len(lines) >= 10:
                break

            test_line = (current_line + " " + word).strip()
            # Используем pilmoji для измерения
            bbox = pilmoji.getsize(test_line, font=font)
            w = bbox[0]

            if w <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else ["..."]

def cleanup_old_temp_files():
    """Удаляет временные файлы старше 1 часа"""
    try:
        import time
        current_time = time.time()
        count = 0
        
        for filename in os.listdir("."):
            if filename.startswith("temp_"):
                filepath = os.path.join(".", filename)
                try:
                    # Проверяем возраст файла
                    file_age = current_time - os.path.getmtime(filepath)
                    
                    # Если старше 1 часа (3600 сек)
                    if file_age > 3600:
                        os.remove(filepath)
                        count += 1
                except:
                    pass
        
        if count > 0:
            logging.info(f"Cleaned up {count} old temp files")
    except Exception as e:
        logging.error(f"Cleanup error: {e}")


def generate_text_image(text: str, output_path: str, size=(600, 600)) -> bool:
    """Генерирует картинку из текста или эмоджи с поддержкой цветных эмоджи"""
    try:
        img = Image.new("RGB", size, "white")
        
        # Определяем нужен ли Unicode шрифт
        use_unicode = has_emoji(text)
        
        # Подбираем размер шрифта
        max_font_size = 120
        min_font_size = 40
        
        best_font = None
        best_lines = []
        
        for font_size in range(max_font_size, min_font_size, -10):
            font = get_unicode_font(font_size) if use_unicode else get_font(font_size)
            lines = fit_text(text, font, size[0] - 40, img)
            
            # Считаем общую высоту
            total_height = len(lines) * (font_size + 10)
            
            if total_height < size[1] - 40:
                best_font = font
                best_lines = lines
                break
        
        if not best_font:
            best_font = get_unicode_font(min_font_size) if use_unicode else get_font(min_font_size)
            best_lines = fit_text(text, best_font, size[0] - 40, img)
        
        # Рисуем текст с эмоджи
        font_size = best_font.size
        total_height = len(best_lines) * (font_size + 10)
        y = (size[1] - total_height) / 2
        
        with Pilmoji(img) as pilmoji:
            for line in best_lines:
                bbox = pilmoji.getsize(line, font=best_font)
                line_w = bbox[0]
                x = (size[0] - line_w) / 2
                pilmoji.text((int(x), int(y)), line, font=best_font, fill="black")
                y += font_size + 10
        
        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error(f"Error generating text image: {e}", exc_info=True)
        return False


# ---------------- ФУНКЦИИ: ОБРАБОТКА ИЗОБРАЖЕНИЙ ----------------

def apply_invert(img_path: str, output_path: str) -> bool:
    """Инверсия цветов"""
    try:
        img = Image.open(img_path)
        if img.mode == 'RGBA':
            r, g, b, a = img.split()
            rgb = Image.merge('RGB', (r, g, b))
            rgb = ImageOps.invert(rgb)
            r2, g2, b2 = rgb.split()
            img = Image.merge('RGBA', (r2, g2, b2, a))
        else:
            img = img.convert('RGB')
            img = ImageOps.invert(img)
        
        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error(f"Invert error: {e}")
        return False

def apply_vintage(img_path: str, output_path: str) -> bool:
    """Винтажная обработка: сепия + шум + виньетка"""
    try:
        img = Image.open(img_path).convert('RGB')
        width, height = img.size
        
        # 1. Сепия
        sepia_matrix = (
            0.393, 0.769, 0.189, 0,
            0.349, 0.686, 0.168, 0,
            0.272, 0.534, 0.131, 0
        )
        img = img.convert("RGB", sepia_matrix)
        
        # 2. Снижаем контраст и насыщенность
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(0.8)
        
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.6)
        
        # 3. Добавляем шум
        pixels = img.load()
        for i in range(0, width, 3):
            for j in range(0, height, 3):
                noise = random.randint(-15, 15)
                r, g, b = pixels[i, j]
                pixels[i, j] = (
                    max(0, min(255, r + noise)),
                    max(0, min(255, g + noise)),
                    max(0, min(255, b + noise))
                )
        
        # 4. Виньетка
        vignette = Image.new('L', (width, height), 0)
        vignette_draw = ImageDraw.Draw(vignette)
        
        for i in range(min(width, height) // 2):
            darkness = int(255 * (i / (min(width, height) / 2)))
            vignette_draw.rectangle(
                [i, i, width - i, height - i],
                outline=darkness
            )
        
        img = Image.composite(img, Image.new('RGB', img.size, (40, 30, 20)), vignette)
        
        img.save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error(f"Vintage error: {e}")
        return False

#генерация текста

def generate_demotivator_text() -> str:
    """Генерирует умную/саркастичную фразу для демотиватора"""
    if not groq_client:
        return random.choice([
            "Жизнь - боль",
            "Всё тленно",
            "Ничего не вечно",
            "Надежда умирает последней",
        ])
    
    try:
        prompts = [
            # "Напиши короткую саркастическую фразу для демотиватора на русском. Максимум 8 слов. Только текст, без кавычек.",
            # "Придумай философскую фразу для мема на русском. Максимум 8 слов. Только текст.",
            # "Сгенерируй циничную мысль для демотиватора. Коротко, на русском, до 8 слов.",
            # "Напиши абсурдную фразу в стиле русских демотиваторов. До 8 слов.",
            "напиши какой-нибудь рофл рофлянский",
            "напиши какую-нибудь шизу до 8 слов",
        ]
        
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Ты генератор текста для демотиваторов. Пиши кратко, саркастично, по-русски."},
                {"role": "user", "content": random.choice(prompts)}
            ],
            max_tokens=50,
            temperature=1.2,  # Больше креатива
        )
        
        text = response.choices[0].message.content.strip()
        
        # Убираем кавычки если есть
        text = text.strip('"').strip("'").strip()
        
        # Если слишком длинный - берём первые 10 слов
        words = text.split()
        if len(words) > 10:
            text = " ".join(words[:10]) + "..."
        
        logging.info(f"Generated text: {text}")
        return text
        
    except Exception as e:
        logging.error(f"Groq generation error: {e}")
        return random.choice([
            "Всё сложно",
            "Бывает",
            "Жизнь - боль",
            "Ничего не вечно",
        ])


def trumpify_text(original_text: str) -> str:
    """Переписывает текст в стиле Дональда Трампа"""
    if not groq_client:
        return f"{original_text} Tremendous! 🇺🇸"
    
    try:
        prompt = f"""Перепиши текст в стиле твитов Дональда Трампа. Точно копируй его манеру!

ОБЯЗАТЕЛЬНЫЕ элементы стиля:
- ЗАГЛАВНЫЕ слова для усиления (VERY, GREAT, FAKE NEWS, TERRIBLE, etc)
- Превосходные степени: biggest, greatest, best, worst, most, tremendous, fantastic, incredible, beautiful
- Короткие резкие предложения. Много восклицательных знаков!
- Фразы: "Many people are saying", "Believe me", "Everyone knows", "Like never before"
- Местоимения: "I", "We", "They" (враги)
- Третье лицо о себе: "President Trump", "Your favorite President"
- Эмодзи: 🇺🇸 (обязательно 1-2 раза)
- Драматизм и уверенность
- Обвинения врагов в провалах

ПРИМЕРЫ стиля Трампа:
"Just had a GREAT meeting with world leaders. Many people saying it was the BEST meeting in history! America is WINNING again! 🇺🇸"

"The Fake News Media won't report this, but our economy is doing TREMENDOUSLY! Jobs up, unemployment DOWN. Best numbers EVER! 🇺🇸"

"I am doing a FANTASTIC job - everyone knows it. The haters and losers won't admit it, but history will remember! MAGA! 🇺🇸"

Оригинал: "{original_text}"

Ответ (только переписанный текст без комментариев):"""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write EXACTLY like Donald Trump tweets. Use his style: CAPS, superlatives, short sentences, confidence, drama. Add 1-2 🇺🇸 flags."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=350,
            temperature=1.0,
        )
        
        result = response.choices[0].message.content.strip()
        result = result.strip('"').strip("'").strip()
        
        # Убираем markdown если есть
        result = result.replace('**', '')
        
        logging.info(f"Trumpified: {original_text[:50]}")
        return result
        
    except Exception as e:
        logging.error(f"Trumpify error: {e}")
        return f"{original_text} - FAKE NEWS! 🇺🇸"


async def download_user_avatar(user_id: int, output_path: str) -> bool:
    """Скачивает аватарку пользователя"""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            await bot.download(photos.photos[0][-1], destination=output_path)
            return True
        return False
    except Exception as e:
        logging.error(f"Failed to download avatar: {e}")
        return False


def create_trump_tweet_image(text: str, output_path: str, avatar_path: str = None) -> bool:
    """Создаёт картинку твита Трампа с динамическим размером"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        from pilmoji import Pilmoji
        
        logging.info(f"Creating Trump tweet image: {output_path}")
        
        # Шрифты (загружаем сначала для подсчёта размера)
        try:
            font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
            font_username = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
        except:
            font_name = ImageFont.load_default()
            font_username = ImageFont.load_default()
            font_text = ImageFont.load_default()
        
        # === ВЫЧИСЛЯЕМ РАЗМЕР ===
        max_width = 520
        
        # Разбиваем текст на строки
        words = text.split()
        lines = []
        current_line = []
        
        temp_img = Image.new('RGB', (1, 1))
        with Pilmoji(temp_img) as pilmoji:
            for word in words:
                test_line = ' '.join(current_line + [word])
                bbox = pilmoji.getsize(test_line, font=font_text)
                width = bbox[0]
                
                if width <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            
            if current_line:
                lines.append(' '.join(current_line))
        
        # Ограничиваем 15 строками максимум
        lines = lines[:15]
        
        # Вычисляем высоту
        header_height = 100  # Аватарка + имя
        text_height = len(lines) * 26
        footer_height = 80   # "just now" + иконки + отступы
        padding = 50         # Верх и низ
        
        total_height = header_height + text_height + footer_height + padding
        img_height = total_height
        img_width = 600
        
        # Создаём изображение нужного размера
        img = Image.new('RGB', (img_width, img_height), color='#15202b')
        
        # Твит фон
        tweet_height = img_height - 50
        tweet_box = Image.new('RGB', (560, tweet_height), color='white')
        img.paste(tweet_box, (20, 25))
        
        draw = ImageDraw.Draw(img)
        
        # Аватарка
        avatar_size = 48
        avatar_x, avatar_y = 40, 45
        
        if avatar_path and os.path.exists(avatar_path):
            try:
                avatar_img = Image.open(avatar_path).convert('RGB')
                avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)
                
                mask = Image.new('L', (avatar_size, avatar_size), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)
                
                img.paste(avatar_img, (avatar_x, avatar_y), mask)
            except Exception as e:
                logging.error(f"Avatar error: {e}")
                draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill='#1d9bf0')
        else:
            draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill='#1d9bf0')
        
        # Имя и верификация
        draw.text((100, 50), "Donald J. Trump", font=font_name, fill='#0f1419')
        
        check_x, check_y = 270, 52
        draw.ellipse([check_x, check_y, check_x + 16, check_y + 16], fill='#1d9bf0')
        draw.text((check_x + 3, check_y - 1), "✓", font=font_username, fill='white')
        
        draw.text((100, 72), "@realDonaldTrump", font=font_username, fill='#536471')
        
        # Текст с эмоджи
        y_pos = 115
        
        with Pilmoji(img) as pilmoji:
            for line in lines:
                pilmoji.text((40, y_pos), line, font=font_text, fill='#0f1419')
                y_pos += 26
        
        # Время
        draw.text((40, y_pos + 20), "just now", font=font_username, fill='#536471')
        
        # Иконки внизу (динамическая позиция)
        icons_y = img_height - 45
        icon_color = '#536471'
        icon_size = 18
        
        # Reply
        x1 = 50
        draw.ellipse([x1, icons_y, x1 + icon_size, icons_y + icon_size], outline=icon_color, width=2)
        draw.polygon([(x1 + 3, icons_y + icon_size), (x1 + 3, icons_y + icon_size + 4), (x1 + 7, icons_y + icon_size)], fill=icon_color)
        
        # Retweet
        x2 = 140
        draw.line([(x2, icons_y + 6), (x2 + 14, icons_y + 6)], fill=icon_color, width=2)
        draw.polygon([(x2 + 14, icons_y + 3), (x2 + 18, icons_y + 6), (x2 + 14, icons_y + 9)], fill=icon_color)
        draw.line([(x2, icons_y + 12), (x2 + 14, icons_y + 12)], fill=icon_color, width=2)
        draw.polygon([(x2, icons_y + 9), (x2 - 4, icons_y + 12), (x2, icons_y + 15)], fill=icon_color)
        
        # Like
        x3 = 230
        draw.ellipse([x3, icons_y + 2, x3 + 7, icons_y + 9], outline=icon_color, width=2)
        draw.ellipse([x3 + 7, icons_y + 2, x3 + 14, icons_y + 9], outline=icon_color, width=2)
        draw.polygon([(x3, icons_y + 7), (x3 + 14, icons_y + 7), (x3 + 7, icons_y + 16)], outline=icon_color, width=2)
        
        # Share
        x4 = 320
        draw.rectangle([x4 + 3, icons_y + 8, x4 + 13, icons_y + 16], outline=icon_color, width=2)
        draw.line([(x4 + 8, icons_y + 8), (x4 + 8, icons_y + 2)], fill=icon_color, width=2)
        draw.polygon([(x4 + 5, icons_y + 4), (x4 + 8, icons_y), (x4 + 11, icons_y + 4)], fill=icon_color)
        
        # Bookmark
        x5 = 410
        draw.rectangle([x5, icons_y + 2, x5 + 12, icons_y + 18], outline=icon_color, width=2)
        draw.polygon([(x5, icons_y + 18), (x5 + 6, icons_y + 14), (x5 + 12, icons_y + 18)], fill=icon_color)
        
        # Сохраняем
        img.save(output_path)
        
        logging.info(f"Trump tweet created: {img_width}x{img_height}, {len(lines)} lines")
        return os.path.exists(output_path)
        
    except Exception as e:
        logging.error(f"Tweet image error: {e}", exc_info=True)
        return False


# ---------------- ФУНКЦИИ: ОБРАБОТКА МЕДИА ----------------

def extract_first_frame(video_path: str, output_jpg: str) -> bool:
    """Достаем 1 кадр"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_jpg
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    return os.path.exists(output_jpg) and os.path.getsize(output_jpg) > 0

def build_layout_params(base_w, base_h, text, for_video=False):
    """Создает фон с рамкой и текстом"""
    target_w, target_h = base_w, base_h

    max_side = 720 if for_video else 1024

    if max(target_w, target_h) > max_side:
        ratio = max_side / max(target_w, target_h)
        target_w = int(target_w * ratio)
        target_h = int(target_h * ratio)

    if for_video:
        target_w = (target_w // 2) * 2
        target_h = (target_h // 2) * 2

    pad_top = 40
    pad_side = 40
    gap_to_text = 50
    gap_after_text = 40

    total_w = target_w + pad_side * 2

    font_size = max(20, int(total_w / 12))
    font = get_unicode_font(font_size) if has_emoji(text) else get_font(font_size)

    temp_img = Image.new("RGB", (1, 1))
    lines = fit_text(text, font, total_w - 20, temp_img)

    text_block_h = len(lines) * (font_size + 10)
    pad_bottom = gap_to_text + text_block_h + gap_after_text

    total_h = target_h + pad_top + pad_bottom
    
    # === ДОБАВЬ ЭТО ===
    # Округляем до чётных для видео
    if for_video:
        total_w = (total_w // 2) * 2
        total_h = (total_h // 2) * 2
    # === КОНЕЦ ===

    canvas = Image.new("RGB", (total_w, total_h), "black")
    draw = ImageDraw.Draw(canvas)

    # Рамка
    border = 2
    draw.rectangle(
        [(pad_side - 5, pad_top - 5),
         (pad_side + target_w + 4, pad_top + target_h + 4)],
        outline="white", width=border
    )

    # Рисуем текст с эмоджи
    y_text = pad_top + target_h + gap_to_text
    
    with Pilmoji(canvas) as pilmoji:
        for line in lines:
            bbox = pilmoji.getsize(line, font=font)
            line_w = bbox[0]
            x_text = (total_w - line_w) / 2
            pilmoji.text((int(x_text), int(y_text)), line, font=font, fill="white")
            y_text += font_size + 10

    return canvas, target_w, target_h, pad_side, pad_top


def create_demotivator_image(img_path, text, output_path, is_avatar=False, effect=None):
    """Создаёт демотиватор из картинки"""
    try:
        orig = Image.open(img_path).convert("RGBA")

        if is_avatar or max(orig.size) < 300:
            orig = orig.resize((600, 600), Image.Resampling.LANCZOS)

        # Применяем эффект
        if effect == 'invert':
            temp_path = img_path + "_temp.png"
            orig.save(temp_path)
            if apply_invert(temp_path, temp_path):
                orig = Image.open(temp_path).convert("RGBA")
            try:
                os.remove(temp_path)
            except:
                pass
        elif effect == 'vintage':
            temp_path = img_path + "_temp.png"
            orig.save(temp_path)
            if apply_vintage(temp_path, temp_path):
                orig = Image.open(temp_path).convert("RGBA")
            try:
                os.remove(temp_path)
            except:
                pass

        bg, t_w, t_h, p_x, p_y = build_layout_params(orig.width, orig.height, text, for_video=False)

        orig = orig.resize((t_w, t_h), Image.Resampling.LANCZOS)

        bg_rgba = bg.convert("RGBA")
        bg_rgba.paste(orig, (p_x, p_y), orig)

        bg_rgba.convert("RGB").save(output_path, quality=95)
        return True
    except Exception as e:
        logging.error(f"Image error: {e}", exc_info=True)
        return False

def convert_tgs_to_mp4_simple(tgs_path: str, output_mp4: str) -> bool:
    """Конвертация TGS через lottie + ffmpeg"""
    logging.info(f"TGS conversion started: {tgs_path} -> {output_mp4}")
    
    try:
        import gzip
        import json
        import tempfile
        import shutil
        from lottie import parsers
        from lottie.exporters.cairo import export_png
        
        logging.info("Libraries imported successfully")
        
        # Распаковываем
        with gzip.open(tgs_path, 'rb') as f:
            data = json.load(f)
            logging.info("TGS file unpacked")
            anim = parsers.tgs.parse_tgs(data)
            logging.info(f"Animation parsed: duration={anim.out_point/anim.frame_rate}s")
        
        temp_dir = tempfile.mkdtemp()
        logging.info(f"Temp dir created: {temp_dir}")
        
        try:
            # Рендерим кадры
            fps = 30
            duration = anim.out_point / anim.frame_rate
            frame_count = int(duration * fps)
            
            logging.info(f"Rendering {frame_count} frames at {fps} fps...")
            
            for i in range(min(frame_count, 90)):  # Макс 3 сек
                if i % 10 == 0:
                    logging.info(f"Rendering frame {i}/{frame_count}")
                
                t = (i / fps) * anim.frame_rate
                frame_path = f"{temp_dir}/{i:04d}.png"
                export_png(anim, frame_path, t, 512, 512)
            
            logging.info("All frames rendered, starting ffmpeg...")
            
            # Собираем в MP4
            cmd = [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", f"{temp_dir}/%04d.png",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-t", "3",
                output_mp4
            ]
            result = subprocess.run(cmd, capture_output=True, check=False)
            
            if result.returncode != 0:
                logging.error(f"FFmpeg error: {result.stderr.decode()}")
                return False
            
            logging.info(f"TGS conversion completed: {output_mp4}")
            return os.path.exists(output_mp4) and os.path.getsize(output_mp4) > 1000
            
        finally:
            logging.info(f"Cleaning up temp dir: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        logging.error(f"TGS mp4 error: {e}", exc_info=True)
        return False

def convert_tgs_to_mp4(tgs_path: str, output_path: str) -> bool:
    """Конвертирует TGS стикер в MP4"""
    try:
        import gzip
        import json
        
        # Распаковываем TGS в JSON
        json_path = tgs_path.replace('.tgs', '.json')
        with gzip.open(tgs_path, 'rb') as f_in:
            with open(json_path, 'w') as f_out:
                json.dump(json.load(f_in), f_out)
        
        # Конвертируем через ffmpeg с lottie filter (если есть)
        # Или просто делаем из превью видео
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=white:s=512x512:d=3",
            "-vf", f"drawtext=text='Animated Sticker':fontsize=48:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-t", "3",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, check=False)
        
        # Cleanup
        if os.path.exists(json_path):
            os.remove(json_path)
        
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        
    except Exception as e:
        logging.error(f"TGS conversion error: {e}")
        return False

def create_demotivator_video(vid_path, text, output_path):
    """Создает видео-демотиватор"""
    frame_path = vid_path + ".jpg"
    bg_path = vid_path + "_bg.png"

    try:
        logging.info(f"Video demotivator: input={vid_path}, output={output_path}")
        
        if not extract_first_frame(vid_path, frame_path):
            logging.error("Failed to extract first frame")
            return False

        frame = Image.open(frame_path)
        w, h = frame.size
        logging.info(f"Video dimensions: {w}x{h}")

        bg, t_w, t_h, p_x, p_y = build_layout_params(w, h, text, for_video=True)
        bg.save(bg_path)
        logging.info(f"Background created: {t_w}x{t_h}, offset: ({p_x}, {p_y})")

        filter_complex = (
            f"[1:v]scale={t_w}:{t_h}[vid];"
            f"[0:v][vid]overlay={p_x}:{p_y}:shortest=1"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", bg_path,
            "-i", vid_path,
            "-filter_complex", filter_complex,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-t", "30",
            output_path
        ]

        logging.info("Starting ffmpeg with command: " + " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, check=False)

        if result.returncode != 0:
            logging.error(f"FFmpeg failed with code {result.returncode}")
            logging.error(f"FFmpeg stderr: {result.stderr.decode()}")
            return False

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            logging.info(f"Output file created: {output_path}, size: {size} bytes")
            
            if size > 1000:
                return True
            else:
                logging.error(f"Output file too small: {size} bytes")
                return False
        else:
            logging.error("Output file not created")
            return False

    except Exception as e:
        logging.error(f"Video error: {e}", exc_info=True)
        return False
    finally:
        for f in [frame_path, bg_path]:
            if os.path.exists(f): 
                try:
                    os.remove(f)
                except:
                    pass


# ---------------- ФУНКЦИИ: ЭМОДЗИ-ПАКИ ----------------

def calculate_grid_size(width: int, height: int, user_grid: str = None) -> tuple:
    """
    Определяет оптимальный размер сетки на основе соотношения сторон
    и предпочтений пользователя.

    Args:
        width: ширина изображения
        height: высота изображения
        user_grid: опциональный размер из команды ("4x4", "5x5")

    Returns:
        tuple (cols, rows) - количество колонок и строк
    """
    # Если пользователь указал размер, используем его
    if user_grid and 'x' in user_grid.lower():
        try:
            parts = user_grid.lower().replace(' ', '').split('x')
            cols, rows = int(parts[0]), int(parts[1])
            if 2 <= cols <= 10 and 2 <= rows <= 10 and cols * rows <= 50:
                logging.info(f"Using user-specified grid: {cols}x{rows}")
                return (cols, rows)
        except Exception as e:
            logging.warning(f"Failed to parse user grid '{user_grid}': {e}")

    # Автоматический выбор на основе соотношения сторон
    aspect_ratio = width / height

    if 0.9 <= aspect_ratio <= 1.1:  # Почти квадратное
        grid = (5, 5) if width >= 500 else (4, 4)
    elif aspect_ratio > 1.5:  # Широкое
        grid = (6, 4) if width >= 600 else (5, 3)
    elif aspect_ratio < 0.67:  # Высокое
        grid = (4, 6) if height >= 600 else (3, 5)
    else:  # Промежуточное
        grid = (4, 4)

    logging.info(f"Auto-selected grid {grid[0]}x{grid[1]} for {width}x{height} (aspect {aspect_ratio:.2f})")
    return grid


async def split_image_to_grid(image_path: str, cols: int, rows: int, output_dir: str) -> list:
    """
    Нарезает изображение на сетку и возвращает пути к частям.

    Args:
        image_path: путь к исходному изображению
        cols: количество колонок
        rows: количество строк
        output_dir: директория для сохранения частей

    Returns:
        list путей к частям (в порядке слева-направо, сверху-вниз)
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        cell_width = width // cols
        cell_height = height // rows

        parts = []
        for row in range(rows):
            for col in range(cols):
                left = col * cell_width
                top = row * cell_height
                right = left + cell_width
                bottom = top + cell_height

                # Обрезаем часть
                cell = img.crop((left, top, right, bottom))

                # Масштабируем до 100x100
                cell = cell.resize((100, 100), Image.Resampling.LANCZOS)

                # Сохраняем как WEBP
                part_path = f"{output_dir}/part_{row}_{col}.webp"
                cell.save(part_path, "WEBP", quality=95)
                parts.append(part_path)

                logging.debug(f"Created image part {row},{col}: {part_path}")

        logging.info(f"Split image into {len(parts)} parts ({cols}x{rows})")
        return parts

    except Exception as e:
        logging.error(f"Error splitting image: {e}", exc_info=True)
        return []


async def split_video_to_grid(video_path: str, cols: int, rows: int, output_dir: str) -> list:
    """
    Нарезает видео на сетку и возвращает пути к WEBM частям.

    1. Получаем размеры видео через ffprobe
    2. Для каждой ячейки сетки:
       - Вырезаем область через crop filter
       - Масштабируем до 100x100
       - Конвертируем в WEBM (VP9, без аудио, до 3 сек)

    Returns:
        list путей к WEBM частям
    """
    try:
        # Получаем размеры видео
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logging.error(f"ffprobe failed: {result.stderr}")
            return []

        try:
            width, height = map(int, result.stdout.strip().split(','))
        except:
            logging.error(f"Failed to parse video dimensions: {result.stdout}")
            return []

        logging.info(f"Video dimensions: {width}x{height}")

        cell_width = width // cols
        cell_height = height // rows

        parts = []
        for row in range(rows):
            for col in range(cols):
                x = col * cell_width
                y = row * cell_height

                output_path = f"{output_dir}/part_{row}_{col}.webm"

                # ffmpeg команда для вырезки и конвертации
                cmd = [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-t", "3",  # Обрезаем до 3 секунд
                    "-vf", f"crop={cell_width}:{cell_height}:{x}:{y},scale=100:100",
                    "-c:v", "libvpx-vp9",
                    "-b:v", "150k",
                    "-an",  # Без аудио
                    "-pix_fmt", "yuva420p",
                    "-auto-alt-ref", "0",  # Важно для custom emoji
                    output_path
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode == 0 and os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    if file_size > 256 * 1024:  # Больше 256 KB
                        logging.warning(f"Part {row},{col} is too large: {file_size} bytes")
                    parts.append(output_path)
                    logging.debug(f"Created video part {row},{col}: {output_path} ({file_size} bytes)")
                else:
                    logging.error(f"Failed to create video part {row},{col}: {result.stderr}")

        logging.info(f"Split video into {len(parts)} parts ({cols}x{rows})")
        return parts

    except subprocess.TimeoutExpired:
        logging.error("Video splitting timeout")
        return []
    except Exception as e:
        logging.error(f"Error splitting video: {e}", exc_info=True)
        return []


async def create_custom_emoji_pack(bot_instance, user_id: int, parts: list, is_video: bool = False) -> str:
    """
    Создает custom emoji sticker set из частей.

    Args:
        bot_instance: экземпляр бота
        user_id: ID пользователя
        parts: список путей к файлам (WEBP или WEBM)
        is_video: True если видео, False если статичные

    Returns:
        короткое имя пака для ссылки t.me/addemoji/<name>
    """
    from aiogram.types import BufferedInputFile, InputSticker
    import time

    try:
        # Генерируем уникальное имя пака
        timestamp = int(time.time())
        bot_info = await bot_instance.me()
        bot_username = bot_info.username

        pack_name = f"emoji_{user_id}_{timestamp}_by_{bot_username}"
        pack_title = f"Emoji Pack {timestamp}"

        logging.info(f"Creating custom emoji pack: {pack_name}")

        # Создаем InputSticker объекты
        stickers = []
        emoji_map = ["🟦", "🟩", "🟥", "🟧", "🟨", "🟪", "⬜", "⬛", "🔵", "🟫",
                     "🔴", "🟢", "🟡", "🟣", "🟤", "⚫", "⚪", "🔶", "🔷", "🔸"]

        for i, part_path in enumerate(parts):
            try:
                with open(part_path, "rb") as f:
                    file_data = f.read()

                file_size = len(file_data)
                logging.debug(f"Loading part {i}: {file_size} bytes")

                # Проверка размера
                if is_video and file_size > 256 * 1024:
                    logging.warning(f"Part {i} exceeds 256KB limit: {file_size} bytes")

                filename = f"part_{i}.webm" if is_video else f"part_{i}.webp"

                sticker = InputSticker(
                    sticker=BufferedInputFile(file_data, filename=filename),
                    emoji_list=[emoji_map[i % len(emoji_map)]],
                    format="video" if is_video else "static"
                )
                stickers.append(sticker)

            except Exception as e:
                logging.error(f"Failed to prepare sticker {i}: {e}")

        if not stickers:
            raise Exception("No stickers prepared")

        logging.info(f"Prepared {len(stickers)} stickers, creating pack...")

        # Создаем стикер-пак
        result = await bot_instance.create_new_sticker_set(
            user_id=user_id,
            name=pack_name,
            title=pack_title,
            stickers=stickers,
            sticker_type="custom_emoji",
        )

        if result:
            logging.info(f"Custom emoji pack created successfully: {pack_name}")
            return pack_name
        else:
            raise Exception("create_new_sticker_set returned False")

    except Exception as e:
        logging.error(f"Error creating custom emoji pack: {e}", exc_info=True)
        raise


# ---------------- ХЕНДЛЕРЫ ----------------

# === TENET FUNCTIONS ===

def mirror_image(img_path: str, output_path: str) -> bool:
    """Mirror an image horizontally."""
    try:
        img = Image.open(img_path)
        mirrored = img.transpose(Image.FLIP_LEFT_RIGHT)
        if mirrored.mode == "RGBA":
            mirrored = mirrored.convert("RGB")
        mirrored.save(output_path, "JPEG", quality=95)
        logging.info(f"Mirrored image saved to {output_path}")
        return True
    except Exception as e:
        logging.error(f"Mirror image error: {e}", exc_info=True)
        return False


def reverse_video(vid_path: str, output_path: str) -> bool:
    """Reverse a video or GIF (play backwards)."""
    try:
        max_duration = 30
        cmd = [
            "ffmpeg", "-y",
            "-i", vid_path,
            "-t", str(max_duration),
            "-vf", "reverse",
            "-af", "areverse",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path
        ]
        logging.info(f"Reversing video: {vid_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            cmd_no_audio = [
                "ffmpeg", "-y",
                "-i", vid_path,
                "-t", str(max_duration),
                "-vf", "reverse",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-an",
                "-movflags", "+faststart",
                "-pix_fmt", "yuv420p",
                output_path
            ]
            result = subprocess.run(cmd_no_audio, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logging.error(f"FFmpeg reverse error: {result.stderr}")
                return False
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logging.info(f"Reversed video saved to {output_path}")
            return True
        return False
    except subprocess.TimeoutExpired:
        logging.error("Video reverse timeout")
        return False
    except Exception as e:
        logging.error(f"Reverse video error: {e}", exc_info=True)
        return False


def reverse_text(text: str) -> str:
    """Reverse text fully."""
    return text[::-1]


def reverse_audio(audio_path: str, output_path: str) -> bool:
    """Reverse audio file."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-af", "areverse",
            "-c:a", "libopus",
            "-b:a", "64k",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logging.error(f"Audio reverse error: {result.stderr}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logging.error(f"Reverse audio error: {e}")
        return False


def reverse_pdf(pdf_path: str, output_path: str) -> bool:
    """Reverse PDF page order."""
    try:
        from PyPDF2 import PdfReader, PdfWriter
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        for page in reversed(reader.pages):
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        logging.info(f"Reversed PDF: {len(reader.pages)} pages")
        return True
    except ImportError:
        logging.error("PyPDF2 not installed")
        return False
    except Exception as e:
        logging.error(f"PDF reverse error: {e}")
        return False


@dp.message(Command("tenet"))
async def cmd_tenet(message: Message):
    """Handle /tenet command - reverse media, text, audio, PDF."""
    if not message.reply_to_message:
        await message.reply(
            "🔄 *Команда /tenet* — переворачивает всё!\n\n"
            "Ответь на сообщение:\n"
            "• 📝 Текст → ьтаробо|текст наоборот\n"
            "• 🖼 Фото → зеркало\n"
            "• 🎬 Видео/GIF → задом наперёд\n"
            "• 🎤 Голосовое → реверс аудио\n"
            "• 🎵 Аудио → реверс\n"
            "• 📄 PDF → страницы в обратном порядке\n"
            "• 📍 Локация → антипод (противоположная точка Земли)",
            parse_mode="Markdown"
        )
        return

    replied = message.reply_to_message
    status_msg = await message.reply("⏳ Обрабатываем в стиле Тенет...")

    input_file = f"temp_tenet_in_{message.message_id}"
    output_file = f"temp_tenet_out_{message.message_id}"

    try:
        # === LOCATION (Antipode) ===
        if replied.location:
            lat = replied.location.latitude
            lon = replied.location.longitude

            # Calculate antipodal point (opposite side of Earth)
            anti_lat = -lat
            anti_lon = lon + 180 if lon <= 0 else lon - 180

            await status_msg.edit_text(
                f"🌍 Исходная точка: {lat:.6f}, {lon:.6f}\n"
                f"🔄 Пробиваем Землю насквозь...\n"
                f"🌏 Антипод: {anti_lat:.6f}, {anti_lon:.6f}"
            )

            await message.answer_location(latitude=anti_lat, longitude=anti_lon)
            return

        # === TEXT ===
        elif replied.text:
            reversed_text = reverse_text(replied.text)
            await status_msg.edit_text(f"🔄 {reversed_text}")
            return

        # === PHOTO ===
        elif replied.photo:
            input_file += ".jpg"
            output_file += ".jpg"
            await bot.download(replied.photo[-1], destination=input_file)
            await status_msg.edit_text("⏳ Зеркалим изображение...")
            success = await run_in_thread(lambda: mirror_image(input_file, output_file))
            if success:
                await message.answer_photo(FSInputFile(output_file))
            else:
                await message.answer("Ошибка при зеркалировании")

        # === VOICE ===
        elif replied.voice:
            input_file += ".ogg"
            output_file += ".ogg"
            await bot.download(replied.voice, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем голосовое...")
            success = await run_in_thread(lambda: reverse_audio(input_file, output_file))
            if success:
                await message.answer_voice(FSInputFile(output_file))
            else:
                await message.answer("Ошибка при реверсе голосового")

        # === AUDIO ===
        elif replied.audio:
            ext = ".mp3"
            if replied.audio.file_name:
                ext = os.path.splitext(replied.audio.file_name)[1] or ".mp3"
            input_file += ext
            output_file += ".ogg"
            await bot.download(replied.audio, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем аудио...")
            success = await run_in_thread(lambda: reverse_audio(input_file, output_file))
            if success:
                await message.answer_audio(FSInputFile(output_file), title="Reversed Audio")
            else:
                await message.answer("Ошибка при реверсе аудио")

        # === DOCUMENT ===
        elif replied.document:
            mime = replied.document.mime_type or ""
            fname = replied.document.file_name or "file"
            
            # PDF
            if "pdf" in mime or fname.lower().endswith(".pdf"):
                input_file += ".pdf"
                output_file += ".pdf"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем страницы PDF...")
                success = await run_in_thread(lambda: reverse_pdf(input_file, output_file))
                if success:
                    await message.answer_document(FSInputFile(output_file, filename="reversed.pdf"))
                else:
                    await message.answer("Ошибка при реверсе PDF (нужен PyPDF2)")
            
            # Image document
            elif "image" in mime:
                input_file += ".jpg"
                output_file += ".jpg"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Зеркалим изображение...")
                success = await run_in_thread(lambda: mirror_image(input_file, output_file))
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка при зеркалировании")
            
            # Text file
            elif "text" in mime or fname.endswith((".txt", ".md", ".json", ".xml", ".html", ".css", ".js", ".py")):
                input_file += ".txt"
                await bot.download(replied.document, destination=input_file)
                with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                reversed_content = reverse_text(content)
                if len(reversed_content) > 4000:
                    output_file += ".txt"
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(reversed_content)
                    await message.answer_document(FSInputFile(output_file, filename=f"reversed_{fname}"))
                else:
                    await message.answer(f"```\n{reversed_content[:4000]}\n```", parse_mode="Markdown")

            # Video document
            elif "video" in mime:
                can_process, count = check_server_load()
                if not can_process:
                    await send_overload_message(message, count)
                    return
                input_file += ".mp4"
                output_file += ".mp4"
                await bot.download(replied.document, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем видео...")
                success = await run_in_thread(lambda: reverse_video(input_file, output_file))
                if success:
                    await message.answer_video(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка при реверсе видео")

            else:
                await message.answer(f"Не знаю как перевернуть этот тип файла: {mime}")

        # === VIDEO ===
        elif replied.video:
            can_process, count = check_server_load()
            if not can_process:
                await send_overload_message(message, count)
                return
            input_file += ".mp4"
            output_file += ".mp4"
            await bot.download(replied.video, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем время...")
            success = await run_in_thread(lambda: reverse_video(input_file, output_file))
            if success:
                await message.answer_video(FSInputFile(output_file))
            else:
                await message.answer("Ошибка при реверсе видео")

        # === ANIMATION (GIF) ===
        elif replied.animation:
            can_process, count = check_server_load()
            if not can_process:
                await send_overload_message(message, count)
                return
            input_file += ".mp4"
            output_file += ".mp4"
            await bot.download(replied.animation, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем GIF...")
            success = await run_in_thread(lambda: reverse_video(input_file, output_file))
            if success:
                await message.answer_animation(FSInputFile(output_file))
            else:
                await message.answer("Ошибка при реверсе GIF")

        # === VIDEO NOTE ===
        elif replied.video_note:
            can_process, count = check_server_load()
            if not can_process:
                await send_overload_message(message, count)
                return
            input_file += ".mp4"
            output_file += ".mp4"
            await bot.download(replied.video_note, destination=input_file)
            await status_msg.edit_text("⏳ Переворачиваем кружок...")
            success = await run_in_thread(lambda: reverse_video(input_file, output_file))
            if success:
                await message.answer_animation(FSInputFile(output_file))
            else:
                await message.answer("Ошибка при реверсе видео")

        # === STICKER ===
        elif replied.sticker:
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path
            
            if file_path and file_path.endswith(".webm"):
                can_process, count = check_server_load()
                if not can_process:
                    await send_overload_message(message, count)
                    return
                input_file += ".webm"
                output_file += ".mp4"
                await bot.download(replied.sticker, destination=input_file)
                await status_msg.edit_text("⏳ Переворачиваем видео-стикер...")
                success = await run_in_thread(lambda: reverse_video(input_file, output_file))
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка при реверсе стикера")
            elif file_path and (file_path.endswith(".webp") or file_path.endswith(".png")):
                input_file += ".webp"
                output_file += ".jpg"
                await bot.download(replied.sticker, destination=input_file)
                await status_msg.edit_text("⏳ Зеркалим стикер...")
                success = await run_in_thread(lambda: mirror_image(input_file, output_file))
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка при зеркалировании стикера")
            elif file_path and file_path.endswith(".tgs"):
                await message.answer("TGS стикеры пока не поддерживаются для /tenet")
            else:
                await message.answer("Неизвестный тип стикера")

        else:
            await message.answer("Не могу обработать этот тип сообщения")

    except Exception as e:
        logging.error(f"Tenet command error: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке")
    finally:
        try:
            await status_msg.delete()
        except:
            pass
        for f in [input_file, output_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass

# === END TENET ===

@dp.message(Command("emoji"))
async def cmd_emoji(message: Message):
    """Обработчик команды /emoji - создание custom emoji sticker packs"""
    import tempfile
    import shutil

    # Парсим команду для извлечения размера сетки
    parts = message.text.split()
    user_grid = parts[1] if len(parts) > 1 else None

    # Проверяем reply
    if not message.reply_to_message:
        await message.reply(
            "🎨 **Команда /emoji** — создать эмодзи-пак из картинки/видео\n\n"
            "**Использование:**\n"
            "1️⃣ Ответь на фото/видео/GIF командой /emoji\n"
            "2️⃣ Или отправь медиа с подписью /emoji\n\n"
            "**Опции:**\n"
            "• /emoji — автоматический выбор сетки\n"
            "• /emoji 4x4 — сетка 4x4 (16 эмодзи)\n"
            "• /emoji 5x5 — сетка 5x5 (25 эмодзи)\n\n"
            "**Лимиты:**\n"
            "• Видео/GIF: до 3 секунд, до 10 МБ\n"
            "• Максимум 50 эмодзи в паке",
            parse_mode="Markdown"
        )
        return

    replied = message.reply_to_message
    status_msg = await message.reply("⏳ Создаю эмодзи-пак...")

    # Создаём временную директорию
    temp_dir = tempfile.mkdtemp(prefix="emoji_pack_")
    input_file = None
    output_parts = []

    try:
        # === ПРОВЕРКА ТИПА МЕДИА ===
        is_video = False
        is_image = False

        if replied.photo:
            is_image = True
            input_file = f"{temp_dir}/input.jpg"
            await bot.download(replied.photo[-1], destination=input_file)
            logging.info("Processing photo for emoji pack")

        elif replied.document:
            mime = replied.document.mime_type or ""
            if "image" in mime:
                is_image = True
                ext = ".jpg"
                if "png" in mime:
                    ext = ".png"
                elif "webp" in mime:
                    ext = ".webp"
                input_file = f"{temp_dir}/input{ext}"
                await bot.download(replied.document, destination=input_file)
                logging.info(f"Processing image document for emoji pack: {mime}")
            elif "video" in mime or "gif" in mime:
                is_video = True
                input_file = f"{temp_dir}/input.mp4"
                await bot.download(replied.document, destination=input_file)
                logging.info(f"Processing video document for emoji pack: {mime}")
            else:
                await status_msg.edit_text("❌ Неподдерживаемый тип файла")
                return

        elif replied.video or replied.animation:
            is_video = True
            input_file = f"{temp_dir}/input.mp4"
            obj = replied.video if replied.video else replied.animation
            await bot.download(obj, destination=input_file)
            logging.info("Processing video/animation for emoji pack")

        elif replied.sticker:
            # Проверяем тип стикера
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path

            if file_path and file_path.endswith('.webm'):
                is_video = True
                input_file = f"{temp_dir}/input.webm"
                await bot.download(replied.sticker, destination=input_file)
                logging.info("Processing video sticker for emoji pack")
            elif file_path and (file_path.endswith('.webp') or file_path.endswith('.png')):
                is_image = True
                input_file = f"{temp_dir}/input.webp"
                await bot.download(replied.sticker, destination=input_file)
                logging.info("Processing static sticker for emoji pack")
            elif file_path and file_path.endswith('.tgs'):
                await status_msg.edit_text("❌ TGS стикеры пока не поддерживаются.\nИспользуйте статичные стикеры или видео.")
                return
            else:
                await status_msg.edit_text("❌ Неизвестный тип стикера")
                return

        else:
            await status_msg.edit_text("❌ Отправь фото, видео, GIF или стикер")
            return

        # === ОПРЕДЕЛЯЕМ РАЗМЕР СЕТКИ ===
        if is_image:
            img = Image.open(input_file)
            width, height = img.size
            cols, rows = calculate_grid_size(width, height, user_grid)
        elif is_video:
            # Получаем размеры видео
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                input_file
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                await status_msg.edit_text("❌ Ошибка обработки видео")
                return

            try:
                width, height = map(int, result.stdout.strip().split(','))
                cols, rows = calculate_grid_size(width, height, user_grid)
            except:
                await status_msg.edit_text("❌ Не удалось определить размеры видео")
                return

        total_emojis = cols * rows
        if total_emojis > 50:
            await status_msg.edit_text(f"❌ Слишком большая сетка: {cols}x{rows} = {total_emojis} эмодзи\nМаксимум 50 эмодзи в паке")
            return

        await status_msg.edit_text(f"⏳ Нарезаю на сетку {cols}x{rows} ({total_emojis} эмодзи)...")

        # === НАРЕЗКА ===
        if is_image:
            output_parts = await run_in_thread(
                lambda: asyncio.run(split_image_to_grid(input_file, cols, rows, temp_dir))
            )
        elif is_video:
            await status_msg.edit_text(f"⏳ Обрабатываю видео (может занять время)...")
            output_parts = await run_in_thread(
                lambda: asyncio.run(split_video_to_grid(input_file, cols, rows, temp_dir))
            )

        if not output_parts:
            await status_msg.edit_text("❌ Ошибка при нарезке медиа")
            return

        logging.info(f"Created {len(output_parts)} parts for emoji pack")
        await status_msg.edit_text(f"⏳ Создаю стикер-пак ({len(output_parts)} эмодзи)...")

        # === СОЗДАНИЕ СТИКЕР-ПАКА ===
        try:
            pack_name = await create_custom_emoji_pack(
                bot,
                message.from_user.id,
                output_parts,
                is_video=is_video
            )

            # Формируем ссылку на пак
            pack_link = f"https://t.me/addemoji/{pack_name}"

            await status_msg.edit_text(
                f"✅ **Эмодзи-пак создан!**\n\n"
                f"🎨 Сетка: {cols}x{rows}\n"
                f"📦 Эмодзи: {len(output_parts)}\n"
                f"🎬 Тип: {'Анимированные' if is_video else 'Статичные'}\n\n"
                f"🔗 [Добавить пак]({pack_link})\n\n"
                f"Теперь вы можете использовать эти эмодзи в любом чате!",
                parse_mode="Markdown",
                disable_web_page_preview=False
            )

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Failed to create emoji pack: {error_msg}")

            if "STICKERSET_INVALID" in error_msg:
                await status_msg.edit_text("❌ Ошибка создания пака. Попробуйте уменьшить размер сетки.")
            elif "name is already" in error_msg.lower():
                await status_msg.edit_text("❌ Пак с таким именем уже существует. Попробуйте ещё раз.")
            else:
                await status_msg.edit_text(f"❌ Ошибка создания пака: {error_msg[:100]}")

    except Exception as e:
        logging.error(f"Emoji pack creation error: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка: {str(e)[:100]}")

    finally:
        # Очистка временных файлов
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logging.info(f"Cleaned up temp dir: {temp_dir}")
        except Exception as e:
            logging.error(f"Failed to cleanup temp dir: {e}")

        try:
            await status_msg.delete()
        except:
            pass


@dp.message(Command("trump", "трамп"))
async def cmd_trump(message: Message):
    """Переписать текст в стиле Трампа с картинкой"""
    
    # Из реплая
    if message.reply_to_message:
        original = message.reply_to_message.text or message.reply_to_message.caption
        if not original:
            await message.answer("Нет текста для трампификации")
            return
        user_id = message.reply_to_message.from_user.id
    # Из текста команды
    else:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование:\n/trump текст\nили ответь на сообщение")
            return
        original = parts[1]
        user_id = message.from_user.id
    
    status_msg = await message.reply("⏳ MAKING AMERICA GREAT AGAIN...")
    
    output_path = f"/root/bots/trump_tweet_{message.message_id}.png"
    avatar_path = f"/root/bots/trump_avatar_{message.message_id}.jpg"
    
    try:
        # Трампифицируем текст
        trumpified = await run_in_thread(lambda: trumpify_text(original))
        
        # Скачиваем аватарку
        await download_user_avatar(user_id, avatar_path)
        
        # Создаём картинку
        if await run_in_thread(lambda: create_trump_tweet_image(trumpified, output_path, avatar_path)):
            await message.answer_photo(
                FSInputFile(output_path),
                caption="🇺🇸 **TRUMP MODE ACTIVATED** 🇺🇸"
            )
        else:
            # Fallback на текст
            await message.answer(f"🇺🇸 **TRUMP MODE ACTIVATED** 🇺🇸\n\n{trumpified}")
        
    except Exception as e:
        logging.error(f"Trump command error: {e}", exc_info=True)
        await message.answer("FAKE NEWS! Ошибка трампификации 🇺🇸")
    
    finally:
        try:
            await status_msg.delete()
        except:
            pass
        
        # Очистка
        for f in [output_path, avatar_path]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass


@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
**Демотиватор Бот с цветными эмоджи 🎨**

**Команды:**
/d [текст] — создать демотиватор
/dd [текст] — то же самое
/д [текст] — русский вариант
/дд [текст] — русский вариант

**Эффекты:**
/inv [текст] — инверсия цветов
/vin [текст] — винтажная обработка

**Эмодзи-паки:**
/emoji — нарезать картинку/видео на эмодзи
/emoji 4x4 — сетка 4x4 (16 эмодзи)
/emoji 5x5 — сетка 5x5 (25 эмодзи)

**Другие команды:**
/tenet — переворот медиа (зеркало, реверс, антипод)
/trump — переписать текст в стиле Трампа

**Как использовать:**

1. Ответь командой на любое сообщение
2. После команды можно добавить текст
3. Эмоджи отображаются цветными! 🔥💯😎

**Примеры:**

/d — обычный демотиватор
/d мой текст 🚀 — с текстом и эмоджи
/inv — инверсия
/vin винтаж — винтажный эффект
/emoji — создать эмодзи-пак из картинки

**Особенности:**
- Цветные эмоджи через Twemoji
- Эффекты только для изображений
- Видео до 30 секунд
- Эмодзи-паки: любое разрешение, автоматическая сетка
"""
    await message.answer(help_text)

async def get_random_fallback_image(message_id: int) -> str:
    """Возвращает путь к рандомной заглушке: 123.png или стикер из пака"""
    try:
        # Список стикерпаков
        sticker_packs = [
            "sp031fedcbc4e438a8984a76e28c81713d_by_stckrRobot",
            "sp70cc950ed11089c18703860f5419aa27_by_stckrRobot",
            "sp5e6aec1cfbfc458c3166a9bbb80e4bf2_by_stckrRobot",
            "sp40ba02f59a1bd3f647b89178bf001829_by_stckrRobot",
            "JowFaderMitch_by_fStikBot",
            "pa_PzVnv4JOlkayQOj8W8LQ_by_SigStick20Bot",
            "OninationSquadAnimStickers",
            "PerdunMorjopa_by_fStikBot",
            "vDfCbyQ_by_achestickbot",
            "woodcum",
            "ShooBeDoo",
            "pchellovod85434_by_sportsmem_bot",
            "pchellovod7569_by_sportsmem_bot",
            "l8da2e0PmqVX0fArOJ7A5vlCc_by_literalmebot",
            "vdyrky",
            "pchellovod78493_by_sportsmem_bot",
            "f_weyjrjak_896383854_by_fStikBot",
            "pchellovod84489_by_Kinopoisk_Memes_bot",
            "Hiroon_RafGrassetti",
            "with_love_for_680300712_by_msu_hub_bot",
            "with_love_for_1001414584186_by_msu_hub_bot",
            "dedobemebykot",
            "igorvikhorkov_by_fStikBot",
            "horsestikerisfiu_by_fStikBot",
            "with_love_for_1001615989157_by_msu_hub_bot",
            "peepee_poopoo",
            "Miss_evidence",
            "set_2900_by_makestick3_bot",
            "GamingYarAnimated",
            "Fortrach",
            "mihalpalich",
            "tapok2",
            "airplanshaha",
            "GospodJesus",
            "bttvAni",
            "Harry_Potter_stickers",
            "gifki",
            "skzkz",
            "Eto_golub_eeZee",
            "BoysClub",
            "anegen_2",
            "electroeditions",
            "NonameR",
            "tashkent_stickers",
            "KAZINO",
            "uktambek",
            "ChineseCubes",
            "BEPHO",
            "ButlerOstin",
            "Mosamapack",
            "Moral_condemnation",
            "als_ohuenny",
            "Stickers_ebat",
            "RESTORENATURALORDER",
            "blobbyyyy",
            "VitaminParty",
            "pollitrovaya",
            "LMTBZH_people",
            "sp760f8c50d2ff59b6231022bcb81e1e66_by_stckrRobot",
            "IgorIvanovich_by_fStikBot",
            "blyaskolko",
            "f_ws1afq2_1216979815_by_fStikBot",
            "modern2",
            "Rudiemoji",
            "AtiltDitalMasus_by_fStikBot",
            "kulhaker_salt",
            "peepee_poopoo",
            "ozero",
            "stkrchat",
            "putinsmoney",
            "daEntoOn",
            "PBaas",
            "best_ecosystem",
            "Yellowboi",
            "vsrpron",
            "set_2900_by_makestick3_bot",
            "ultrarjombav2",
        ]
        
        # С вероятностью 2% берём 123.png, иначе стикер
        if random.random() < 0.02 and os.path.exists(FALLBACK_AVATAR):
            output_file = f"temp_fallback_{message_id}.png"
            copy2(FALLBACK_AVATAR, output_file)
            logging.info("Using 123.png as fallback")
            return output_file
        
        # Выбираем случайный пак (БЕЗ КЕША)
        pack_name = random.choice(sticker_packs)
        logging.info(f"Getting random sticker from pack: {pack_name}")
        
        # Получаем стикерпак
        sticker_set = await bot.get_sticker_set(pack_name)
        
        if not sticker_set.stickers:
            logging.warning("Sticker pack is empty, using 123.png")
            if os.path.exists(FALLBACK_AVATAR):
                output_file = f"temp_fallback_{message_id}.png"
                copy2(FALLBACK_AVATAR, output_file)
                return output_file
            return None
        
        # Берём ЛЮБОЙ стикер (включая анимированные и видео)
        sticker = random.choice(sticker_set.stickers)
        logging.info(f"Selected sticker: animated={sticker.is_animated}, video={sticker.is_video}")
        
        # Определяем расширение
        if sticker.is_animated:
            # TGS стикеры - пока берём превью
            if sticker.thumbnail:
                output_file = f"temp_fallback_{message_id}.jpg"
                await bot.download(sticker.thumbnail, destination=output_file)
            else:
                # Нет превью - берём другой
                return await get_random_fallback_image(message_id)
        elif sticker.is_video:
            output_file = f"temp_fallback_{message_id}.webm"
            await bot.download(sticker, destination=output_file)
        else:
            output_file = f"temp_fallback_{message_id}.webp"
            await bot.download(sticker, destination=output_file)
        
        logging.info(f"Downloaded sticker: {output_file}")
        return output_file
        
    except Exception as e:
        logging.error(f"Failed to get random fallback: {e}", exc_info=True)
        
        # Fallback на 123.png
        if os.path.exists(FALLBACK_AVATAR):
            output_file = f"temp_fallback_{message_id}.png"
            copy2(FALLBACK_AVATAR, output_file)
            return output_file
        
        return None

# @dp.message(F.sticker)
# async def handle_sticker_direct(message: Message):
#     """Прямая обработка стикеров без команды"""
#     logging.info(f"Direct sticker received: is_animated={message.sticker.is_animated}")
    
#     status_msg = await message.reply("⏳ Делаем демотиватор...")
    
#     input_file = f"temp_in_{message.message_id}"
#     output_file = f"temp_out_{message.message_id}.jpg"
#     final_caption = "..."
    
#     try:
#         if message.sticker.is_animated:
#             logging.info("Processing TGS sticker")
#             input_file += ".tgs"
#             await bot.download(message.sticker, destination=input_file)
            
#             video_file = input_file.replace(".tgs", "_anim.mp4")
#             await status_msg.edit_text("⏳ Рендерим анимацию...")
            
#             logging.info(f"Converting TGS: {input_file} -> {video_file}")
#             success = await run_in_thread(lambda: convert_tgs_to_mp4_simple(input_file, video_file))
            
#             if success:
#                 output_file = f"temp_out_{message.message_id}.mp4"
#                 if await run_in_thread(lambda: create_demotivator_video(video_file, final_caption, output_file)):
#                     await message.answer_animation(FSInputFile(output_file))
#                 else:
#                     await message.answer("Ошибка обработки")
                
#                 if os.path.exists(video_file):
#                     os.remove(video_file)
#             else:
#                 # Fallback на превью
#                 if message.sticker.thumbnail:
#                     input_file = input_file.replace(".tgs", ".jpg")
#                     await bot.download(message.sticker.thumbnail, destination=input_file)
#                     success = await run_in_thread(lambda: create_demotivator_image(input_file, final_caption, output_file, is_avatar=True))
#                     if success:
#                         await message.answer_photo(FSInputFile(output_file))
        
#         elif message.sticker.is_video:
#             # Видео-стикер
#             input_file += ".webm"
#             await bot.download(message.sticker, destination=input_file)
#             output_file = f"temp_out_{message.message_id}.mp4"
            
#             if await run_in_thread(lambda: create_demotivator_video(input_file, final_caption, output_file)):
#                 await message.answer_animation(FSInputFile(output_file))
        
#         else:
#             # Обычный WEBP
#             input_file += ".webp"
#             await bot.download(message.sticker, destination=input_file)
#             success = await run_in_thread(lambda: create_demotivator_image(input_file, final_caption, output_file, is_avatar=True))
#             if success:
#                 await message.answer_photo(FSInputFile(output_file))
    
#     except Exception as e:
#         logging.error(f"Direct sticker error: {e}", exc_info=True)
#         await message.answer("Ошибка обработки")
    
#     finally:
#         try:
#             await status_msg.delete()
#         except:
#             pass
        
#         # Cleanup
#         for f in os.listdir("."):
#             if f.startswith(f"temp_in_{message.message_id}") or \
#                f.startswith(f"temp_out_{message.message_id}"):
#                 try:
#                     os.remove(f)
#                 except:
#                     pass
                    
@dp.message(F.photo | F.document)
async def handle_media_with_caption(message: Message):
    """Обработка картинок/документов с командой в подписи"""
    caption = message.caption or ""

    cmd_prefixes = ("/d ", "/dd ", "/д ", "/дд ", "/inv ", "/vin ", "/emoji ")
    cmd_list = ["/d", "/dd", "/д", "/дд", "/inv", "/vin", "/emoji"]

    is_cmd = caption.lower().startswith(tuple(cmd_prefixes)) or caption.lower() in cmd_list

    if not is_cmd:
        return

    # === ОБРАБОТКА /emoji ===
    if caption.lower().startswith("/emoji"):
        # Создаём фейковое reply сообщение для переиспользования логики cmd_emoji
        # Сохраняем оригинальное сообщение как reply_to_message
        fake_message = message
        fake_message.reply_to_message = message
        fake_message.text = caption  # Используем caption как text для парсинга

        # Вызываем обработчик emoji
        await cmd_emoji(fake_message)
        return
    
    # === ДОБАВЬ ПРОВЕРКУ НАГРУЗКИ ===
    can_process, process_count = check_server_load()
    if not can_process:
        logging.warning(f"Server overloaded ({process_count} processes), rejecting media from {message.from_user.id}")
        await send_overload_message(message, process_count)
        return
    # === КОНЕЦ ПРОВЕРКИ ===

        
    
    logging.info(f"Media with command caption: {caption[:50]}")
    
    # Определяем эффект
    effect = None
    if caption.lower().startswith("/inv"):
        effect = "invert"
    elif caption.lower().startswith("/vin"):
        effect = "vintage"
    
    # Извлекаем текст для демотиватора
    parts = caption.split(maxsplit=1)
    final_caption = parts[1] if len(parts) > 1 else "..."
    
    status_msg = await message.reply("⏳ Делаем демотиватор...")
    
    input_file = f"temp_in_{message.message_id}.jpg"
    output_file = f"temp_out_{message.message_id}.jpg"
    
    try:
        # Скачиваем фото или документ
        if message.photo:
            await bot.download(message.photo[-1], destination=input_file)
        else:
            await bot.download(message.document, destination=input_file)
        
        logging.info(f"Processing media with caption: '{final_caption}'")
        
        # Создаём демотиватор
        success = await run_in_thread(lambda: create_demotivator_image(
            input_file, final_caption, output_file, effect=effect
        ))
        
        if success:
            await message.answer_photo(FSInputFile(output_file))
        else:
            await message.answer("Ошибка обработки")
    
    except Exception as e:
        logging.error(f"Media caption handler error: {e}", exc_info=True)
        await message.answer("Произошла ошибка")
    
    finally:
        try:
            await status_msg.delete()
        except:
            pass
        
        # Cleanup
        for f in [input_file, output_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass


@dp.message(F.text)
async def handle_command(message: Message):
    txt = message.text.strip()
    cmd_prefixes = ("/d ", "/dd ", "/д ", "/дд ", "/inv ", "/vin ")
    cmd_list = ["/d", "/dd", "/д", "/дд", "/inv", "/vin"]
    
    is_cmd = txt.lower() in cmd_list or any(txt.lower().startswith(p) for p in cmd_prefixes)
    if not is_cmd:
        return

    # === ДОБАВЬ ПРОВЕРКУ НАГРУЗКИ ===
    can_process, process_count = check_server_load()
    if not can_process:
        logging.warning(f"Server overloaded ({process_count} processes), rejecting request from {message.from_user.id}")
        await send_overload_message(message, process_count)
        return
    # === КОНЕЦ ПРОВЕРКИ ===
    
    # === ЗАМЕНИ ЭТУ ПРОВЕРКУ ===
    if not message.reply_to_message:
        logging.info("Command without reply - using random sticker")
        
        parts = txt.split(maxsplit=1)
        
        # Если текст не указан - генерируем AI
        if len(parts) == 1:
            caption = generate_demotivator_text()
            logging.info(f"Using AI-generated caption: {caption}")
        else:
            caption = parts[1]
        
        # Определяем эффект
        effect = None
        if txt.lower().startswith("/inv"):
            effect = "invert"
        elif txt.lower().startswith("/vin"):
            effect = "vintage"
        
        status_msg = await message.reply("⏳ Выбираю стикер...")
        
        input_file = f"temp_in_{message.message_id}"
        output_file = f"temp_out_{message.message_id}.jpg"
        
        try:
            # Получаем рандомный стикер (гарантированно стикер, не 123.png)
            fallback_file = await get_random_fallback_image(message.message_id)
            
            if not fallback_file:
                await message.answer("Не удалось получить стикер")
                await status_msg.delete()
                return
            
            logging.info(f"Using fallback file: {fallback_file}")
            
            # Проверяем тип файла
            if fallback_file.endswith('.webm'):
                # Видео-стикер -> видео демотиватор
                output_file = f"temp_out_{message.message_id}.mp4"
                success = await run_in_thread(lambda: create_demotivator_video(
                    fallback_file, caption, output_file
                ))
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка обработки")
            else:
                # Статичный стикер -> фото демотиватор
                success = await run_in_thread(lambda: create_demotivator_image(
                    fallback_file, caption, output_file, is_avatar=True, effect=effect
                ))
                if success:
                    await message.answer_photo(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка обработки")
        
        except Exception as e:
            logging.error(f"Solo command error: {e}", exc_info=True)
            await message.answer("Ошибка при получении стикера")
        
        finally:
            try:
                await status_msg.delete()
            except:
                pass
            
            # Cleanup - удаляем ВСЕ временные файлы
            cleanup_patterns = [
                f"temp_fallback_{message.message_id}*",
                f"temp_in_{message.message_id}*",
                f"temp_out_{message.message_id}*",
            ]
            
            import glob
            for pattern in cleanup_patterns:
                for file_path in glob.glob(pattern):
                    try:
                        os.remove(file_path)
                        logging.debug(f"Cleaned up: {file_path}")
                    except Exception as e:
                        logging.debug(f"Failed to cleanup {file_path}: {e}")
        
        return  # Выходим из функции
    
    # Дальше идёт обычная логика с reply_to_message
    effect = None
    if txt.lower().startswith("/inv"):
        effect = "invert"
    elif txt.lower().startswith("/vin"):
        effect = "vintage"
    
    caption = ""
    parts = txt.split(maxsplit=1)
    if len(parts) > 1:
        caption = parts[1]
    
    replied = message.reply_to_message

    # === ДОБАВЬ ЭТИ ЛОГИ ===
    logging.info(f"Command handler: replied message type check")
    logging.info(f"  video={replied.video is not None}")
    logging.info(f"  animation={replied.animation is not None}")
    logging.info(f"  video_note={replied.video_note is not None}")
    logging.info(f"  sticker={replied.sticker is not None}")
    if replied.sticker:
        logging.info(f"  sticker.is_animated={replied.sticker.is_animated}")
        logging.info(f"  sticker.is_video={replied.sticker.is_video}")
    logging.info(f"  photo={replied.photo is not None}")
    logging.info(f"  document={replied.document is not None}")
    logging.info(f"  text={replied.text is not None}")

    # === КОНЕЦ ЛОГОВ ===


    status_msg = await message.reply("⏳ Делаем...")

    input_file = f"temp_in_{message.message_id}"
    output_file = f"temp_out_{message.message_id}.jpg"
    text_img_file = f"temp_text_{message.message_id}.jpg"

    try:
        final_caption = caption if caption else "..."
        # === ВИДЕО-КРУЖКИ ===
        if replied.video_note:
            logging.info("Branch: video_note")
            input_file += ".mp4"
            output_file = f"temp_out_{message.message_id}.mp4"
            
            await bot.download(replied.video_note, destination=input_file)
            await status_msg.edit_text("⏳ Обрабатываем кружок...")
            
            success = await run_in_thread(lambda: create_demotivator_video(input_file, final_caption, output_file))
            
            if success:
                await message.answer_animation(FSInputFile(output_file))
            else:
                await message.answer("Ошибка обработки кружка")
        
        # === ВИДЕО ===
        elif replied.video or replied.animation:
            logging.info("Branch: video/animation")
            if effect:
                await message.answer("Эффекты работают только с изображениями")
                await status_msg.delete()
                return
                
            if replied.video:
                obj, ext = replied.video, ".mp4"
            elif replied.animation:
                obj, ext = replied.animation, ".mp4"
            else:
                obj, ext = replied.sticker, ".webm"

            input_file += ext
            output_file = f"temp_out_{message.message_id}.mp4"

            await bot.download(obj, destination=input_file)
            await status_msg.edit_text("⏳ Рендерим видео...")

            success = await run_in_thread(lambda: create_demotivator_video(input_file, final_caption, output_file))

            if success:
                await message.answer_animation(FSInputFile(output_file))
            else:
                await message.answer("Ошибка видео")

        # === КАРТИНКИ ===
        elif replied.photo or (replied.document and replied.document.mime_type and "image" in replied.document.mime_type):
            logging.info("Branch: photo/image_document")
            obj = replied.photo[-1] if replied.photo else replied.document

            input_file += ".jpg"
            await bot.download(obj, destination=input_file)
            
            success = await run_in_thread(lambda: create_demotivator_image(input_file, final_caption, output_file, effect=effect))

            if success:
                await message.answer_photo(FSInputFile(output_file))
            else:
                await message.answer("Ошибка фото")

        # === СТИКЕРЫ ===
        elif replied.sticker:
            logging.info(f"Branch: sticker (is_video={replied.sticker.is_video})")
            
            # Получаем информацию о файле
            file_info = await bot.get_file(replied.sticker.file_id)
            file_path = file_info.file_path
            logging.info(f"Sticker file_path: {file_path}")
            
            # TGS стикеры имеют расширение .tgs
            if file_path and file_path.endswith('.tgs'):
                logging.info("Processing TGS sticker (animated)")
                input_file += ".tgs"
                await bot.download(replied.sticker, destination=input_file)
                logging.info(f"TGS downloaded to {input_file}")
                
                video_file = input_file.replace(".tgs", "_anim.mp4")
                await status_msg.edit_text("⏳ Рендерим анимацию...")
                
                logging.info(f"Converting TGS: {input_file} -> {video_file}")
                success = await run_in_thread(lambda: convert_tgs_to_mp4_simple(input_file, video_file))
                logging.info(f"TGS conversion result: {success}")
                
                if success:
                    output_file = f"temp_out_{message.message_id}.mp4"
                    if await run_in_thread(lambda: create_demotivator_video(video_file, final_caption, output_file)):
                        await message.answer_animation(FSInputFile(output_file))
                    else:
                        await message.answer("Ошибка обработки")
                    
                    if os.path.exists(video_file):
                        os.remove(video_file)
                else:
                    # Fallback на превью
                    if replied.sticker.thumbnail:
                        input_file = input_file.replace(".tgs", ".jpg")
                        await bot.download(replied.sticker.thumbnail, destination=input_file)
                        success = await run_in_thread(lambda: create_demotivator_image(input_file, final_caption, output_file, is_avatar=True, effect=effect))
                        if success:
                            await message.answer_photo(FSInputFile(output_file))
            
            # Видео-стикеры (.webm)
            elif file_path and file_path.endswith('.webm'):
                logging.info("Processing WEBM video sticker")
                if effect:
                    await message.answer("Эффекты работают только с изображениями")
                    await status_msg.delete()
                    return
                
                input_file += ".webm"
                output_file = f"temp_out_{message.message_id}.mp4"
                await bot.download(replied.sticker, destination=input_file)
                
                logging.info("Creating video demotivator from WEBM")
                success = await run_in_thread(lambda: create_demotivator_video(input_file, final_caption, output_file))
                logging.info(f"WEBM demotivator result: {success}, file exists: {os.path.exists(output_file)}")
                
                if success:
                    await message.answer_animation(FSInputFile(output_file))
                else:
                    await message.answer("Ошибка обработки видео стикера")
            
            # Обычные WEBP стикеры
            else:
                logging.info("Processing static WEBP sticker")
                input_file += ".webp"
                await bot.download(replied.sticker, destination=input_file)
                success = await run_in_thread(lambda: create_demotivator_image(input_file, final_caption, output_file, is_avatar=True, effect=effect))
                if success:
                    await message.answer_photo(FSInputFile(output_file))

        # === ТЕКСТ ===
        elif replied.text:
            text_content = replied.text.strip()
            user_id = replied.from_user.id
            avatar_available = False
            
            try:
                photos = await bot.get_user_profile_photos(user_id, limit=1)
                
                if photos.total_count > 0:
                    input_file += ".jpg"
                    await bot.download(photos.photos[0][-1], destination=input_file)
                    avatar_available = True
                else:
                    # Используем рандомную заглушку вместо 123.png
                    fallback_file = await get_random_fallback_image(message.message_id)
                    if fallback_file:
                        input_file = fallback_file
                        avatar_available = True
            except:
                # Используем рандомную заглушку
                fallback_file = await get_random_fallback_image(message.message_id)
                if fallback_file:
                    input_file = fallback_file
                    avatar_available = True
            
            if avatar_available:
                text_for_demot = caption if caption else text_content
                success = await run_in_thread(lambda: create_demotivator_image(input_file, text_for_demot, output_file, is_avatar=True, effect=effect))
                if success:
                    await message.answer_photo(FSInputFile(output_file))
            else:
                # Генерируем из текста
                text_for_caption = caption if caption else "..."
                if await run_in_thread(lambda: generate_text_image(text_content, text_img_file)):
                    if await run_in_thread(lambda: create_demotivator_image(text_img_file, text_for_caption, output_file, effect=effect)):
                        await message.answer_photo(FSInputFile(output_file))

        # === FALLBACK ===
        else:
            fallback_text = caption if caption else "Unknown"
            if await run_in_thread(lambda: generate_text_image(fallback_text, text_img_file)):
                if await run_in_thread(lambda: create_demotivator_image(text_img_file, fallback_text, output_file, effect=effect)):
                    await message.answer_photo(FSInputFile(output_file))

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        await message.answer("Ошибка обработки")
    finally:
        try:
            await status_msg.delete()
        except:
            pass
        
        # Cleanup
        for f in os.listdir("."):
            if f.startswith(f"temp_in_{message.message_id}") or \
               f.startswith(f"temp_out_{message.message_id}") or \
               f.startswith(f"temp_text_{message.message_id}") or \
               f.startswith(f"temp_fallback_{message.message_id}"):
                try:
                    os.remove(f)
                except:
                    pass

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot with emoji support started!")
    cleanup_old_temp_files()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
