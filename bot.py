import asyncio
import logging
import os
import random
from collections import defaultdict, deque
from typing import Dict, List

import aiofiles
import requests
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
from moviepy.editor import VideoFileClip
from PIL import Image, ImageEnhance, ImageFilter

# Pillow ≥ 9.1 uses Image.Resampling; older versions use Image.NEAREST directly.
_NEAREST = getattr(Image, "Resampling", Image).NEAREST

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

if not BOT_TOKEN:
    raise ValueError("Add BOT_TOKEN to your .env file.")
if not HUGGINGFACE_API_KEY:
    raise ValueError("Add HUGGINGFACE_API_KEY to your .env file.")

PHOTOS_DIR = os.getenv("PHOTOS_DIR", "photos")
VIDEOS_DIR = os.getenv("VIDEOS_DIR", "videos")
GALLERY_DIR = os.getenv("GALLERY_DIR", "gallery")
FRAME_DIR = os.getenv("FRAME_DIR", "frames")
COLLAGE_DIR = os.getenv("COLLAGE_DIR", "collages")
FRAME_OVERLAY_DIR = os.getenv("FRAME_OVERLAY_DIR", "frame_overlays")
LOG_FILE = os.getenv("LOG_FILE", "actions.log")
MAX_SIZE_MB = int(os.getenv("MAX_SIZE_MB", 15))
MAX_COMMENTS = int(os.getenv("MAX_COMMENTS", 20))
MAX_FRAME_BUTTONS = int(os.getenv("MAX_FRAME_BUTTONS", 12))
COLLAGE_COLS = int(os.getenv("COLLAGE_COLS", 3))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", 500))

for _d in [PHOTOS_DIR, VIDEOS_DIR, GALLERY_DIR, FRAME_DIR, COLLAGE_DIR, FRAME_OVERLAY_DIR]:
    os.makedirs(_d, exist_ok=True)

client = InferenceClient(api_key=HUGGINGFACE_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("FSMMediaBot")

EFFECTS = ["blur", "sharpen", "bw", "brightness", "contrast", "pixelate", "glitch", "sepia"]
gallery_db: Dict[str, Dict] = defaultdict(
    lambda: {"likes": 0, "comments": deque(maxlen=MAX_COMMENTS)}
)
user_last_media: Dict[int, str] = {}


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class MediaStates(StatesGroup):
    waiting_for_frame = State()
    waiting_for_collage_photos = State()
    waiting_for_video_trim_params = State()
    waiting_for_video_file = State()
    waiting_for_ai_request = State()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def is_valid_file_size(file_size: int) -> bool:
    return file_size <= MAX_SIZE_MB * 1024 * 1024


def apply_effect(image: Image.Image, effect: str) -> Image.Image:
    try:
        if effect == "blur":
            return image.filter(ImageFilter.BLUR)
        if effect == "sharpen":
            return ImageEnhance.Sharpness(image).enhance(2.0)
        if effect == "bw":
            return image.convert("L").convert("RGB")
        if effect == "brightness":
            return ImageEnhance.Brightness(image).enhance(1.5)
        if effect == "contrast":
            return ImageEnhance.Contrast(image).enhance(1.5)
        if effect == "pixelate":
            w, h = image.size
            small = image.resize((max(1, w // 16), max(1, h // 16)), _NEAREST)
            return small.resize((w, h), _NEAREST)
        if effect == "glitch":
            data = list(image.getdata())
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
    except Exception as e:
        logger.error("Error applying effect %s: %s", effect, e)
        raise


def add_frame_to_photo(base_path: str, frame_path: str, output_path: str) -> None:
    try:
        base = Image.open(base_path).convert("RGBA")
        frame = Image.open(frame_path).convert("RGBA").resize(base.size)
        combined = Image.alpha_composite(base, frame)
        combined.convert("RGB").save(output_path)
    except Exception as e:
        logger.error("Error adding frame: %s", e)
        raise


def create_collage_from_paths(
    paths: List[str],
    output_path: str,
    cols: int = 2,
    thumb_size: tuple = None,
) -> None:
    try:
        images = [Image.open(p).convert("RGBA") for p in paths]
        if not images:
            raise ValueError("No images for collage")
        if thumb_size is None:
            thumb_size = images[0].size
        w, h = thumb_size
        cols = min(cols, max(1, len(images)))
        rows = (len(images) + cols - 1) // cols
        collage = Image.new("RGBA", (cols * w, rows * h), (255, 255, 255, 0))
        for idx, im in enumerate(images):
            im = im.resize((w, h))
            collage.paste(im, ((idx % cols) * w, (idx // cols) * h))
        collage.convert("RGB").save(output_path)
    except Exception as e:
        logger.error("Error creating collage: %s", e)
        raise


async def query_huggingface(
    prompt: str, model: str = "mistralai/Mistral-7B-Instruct-v0.3"
) -> str:
    try:
        api_url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}
        payload = {"inputs": prompt, "parameters": {"max_length": AI_MAX_TOKENS}}
        response = await asyncio.to_thread(
            requests.post, api_url, headers=headers, json=payload, timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            return result[0].get("generated_text", "Не удалось сгенерировать ответ.")
        logger.error("Hugging Face API error: %s - %s", response.status_code, response.text)
        return "Ошибка при обращении к ИИ. Попробуйте позже."
    except Exception as e:
        logger.error("Error querying Hugging Face: %s", e)
        return f"Ошибка: {e}"


# ---------------------------------------------------------------------------
# Bot and router
# ---------------------------------------------------------------------------

bot = Bot(token=BOT_TOKEN)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Отправляйте фото/видео. Используйте команды:\n"
        "/frame — применить рамку к последнему фото\n"
        "/collage — создать коллаж (последовательная загрузка фото)\n"
        "/video_trim — обрезать видео (загрузка + ввод параметров)\n"
        "/ai — задать вопрос ИИ-ассистенту\n"
        "/help — помощь"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/frame — выбрать и применить рамку\n"
        "/collage — создать коллаж из нескольких фото\n"
        "/video_trim — обрезать видео\n"
        "/ai — задать вопрос ИИ-ассистенту\n"
        "/help — показать эту подсказку"
    )


@router.message(Command("ai"))
async def cmd_ai(message: Message, state: FSMContext) -> None:
    await message.answer("Задайте ваш вопрос или запрос для ИИ-ассистента:")
    await state.set_state(MediaStates.waiting_for_ai_request)


@router.message(MediaStates.waiting_for_ai_request)
async def process_ai_request(message: Message, state: FSMContext) -> None:
    await message.answer("Обрабатываю ваш запрос, подождите…")
    response = await query_huggingface(message.text or "")
    await message.answer(f"Ответ ИИ:\n{response}")
    await state.clear()


@router.message(Command("frame"))
async def cmd_frame(message: Message, state: FSMContext) -> None:
    frames = [
        f for f in os.listdir(FRAME_DIR) if f.lower().endswith((".png", ".jpg", ".webp"))
    ]
    if not frames:
        await message.reply("Нет доступных рамок. Добавьте изображения в папку frames.")
        return
    buttons = [
        [InlineKeyboardButton(text=f, callback_data=f"frame_select:{f}")]
        for f in frames[:MAX_FRAME_BUTTONS]
    ]
    await message.answer(
        "Выберите рамку для последнего фото:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(MediaStates.waiting_for_frame)


@router.callback_query(lambda c: c.data.startswith("frame_select:"))
async def callback_frame_select(query: CallbackQuery, state: FSMContext) -> None:
    frame_name = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    base_path = user_last_media.get(user_id)
    if not base_path or not os.path.exists(base_path):
        await query.answer("Отправьте сначала фото.", show_alert=True)
        await state.clear()
        return
    frame_path = os.path.join(FRAME_DIR, frame_name)
    if not os.path.exists(frame_path):
        await query.answer("Рамка не найдена.", show_alert=True)
        await state.clear()
        return
    out_path = os.path.join(PHOTOS_DIR, f"{user_id}_framed_{frame_name}")
    try:
        add_frame_to_photo(base_path, frame_path, out_path)
        await bot.send_photo(user_id, FSInputFile(out_path), caption=f"Рамка {frame_name} применена")
        await query.answer()
        logger.info("User %s applied frame %s", user_id, frame_name)
    except Exception as e:
        logger.error("Ошибка применения рамки: %s", e)
        await query.answer(f"Ошибка: {e}", show_alert=True)
    await state.clear()


@router.message(Command("collage"))
async def cmd_collage_start(message: Message, state: FSMContext) -> None:
    await state.update_data(collage_photos=[])
    await message.answer(
        "Отправьте фото для коллажа (не более 6). Отправьте /done, когда закончите."
    )
    await state.set_state(MediaStates.waiting_for_collage_photos)


@router.message(MediaStates.waiting_for_collage_photos, F.photo)
async def collage_photo_receive(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    if not is_valid_file_size(photo.file_size):
        await message.reply("Файл слишком большой, попробуйте меньшего размера.")
        return
    file_info = await bot.get_file(photo.file_id)
    file_data = await bot.download_file(file_info.file_path)
    user_id = message.from_user.id
    save_path = os.path.join(PHOTOS_DIR, f"collage_{user_id}_{file_info.file_unique_id}.jpg")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_data.getvalue())
    user_data = await state.get_data()
    photos: List[str] = user_data.get("collage_photos", [])
    photos.append(save_path)
    await state.update_data(collage_photos=photos)
    await message.reply(f"Фото добавлено к коллажу. Всего: {len(photos)}")


@router.message(MediaStates.waiting_for_collage_photos, Command("done"))
async def collage_done(message: Message, state: FSMContext) -> None:
    user_data = await state.get_data()
    photos: List[str] = user_data.get("collage_photos", [])
    if len(photos) < 2:
        await message.reply("Минимум 2 фото для коллажа.")
        return
    user_id = message.from_user.id
    output_path = os.path.join(COLLAGE_DIR, f"collage_{user_id}.jpg")
    try:
        create_collage_from_paths(photos, output_path, cols=COLLAGE_COLS)
        await message.reply_photo(FSInputFile(output_path), caption="Коллаж готов!")
    except Exception as e:
        logger.error("Ошибка создания коллажа: %s", e)
        await message.reply("Ошибка при создании коллажа.")
    await state.clear()


@router.message(Command("video_trim"))
async def cmd_video_trim(message: Message, state: FSMContext) -> None:
    await message.reply("Отправьте видео, которое хотите обрезать.")
    await state.set_state(MediaStates.waiting_for_video_file)


@router.message(MediaStates.waiting_for_video_file, F.video)
async def video_received(message: Message, state: FSMContext) -> None:
    video = message.video
    if not video or video.file_size <= 0:
        await message.reply("Ошибка загрузки видео.")
        return
    if not is_valid_file_size(video.file_size):
        await message.reply("Видео слишком большое.")
        return
    file_info = await bot.get_file(video.file_id)
    file_data = await bot.download_file(file_info.file_path)
    user_id = message.from_user.id
    save_path = os.path.join(VIDEOS_DIR, f"{user_id}_{file_info.file_unique_id}.mp4")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_data.getvalue())
    user_last_media[user_id] = save_path
    await message.reply(
        "Видео получено. Введите параметры обрезки (начало и конец в секундах), например:\n"
        "10 30\n"
        "(обрезать с 10-й по 30-ю секунду)"
    )
    await state.set_state(MediaStates.waiting_for_video_trim_params)


@router.message(MediaStates.waiting_for_video_trim_params)
async def video_trim_params(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    src = user_last_media.get(user_id)
    if not src or not os.path.exists(src):
        await message.reply("Видео не найдено. Отправьте /video_trim и загрузите видео снова.")
        await state.clear()
        return
    try:
        parts = (message.text or "").strip().split()
        start_sec = float(parts[0])
        end_sec = float(parts[1])
    except (ValueError, IndexError):
        await message.reply("Неверный формат. Введите два числа, например: 10 30")
        return
    out_path = os.path.join(VIDEOS_DIR, f"{user_id}_trimmed.mp4")
    try:
        clip = VideoFileClip(src).subclip(start_sec, end_sec)
        clip.write_videofile(out_path, verbose=False, logger="bar")
        clip.close()
        await message.reply_video(
            FSInputFile(out_path), caption=f"Видео обрезано: {start_sec}–{end_sec}с"
        )
        logger.info("User %s trimmed video %s", user_id, src)
    except Exception as e:
        logger.error("Ошибка обрезки видео: %s", e)
        await message.reply(f"Ошибка при обрезке видео: {e}")
    await state.clear()


@router.message(F.photo)
async def photo_received(message: Message) -> None:
    user_id = message.from_user.id
    photo = message.photo[-1]
    if not is_valid_file_size(photo.file_size):
        await message.reply("Файл слишком большой.")
        return
    file_info = await bot.get_file(photo.file_id)
    file_data = await bot.download_file(file_info.file_path)
    save_path = os.path.join(PHOTOS_DIR, f"{user_id}_{file_info.file_unique_id}.jpg")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_data.getvalue())
    user_last_media[user_id] = save_path
    await message.reply(
        "Фото получено! Используйте /frame для рамки или /collage для коллажа."
    )
    logger.info("User %s uploaded photo: %s", user_id, save_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
