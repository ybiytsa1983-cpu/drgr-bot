import os
import asyncio
import logging
import aiofiles
from typing import List, Dict
from collections import defaultdict, deque
from dotenv import load_dotenv
from PIL import Image, ImageFilter, ImageEnhance, ImageSequence
from moviepy.editor import VideoFileClip

# Библиотеки aiogram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Библиотека Hugging Face
from huggingface_hub import InferenceClient

# Загрузка переменных окружения
load_dotenv()

# Получение токенов и настроек
BOT_TOKEN = os.getenv("BOT_TOKEN")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

if not BOT_TOKEN:
    raise ValueError("Добавьте BOT_TOKEN в .env файл.")
if not HUGGINGFACE_API_KEY:
    raise ValueError("Добавьте HUGGINGFACE_API_KEY в .env файл.")

# Директории
PHOTOS_DIR = os.getenv("PHOTOS_DIR", "photos")
VIDEOS_DIR = os.getenv("VIDEOS_DIR", "videos")
GALLERY_DIR = os.getenv("GALLERY_DIR", "gallery")
FRAME_DIR = os.getenv("FRAME_DIR", "frames")
COLLAGE_DIR = os.getenv("COLLAGE_DIR", "collages")
FRAME_OVERLAY_DIR = os.getenv("FRAME_OVERLAY_DIR", "frame_overlays")
LOG_FILE = os.getenv("LOG_FILE", "actions.log")

# Числовые настройки
MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB", 15))
MAX_COMMENTS = int(os.getenv("MAX_COMMENTS", 20))

# Создание директорий
for d in [PHOTOS_DIR, VIDEOS_DIR, GALLERY_DIR, FRAME_DIR, COLLAGE_DIR, FRAME_OVERLAY_DIR]:
    os.makedirs(d, exist_ok=True)

# Инициализация клиента Hugging Face
client = InferenceClient(api_key=HUGGINGFACE_API_KEY)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("FSMMediaBot")

# Базовые данные
EFFECTS = ["blur", "sharpen", "bw", "brightness", "contrast", "pixelate", "glitch", "sepia"]
gallery_db: Dict[str, Dict] = defaultdict(lambda: {"likes": 0, "comments": deque(maxlen=MAX_COMMENTS)})
user_last_media: Dict[int, str] = {}

# FSM состояния
class MediaStates(StatesGroup):
    waiting_for_frame = State()
    waiting_for_collage_photos = State()
    waiting_for_video_trim_params = State()
    waiting_for_video_file = State()

# --- ФУНКЦИИ ОБРАБОТКИ ИЗОБРАЖЕНИЙ ---
def is_valid_file_size(file_size: int) -> bool:
    return file_size <= MAX_SIZE_MB * 1024 * 1024

def apply_effect(image: Image.Image, effect: str) -> Image.Image:
    if effect == "blur":
        return image.filter(ImageFilter.BLUR)
    if effect == "sharpen":
        enhancer = ImageEnhance.Sharpness(image)
        return enhancer.enhance(2.0)
    if effect == "bw":
        return image.convert("L").convert("RGB")
    if effect == "brightness":
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(1.5)
    if effect == "contrast":
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(1.5)
    if effect == "pixelate":
        w, h = image.size
        small = image.resize((max(1, w // 16), max(1, h // 16)), Image.NEAREST)
        return small.resize((w, h), Image.NEAREST)
    if effect == "glitch":
        data = list(image.getdata())
        import random
        random.shuffle(data)
        img = Image.new(image.mode, image.size)
        img.putdata(data)
        return img
    if effect == "sepia":
        width, height = image.size
        img = image.copy()
        pixels = img.load()
        for x in range(width):
            for y in range(height):
                r, g, b = pixels[x, y]
                nr = min(int(r * 0.393 + g * 0.769 + b * 0.189), 255)
                ng = min(int(r * 0.349 + g * 0.686 + b * 0.168), 255)
                nb = min(int(r * 0.272 + g * 0.534 + b * 0.131), 255)
                pixels[x, y] = (nr, ng, nb)
        return img
    raise ValueError(f"Unknown effect: {effect}")

def add_frame_to_photo(base_path: str, frame_path: str, output_path: str) -> None:
    base = Image.open(base_path).convert("RGBA")
    frame = Image.open(frame_path).convert("RGBA").resize(base.size)
    combined = Image.alpha_composite(base, frame)
    combined.convert("RGB").save(output_path)

def create_collage_from_paths(paths: List[str], output_path: str, cols: int = 2, thumb_size: tuple = None) -> None:
    images = [Image.open(p).convert("RGBA") for p in paths]
    if not images:
        raise ValueError("No images for collage")
    if thumb_size is None:
        thumb_size = images[0].size
    w, h = thumb_size
    cols = min(cols, max(1, len(images)))
    rows = (len(images) + cols - 1) // cols
    collage_w = cols * w
    collage_h = rows * h
    collage = Image.new("RGBA", (collage_w, collage_h), (255, 255, 255, 0))
    for idx, im in enumerate(images):
        im = im.resize((w, h))
        x = (idx % cols) * w
        y = (idx // cols) * h
        collage.paste(im, (x, y))
    collage.convert("RGB").save(output_path)

# --- ОБРАБОТЧИКИ КОМАНД ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):

”`python import logging import os import random import asyncio from collections import defaultdict, deque from typing import Dict, List import requests import aiofiles from dotenv import load_dotenv from PIL import Image, ImageFilter, ImageEnhance from moviepy.editor import VideoFileClip
load_dotenv()
Загрузка переменных окружения
BOT_TOKEN = os.getenv(“BOT_TOKEN”) HUGGINGFACE_TOKEN = os.getenv(“HUGGINGFACE_TOKEN”) # Токен для API Hugging Face PHOTOS_DIR = os.getenv(“PHOTOS_DIR”, “photos”) VIDEOS_DIR = os.getenv(“VIDEOS_DIR”, “videos”) GALLERY_DIR = os.getenv(“GALLERY_DIR”, “gallery”) FRAME_DIR = os.getenv(“FRAME_DIR”, “frames”) COLLAGE_DIR = os.getenv(“COLLAGE_DIR”, “collages”) FRAME_OVERLAY_DIR = os.getenv(“FRAME_OVERLAY_DIR”, “frame_overlays”) LOG_FILE = os.getenv(“LOG_FILE”, “actions.log”) MAX_SIZE_MB = int(os.getenv(“MAX_SIZE_MB”, 15)) MAX_COMMENTS = 20
assert BOT_TOKEN, “Add BOT_TOKEN to your .env file.” assert HUGGINGFACE_TOKEN, “Add HUGGINGFACE_TOKEN to your .env file for AI assistant.”
Настройка логирования
logging.basicConfig( level=logging.INFO, filename=LOG_FILE, filemode=“a”, format=“%(asctime)s | %(levelname)s | %(message)s”, ) logger = logging.getLogger(“FSMMediaBot”)
Создание необходимых директорий
for d in [PHOTOS_DIR, VIDEOS_DIR, GALLERY_DIR, FRAME_DIR, COLLAGE_DIR, FRAME_OVERLAY_DIR]: os.makedirs(d, exist_ok=True)
Доступные эффекты для изображений
EFFECTS = [“blur”, “sharpen”, “bw”, “brightness”, “contrast”, “pixelate”, “glitch”, “sepia”]
База данных для галереи и последнее загруженное медиа пользователя
gallery_db: Dict[str, Dict] = defaultdict(lambda: {“likes”: 0, “comments”: deque(maxlen=MAX_COMMENTS)}) user_last_media: Dict[int, str] = {}
Проверка размера файла
def is_valid_file_size(file_size: int) -> bool: return file_size <= MAX_SIZE_MB * 1024 * 1024
Применение эффектов к изображению
def apply_effect(image: Image.Image, effect: str) -> Image.Image: try: if effect == “blur”: return image.filter(ImageFilter.BLUR) if effect == “sharpen”: enhancer = ImageEnhance.Sharpness(image) return enhancer.enhance(2.0) if effect == “bw”: return image.convert(“L”).convert(“RGB”) if effect == “brightness”: enhancer = ImageEnhance.Brightness(image) return enhancer.enhance(1.5) if effect == “contrast”: enhancer = ImageEnhance.Contrast(image) return enhancer.enhance(1.5) if effect == “pixelate”: w, h = image.size small = image.resize((max(1, w // 16), max(1, h // 16)), Image.Resampling.NEAREST) return small.resize((w, h), Image.Resampling.NEAREST) if effect == “glitch”: data = list(image.getdata()) random.shuffle(data) img = Image.new(image.mode, image.size) img.putdata(data) return img if effect == “sepia”: width, height = image.size img = image.copy() pixels = img.load() for x in range(width): for y in range(height): r, g, b = pixels[x, y] nr = min(int(r * 0.393 + g * 0.769 + b * 0.189), 255) ng = min(int(r * 0.349 + g * 0.686 + b * 0.168), 255) nb = min(int(r * 0.272 + g * 0.534 + b * 0.131), 255) pixels[x, y] = (nr, ng, nb) return img raise ValueError(f”Unknown effect: {effect}“) except Exception as e: logger.error(f”Error applying effect {effect}: {e}“) raise
Добавление рамки к фото
def add_frame_to_photo(base_path: str, frame_path: str, output_path: str) -> None: try: base = Image.open(base_path).convert(“RGBA”) frame = Image.open(frame_path).convert(“RGBA”).resize(base.size) combined = Image.alpha_composite(base, frame) combined.convert(“RGB”).save(output_path) except Exception as e: logger.error(f”Error adding frame: {e}“) raise
Создание коллажа
def create_collage_from_paths(paths: List[str], output_path: str, cols: int = 2, thumb_size: tuple = None) -> None: try: images = [Image.open(p).convert(“RGBA”) for p in paths] if not images: raise ValueError(“No images for collage”) if thumb_size is None: thumb_size = images[0].size w, h = thumb_size cols = min(cols, max(1, len(images))) rows = (len(images) + cols - 1) // cols collage_w = cols * w collage_h = rows * h collage = Image.new(“RGBA”, (collage_w, collage_h), (255, 255, 255, 0)) for idx, im in enumerate(images): im = im.resize((w, h)) x = (idx % cols) * w

y = (idx // cols) * h collage.paste(im, (x, y)) collage.convert(“RGB”).save(output_path) except Exception as e: logger.error(f”Error creating collage: {e}“) raise
Инициализация бота и диспетчера для aiogram 3.x
from aiogram import Bot, Router from aiogram.filters import Command, CommandStart from aiogram.types import Message, CallbackQuery, FSInputFile from aiogram.fsm.context import FSMContext from aiogram.fsm.state import State, StatesGroup from aiogram.types.inline_keyboard_button import InlineKeyboardButton from aiogram.types.inline_keyboard_markup import InlineKeyboardMarkup
bot = Bot(token=BOT_TOKEN) router = Router()
Состояния для FSM
class MediaStates(StatesGroup): waiting_for_frame = State() waiting_for_collage_photos = State() waiting_for_video_trim_params = State() waiting_for_video_file = State() waiting_for_ai_request = State()
Функция для запроса к Hugging Face API (текстовая модель)
async def query_huggingface(prompt: str, model: str = “mistralai/Mistral-7B-Instruct-v0.3”) -> str: try: api_url = f”https://api-inference.huggingface.co/models/{model}” headers = {“Authorization”: f”Bearer {HUGGINGFACE_TOKEN}“} payload = {“inputs”: prompt, “parameters”: {“max_length”: 200}} response = await asyncio.to_thread(requests.post, api_url, headers=headers, json=payload) if response.status_code == 200: result = response.json() return result[0].get(“generated_text”, “Не удалось сгенерировать ответ.”) else: logger.error(f”Hugging Face API error: {response.status_code} - {response.text}“) return “Ошибка при обращении к ИИ. Попробуйте позже.” except Exception as e: logger.error(f”Error querying Hugging Face: {e}“) return f”Ошибка: {str(e)}”
Команда /start
@router.message(CommandStart()) async def cmd_start(message: Message): await message.answer( “Привет! Отправляйте фото/видео. Используйте команды:\n” “/frame - применить рамку к последнему фото\n” “/collage - создать коллаж (последовательная загрузка фото)\n” “/video_trim - обрезать видео (загрузка + ввод параметров)\n” “/ai - задать вопрос ИИ-ассистенту\n” “/help - помощь” )
Команда /help
@router.message(Command(“help”)) async def cmd_help(message: Message): await message.answer( “Команды:\n” “/frame — выбрать и применить рамку\n” “/collage — создать коллаж из нескольких фото\n” “/video_trim — обрезать видео\n” “/ai — задать вопрос ИИ-ассистенту\n” “/help — показать эту подсказку” )
Команда /ai для общения с ИИ
@router.message(Command(“ai”)) async def cmd_ai(message: Message, state: FSMContext): await message.answer(“Задайте ваш вопрос или запрос для ИИ-ассистента:”) await MediaStates.waiting_for_ai_request.set()
@router.message(state=MediaStates.waiting_for_ai_request) async def process_ai_request(message: Message, state: FSMContext): user_prompt = message.text await message.answer(“Обрабатываю ваш запрос, подождите…”) response = await query_huggingface(user_prompt) await message.answer(f”Ответ ИИ:\n{response}“) await state.clear()
Команда /frame
@router.message(Command(“frame”)) async def cmd_frame(message: Message, state: FSMContext): frames = [f for f in os.listdir(FRAME_DIR) if f.lower().endswith((“.png”, “.jpg”, “.webp”))] if not frames: await message.reply(“Нет доступных рамок. Добавьте изображения в папку frames”) return buttons = [[InlineKeyboardButton(text=f, callback_data=f”frame_select:{f}“)] for f in frames[:12]] kb = InlineKeyboardMarkup(inline_keyboard=buttons) await message.answer(“Выберите рамку для последнего фото:”, reply_markup=kb) await MediaStates.waiting_for_frame.set()
Обработка выбора рамки
@router.callback_query(lambda c: c.data.startswith(“frame_select:”)) async def callback_frame_select(query: CallbackQuery, state: FSMContext): frame_name = query.data.split(“:”, 1)[1] user_id = query.from_user.id base_path = user_last_media.get(user_id) if not base_path or not os.path.exists(base_path): await query.answer(“Отправьте сначала фото.”, show_alert=True) await state.clear() return frame_path = os.path.join(FRAME_DIR, frame_name) if not os.path.exists(frame_path): await query.answer(“Рамка не найдена.”, show_alert=True) await state.clear() return

out_path = os.path.join(PHOTOS_DIR, f”{user_id}framed{frame_name}“) try: add_frame_to_photo(base_path, frame_path, out_path) await bot.send_photo(user_id, FSInputFile(out_path), caption=f”Рамка {frame_name} применена”) await query.answer() logger.info(f”User {user_id} applied frame {frame_name}“) except Exception as e: logger.error(f”Ошибка применения рамки: {e}“) await query.answer(f”Ошибка: {e}“, show_alert=True) await state.clear()
Команда /collage
@router.message(Command(“collage”)) async def cmd_collage_start(message: Message, state: FSMContext): await state.update_data(collage_photos=[]) await message.answer(“Отправьте фото для коллажа (не более 6). Отправьте /done, когда закончите.”) await MediaStates.waiting_for_collage_photos.set()
Получение фото для коллажа
@router.message(content_types=[“photo”], state=MediaStates.waiting_for_collage_photos) async def collage_photo_receive(message: Message, state: FSMContext): photo = message.photo[-1] if not is_valid_file_size(photo.file_size): await message.reply(“Файл слишком большой, попробуйте меньшего размера.”) return file_info = await bot.get_file(photo.file_id) file_data = await bot.download_file(file_info.file_path) user_id = message.from_user.id save_path = os.path.join(PHOTOSDIR, f”collage{userid}{file_info.file_unique_id}.jpg”) async with aiofiles.open(save_path, “wb”) as f: await f.write(file_data.getvalue()) user_data = await state.get_data() photos = user_data.get(“collage_photos”, []) photos.append(save_path) await state.update_data(collage_photos=photos) await message.reply(f”Фото добавлено к коллажу. Всего: {len(photos)}“)
Завершение коллажа
@router.message(Command(“done”), state=MediaStates.waiting_for_collage_photos) async def collage_done(message: Message, state: FSMContext): user_data = await state.get_data() photos = user_data.get(“collage_photos”, []) if len(photos) < 2: await message.reply(“Минимум 2 фото для коллажа.”) return user_id = message.from_user.id output_path = os.path.join(COLLAGEDIR, f”collage{user_id}.jpg”) try: create_collage_from_paths(photos, output_path, cols=3) await message.reply_photo(FSInputFile(output_path), caption=“Коллаж готов!”) except Exception as e: logger.error(f”Ошибка создания коллажа: {e}“) await message.reply(“Ошибка при создании коллажа.”) await state.clear()
Команда /video_trim
@router.message(Command(“video_trim”)) async def cmd_video_trim(message: Message, state: FSMContext): await message.reply(“Отправьте видео, которое хотите обрезать.”) await MediaStates.waiting_for_video_file.set()
Получение видео
@router.message(content_types=[“video”], state=MediaStates.waiting_for_video_file) async def video_received(message: Message, state: FSMContext): video = message.video if not video or video.file_size <= 0: await message.reply(“Ошибка загрузки видео.”) return file_info = await bot.get_file(video.file_id) file_data = await bot.download_file(file_info.file_path) user_id = message.from_user.id save_path = os.path.join(VIDEOS_DIR, f”{userid}{file_info.file_unique_id}.mp4
