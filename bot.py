import os
import asyncio
import logging
import subprocess
import random
from pathlib import Path
from shutil import copy2

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
from pilmoji import Pilmoji

# ==========================================
# ⚠️ ВСТАВЬ СЮДА НОВЫЙ ТОКЕН
TOKEN = "8229829474:AAGCSU7jQlZVsxUB-dfZfHD5imuLMdL2irQ"
# ==========================================

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


# ---------------- ХЕНДЛЕРЫ ----------------

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

**Как использовать:**

1. Ответь командой на любое сообщение
2. После команды можно добавить текст
3. Эмоджи отображаются цветными! 🔥💯😎

**Примеры:**

/d — обычный демотиватор
/d мой текст 🚀 — с текстом и эмоджи
/inv — инверсия
/vin винтаж — винтажный эффект

**Особенности:**
- Цветные эмоджи через Twemoji
- Эффекты только для изображений
- Видео до 30 секунд
"""
    await message.answer(help_text)

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
    
    # Проверяем есть ли команда в начале подписи
    cmd_prefixes = ("/d ", "/dd ", "/д ", "/дд ", "/inv ", "/vin ")
    cmd_list = ["/d", "/dd", "/д", "/дд", "/inv", "/vin"]
    
    is_cmd = caption.lower().startswith(tuple(cmd_prefixes)) or caption.lower() in cmd_list
    
    if not is_cmd:
        return  # Игнорируем если нет команды
    
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
    if not message.reply_to_message:
        await message.reply("Ответь этой командой на любое сообщение")
        return
    
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
                elif os.path.exists(FALLBACK_AVATAR):
                    input_file += ".jpg"
                    copy2(FALLBACK_AVATAR, input_file)
                    avatar_available = True
            except:
                if os.path.exists(FALLBACK_AVATAR):
                    input_file += ".jpg"
                    copy2(FALLBACK_AVATAR, input_file)
                    avatar_available = True
            
            if avatar_available:
                text_for_demot = caption if caption else text_content
                success = await run_in_thread(lambda: create_demotivator_image(input_file, text_for_demot, output_file, is_avatar=True, effect=effect))
                if success:
                    await message.answer_photo(FSInputFile(output_file))
            else:
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
        
        for f in os.listdir("."):
            if f.startswith(f"temp_in_{message.message_id}") or \
               f.startswith(f"temp_out_{message.message_id}") or \
               f.startswith(f"temp_text_{message.message_id}"):
                try:
                    os.remove(f)
                except:
                    pass

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot with emoji support started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
