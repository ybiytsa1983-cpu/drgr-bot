import os
import re
import asyncio
import logging
import aiofiles
from typing import List, Dict, Optional
from collections import defaultdict, deque
import urllib.request
import urllib.parse
from urllib.parse import urlparse
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

# DuckDuckGo поиск
from duckduckgo_search import DDGS

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

# --- DuckDuckGo ПОИСК ---

# Домены с низким качеством/нерелевантным контентом, которые фильтруются
_DDG_BLACKLIST_DOMAINS: List[str] = [
    "mk.ru", "aif.ru", "kp.ru", "life.ru",
    "tvzvezda.ru", "ren.tv", "ntv.ru", "1tv.ru",
    "vesti.ru", "riafan.ru", "tsargrad.tv",
]

# Предпочтительные домены: Википедия, официальные сайты, технические ресурсы
_DDG_PREFERRED_DOMAINS: List[str] = [
    "wikipedia.org", "stackoverflow.com", "github.com",
    "docs.python.org", "developer.mozilla.org", "arxiv.org",
    "habr.com", "medium.com", "dev.to", "geeksforgeeks.org",
    "docs.microsoft.com", "learn.microsoft.com",
    "docs.aws.amazon.com", "cloud.google.com",
    "pytorch.org", "tensorflow.org", "scikit-learn.org",
]

_DDG_MAX_FETCH = 20       # Сколько результатов запрашивать у DDG
_DDG_MAX_PER_DOMAIN = 2   # Максимум результатов с одного домена
_DDG_FINAL_COUNT = 8      # Итоговое количество результатов


def _ddg_domain(url: str) -> str:
    """Извлечь корневой домен из URL."""
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _ddg_relevance_score(query: str, title: str, body: str) -> float:
    """
    Вычислить оценку тематической релевантности результата поиска.
    Возвращает число от 0.0 до 1.0.
    """
    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        return 0.0
    text_tokens = set(re.findall(r"\w+", (title + " " + body).lower()))
    matched = query_tokens & text_tokens
    return len(matched) / len(query_tokens)


def _ddg_format_html(query: str, results: List[Dict]) -> str:
    """Сформировать HTML-таблицу результатов поиска."""
    if not results:
        return "<b>Ничего не найдено.</b>"

    rows = ""
    for i, r in enumerate(results, 1):
        title = r.get("title", "—")
        url = r.get("href", "#")
        body = r.get("body", "")
        domain = _ddg_domain(url)
        score = r.get("_score", 0.0)
        stars = "★" * round(score * 5) + "☆" * (5 - round(score * 5))

        safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_body = body[:160].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if len(body) > 160:
            safe_body += "…"

        rows += (
            f"<tr>"
            f"<td><b>{i}</b></td>"
            f"<td><a href='{url}'>{safe_title}</a><br/><small>{safe_body}</small></td>"
            f"<td><small>{domain}</small></td>"
            f"<td><small>{stars}</small></td>"
            f"</tr>\n"
        )

    return (
        f"<b>🔍 Результаты поиска: {query}</b>\n\n"
        f"<table border='1' cellpadding='4'>\n"
        f"<thead><tr><th>#</th><th>Заголовок / Описание</th>"
        f"<th>Домен</th><th>Релевантность</th></tr></thead>\n"
        f"<tbody>\n{rows}</tbody>\n"
        f"</table>"
    )


def _ddg_format_telegram(query: str, results: List[Dict]) -> str:
    """Сформировать текстовое сообщение для Telegram с результатами поиска."""
    if not results:
        return "🔍 Ничего не найдено по запросу: " + query

    lines = [f"🔍 <b>Результаты поиска:</b> {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "—")
        url = r.get("href", "#")
        body = r.get("body", "")
        score = r.get("_score", 0.0)
        stars = "★" * round(score * 5) + "☆" * (5 - round(score * 5))
        snippet = body[:120] + "…" if len(body) > 120 else body
        lines.append(
            f"{i}. <b>{title}</b> [{stars}]\n"
            f"   <a href='{url}'>{_ddg_domain(url)}</a>\n"
            f"   <i>{snippet}</i>\n"
        )
    return "\n".join(lines)


async def search_duckduckgo(
    query: str,
    max_results: int = _DDG_FINAL_COUNT,
    html: bool = False,
) -> str:
    """
    Поиск через DuckDuckGo с:
    - фильтрацией нерелевантных доменов (чёрный список),
    - предпочтением Википедии, официальных и технических сайтов,
    - оценкой тематической релевантности (пересечение ключевых слов),
    - диверсификацией источников (не более _DDG_MAX_PER_DOMAIN на домен).

    Если html=True — возвращает HTML-таблицу, иначе — текст для Telegram.
    """
    try:
        raw: List[Dict] = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=_DDG_MAX_FETCH))
        )
    except Exception as e:
        logger.error(f"DuckDuckGo search error for '{query}': {e}")
        return f"<b>Ошибка поиска:</b> {e}"

    # 1. Фильтрация чёрного списка
    filtered = [
        r for r in raw
        if _ddg_domain(r.get("href", "")) not in _DDG_BLACKLIST_DOMAINS
    ]

    # 2. Оценка релевантности + бонус за предпочтительный домен
    for r in filtered:
        base_score = _ddg_relevance_score(query, r.get("title", ""), r.get("body", ""))
        domain = _ddg_domain(r.get("href", ""))
        preferred_bonus = 0.3 if any(
            domain == d or domain.endswith("." + d) for d in _DDG_PREFERRED_DOMAINS
        ) else 0.0
        r["_score"] = min(1.0, base_score + preferred_bonus)

    # 3. Сортировка по релевантности (убывание)
    filtered.sort(key=lambda r: r["_score"], reverse=True)

    # 4. Диверсификация: не более _DDG_MAX_PER_DOMAIN результатов с одного домена
    diversified: List[Dict] = []
    domain_counts: Dict[str, int] = defaultdict(int)
    for r in filtered:
        domain = _ddg_domain(r.get("href", ""))
        if domain_counts[domain] < _DDG_MAX_PER_DOMAIN:
            diversified.append(r)
            domain_counts[domain] += 1
        if len(diversified) >= max_results:
            break

    logger.info(
        f"DDG '{query}': {len(raw)} raw → {len(filtered)} filtered → "
        f"{len(diversified)} diversified"
    )

    if html:
        return _ddg_format_html(query, diversified)
    return _ddg_format_telegram(query, diversified)


# --- ОБРАБОТЧИКИ КОМАНД ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 <b>DRGR Bot</b>\n\n"
        "/search &lt;запрос&gt; — поиск DuckDuckGo\n"
        "/msearch &lt;запрос&gt; — мультиисточниковый поиск\n"
        "/wiki &lt;запрос&gt; — поиск в Википедии\n"
        "/upload — загрузка файлов 📎\n"
        "/video — обработка видео\n"
        "/frame — рамка для фото\n"
        "/collage — коллаж из фото\n"
        "/help — справка",
        parse_mode="HTML",
    )
@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    """Поиск в интернете через DuckDuckGo. Использование: /search <запрос>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/search запрос</code>\n"
            "Например: <code>/search Python asyncio tutorial</code>",
            parse_mode="HTML",
        )
        return
    query = args[1].strip()
    await message.reply("🔍 Ищу, подождите…")
    result = await search_duckduckgo(query)
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)


# --- WIKIPEDIA ПОИСК ---

async def search_wikipedia(query: str, lang: str = "ru") -> str:
    """Поиск через Wikipedia API."""
    import json
    url = (
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&list=search&srsearch={urllib.parse.quote(query)}"
        f"&srlimit=5&format=json&utf8=1"
    )
    try:
        data = await asyncio.to_thread(
            lambda: json.loads(urllib.request.urlopen(url, timeout=8).read().decode())
        )
        hits = data.get("query", {}).get("search", [])
        if not hits:
            return ""
        lines = [f"📖 <b>Wikipedia:</b> {query}\n"]
        for i, h in enumerate(hits[:5], 1):
            title = h.get("title", "—")
            snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
            wiki_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'), safe='_:')}"
            lines.append(f"{i}. <a href='{wiki_url}'><b>{title}</b></a>\n   <i>{snippet[:120]}…</i>\n")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Wikipedia search error: {e}")
        return ""


async def search_multi(query: str) -> str:
    """
    Мультиисточниковый поиск: DuckDuckGo + Wikipedia.
    Возвращает объединённый результат.
    """
    ddg_task = asyncio.create_task(search_duckduckgo(query))
    wiki_task = asyncio.create_task(search_wikipedia(query))

    ddg_result, wiki_result = await asyncio.gather(ddg_task, wiki_task, return_exceptions=True)

    parts: List[str] = []
    if isinstance(ddg_result, str) and ddg_result:
        parts.append(ddg_result)
    if isinstance(wiki_result, str) and wiki_result:
        parts.append(wiki_result)

    if not parts:
        return f"🔍 Ничего не найдено по запросу: <b>{query}</b>"
    return "\n\n".join(parts)


# --- ОБРАБОТЧИКИ ДОПОЛНИТЕЛЬНЫХ КОМАНД ---

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.reply(
        "📖 <b>Список команд:</b>\n\n"
        "/search <запрос> — поиск DuckDuckGo\n"
        "/msearch <запрос> — поиск сразу в нескольких источниках\n"
        "/wiki <запрос> — поиск в Википедии\n"
        "/upload — подсказка по загрузке файлов\n"
        "/video — обработка видео\n"
        "/frame — применить рамку к фото\n"
        "/collage — создать коллаж\n",
        parse_mode="HTML",
    )

@dp.message(Command("msearch"))
async def cmd_msearch(message: types.Message):
    """Мультиисточниковый поиск."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/msearch запрос</code>",
            parse_mode="HTML",
        )
        return
    query = args[1].strip()
    await message.reply("🔍 Ищу в нескольких источниках…")
    result = await search_multi(query)
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("wiki"))
async def cmd_wiki(message: types.Message):
    """Поиск в Википедии."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/wiki запрос</code>",
            parse_mode="HTML",
        )
        return
    query = args[1].strip()
    await message.reply("📖 Ищу в Википедии…")
    result = await search_wikipedia(query)
    if not result:
        result = f"📖 Ничего не найдено в Википедии по запросу: <b>{query}</b>"
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("upload"))
async def cmd_upload(message: types.Message):
    """Подсказка по загрузке файлов."""
    await message.reply(
        "📎 <b>Загрузка файлов</b>\n\n"
        "Просто отправьте файл (фото, видео, документ) в этот чат.\n"
        "• Фото — обработка эффектами, рамки, коллажи\n"
        "• Видео — обрезка\n"
        "• Документ — сохранение\n",
        parse_mode="HTML",
    )


# --- ОБРАБОТЧИКИ МЕДИА ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    """Обработка фото — сохранение и предложение эффектов."""
    photo = message.photo[-1]
    if not is_valid_file_size(photo.file_size or 0):
        await message.reply(f"Файл слишком большой (лимит {MAX_SIZE_MB} МБ).")
        return

    file = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    user_id = message.from_user.id
    save_path = os.path.join(PHOTOS_DIR, f"{user_id}_{photo.file_unique_id}.jpg")

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_bytes.getvalue())
    user_last_media[user_id] = save_path
    logger.info(f"Photo saved for user {user_id}: {save_path}")

    builder = InlineKeyboardBuilder()
    for effect in EFFECTS:
        builder.button(text=effect, callback_data=f"effect:{effect}:{photo.file_unique_id}")
    builder.adjust(4)
    await message.reply(
        "✅ Фото сохранено! Выберите эффект:",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data.startswith("effect:"))
async def handle_effect_callback(callback: types.CallbackQuery):
    """Применение эффекта к фото."""
    _, effect, file_uid = callback.data.split(":", 2)
    user_id = callback.from_user.id
    base_path = user_last_media.get(user_id)
    if not base_path or not os.path.exists(base_path):
        await callback.answer("Сначала отправьте фото.", show_alert=True)
        return

    try:
        img = Image.open(base_path)
        result_img = apply_effect(img, effect)
        out_path = os.path.join(PHOTOS_DIR, f"{user_id}_effect_{effect}.jpg")
        result_img.save(out_path)
        await callback.message.reply_photo(
            types.FSInputFile(out_path),
            caption=f"Эффект «{effect}» применён",
        )
        await callback.answer()
        logger.info(f"User {user_id} applied effect {effect}")
    except Exception as e:
        logger.error(f"Effect error {effect}: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@dp.message(F.document)
async def handle_document(message: types.Message):
    """Приём загруженных документов (📎 файлов)."""
    doc = message.document
    if not is_valid_file_size(doc.file_size or 0):
        await message.reply(f"Файл слишком большой (лимит {MAX_SIZE_MB} МБ).")
        return

    file = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file.file_path)

    save_dir = os.path.join(PHOTOS_DIR, "uploads")
    os.makedirs(save_dir, exist_ok=True)
    filename = doc.file_name or f"file_{doc.file_unique_id}"
    save_path = os.path.join(save_dir, f"{message.from_user.id}_{filename}")

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_bytes.getvalue())
    logger.info(f"Document saved for user {message.from_user.id}: {save_path}")
    await message.reply(f"📎 Файл <b>{filename}</b> получен и сохранён.", parse_mode="HTML")


@dp.message(F.video)
async def handle_video(message: types.Message, state: FSMContext):
    """Приём видеофайлов с предложением обрезки."""
    video = message.video
    if not is_valid_file_size(video.file_size or 0):
        await message.reply(f"Видео слишком большое (лимит {MAX_SIZE_MB} МБ).")
        return

    file = await message.bot.get_file(video.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    user_id = message.from_user.id
    save_path = os.path.join(VIDEOS_DIR, f"{user_id}_{video.file_unique_id}.mp4")

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_bytes.getvalue())
    user_last_media[user_id] = save_path
    logger.info(f"Video saved for user {user_id}: {save_path}")

    await state.update_data(video_path=save_path)
    await message.reply(
        f"🎬 Видео получено! Продолжительность: {video.duration}с.\n"
        "Отправьте /video_trim для обрезки, либо /help для других команд.",
    )


@dp.message(Command("video"))
async def cmd_video(message: types.Message):
    await message.reply(
        "🎬 <b>Обработка видео</b>\n\n"
        "Отправьте видео в чат, затем используйте /video_trim для обрезки.\n"
        "Параметры обрезки: <code>начало конец</code> (в секундах)\n"
        "Например: <code>10 30</code>",
        parse_mode="HTML",
    )


@dp.message(Command("video_trim"))
async def cmd_video_trim(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("video_path") and not user_last_media.get(message.from_user.id):
        await message.reply("Сначала отправьте видео.")
        return
    await message.reply("Введите начало и конец обрезки в секундах (например: <code>5 30</code>)", parse_mode="HTML")
    await MediaStates.waiting_for_video_trim_params.set()


@dp.message(MediaStates.waiting_for_video_trim_params)
async def handle_video_trim_params(message: types.Message, state: FSMContext):
    """Обрезка видео по введённым параметрам."""
    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            raise ValueError("Нужно два числа")
        start_t = float(parts[0])
        end_t = float(parts[1])
    except Exception:
        await message.reply("Неверный формат. Введите два числа: <code>начало конец</code>", parse_mode="HTML")
        return

    user_id = message.from_user.id
    data = await state.get_data()
    video_path = data.get("video_path") or user_last_media.get(user_id)
    if not video_path or not os.path.exists(video_path):
        await message.reply("Видеофайл не найден. Отправьте видео заново.")
        await state.clear()
        return

    await message.reply("✂️ Обрезаю видео…")
    out_path = os.path.join(VIDEOS_DIR, f"{user_id}_trimmed.mp4")
    try:
        clip = await asyncio.to_thread(VideoFileClip, video_path)
        sub = clip.subclip(start_t, min(end_t, clip.duration))
        await asyncio.to_thread(sub.write_videofile, out_path, codec="libx264", audio_codec="aac", logger=None)
        clip.close()
        await message.reply_video(types.FSInputFile(out_path), caption=f"✅ Обрезано: {start_t}с — {end_t}с")
        logger.info(f"Video trimmed for user {user_id}: {start_t}-{end_t}s")
    except Exception as e:
        logger.error(f"Video trim error: {e}")
        await message.reply(f"Ошибка обрезки: {e}")
    finally:
        await state.clear()


@dp.message(Command("frame"))
async def cmd_frame(message: types.Message, state: FSMContext):
    frames = [f for f in os.listdir(FRAME_DIR) if f.lower().endswith((".png", ".jpg", ".webp"))]
    if not frames:
        await message.reply("Нет доступных рамок. Добавьте изображения в папку frames/")
        return
    builder = InlineKeyboardBuilder()
    for f in frames[:12]:
        builder.button(text=f, callback_data=f"frame_select:{f}")
    builder.adjust(2)
    await message.reply("Выберите рамку:", reply_markup=builder.as_markup())
    await MediaStates.waiting_for_frame.set()


@dp.callback_query(F.data.startswith("frame_select:"))
async def handle_frame_select(callback: types.CallbackQuery, state: FSMContext):
    frame_name = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    base_path = user_last_media.get(user_id)
    if not base_path or not os.path.exists(base_path):
        await callback.answer("Сначала отправьте фото.", show_alert=True)
        await state.clear()
        return
    frame_path = os.path.join(FRAME_DIR, frame_name)
    if not os.path.exists(frame_path):
        await callback.answer("Рамка не найдена.", show_alert=True)
        await state.clear()
        return
    out_path = os.path.join(PHOTOS_DIR, f"{user_id}_framed_{frame_name}")
    try:
        add_frame_to_photo(base_path, frame_path, out_path)
        await callback.message.reply_photo(types.FSInputFile(out_path), caption=f"Рамка «{frame_name}» применена")
        await callback.answer()
        logger.info(f"User {user_id} applied frame {frame_name}")
    except Exception as e:
        logger.error(f"Frame error: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    finally:
        await state.clear()


@dp.message(Command("collage"))
async def cmd_collage_start(message: types.Message, state: FSMContext):
    await state.update_data(collage_photos=[])
    await message.reply("Отправьте фото для коллажа (2–6 штук). Когда закончите — /done")
    await MediaStates.waiting_for_collage_photos.set()


@dp.message(MediaStates.waiting_for_collage_photos, F.photo)
async def collage_photo_receive(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    if not is_valid_file_size(photo.file_size or 0):
        await message.reply(f"Файл слишком большой (лимит {MAX_SIZE_MB} МБ).")
        return
    file = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    user_id = message.from_user.id
    save_path = os.path.join(PHOTOS_DIR, f"collage_{user_id}_{photo.file_unique_id}.jpg")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(file_bytes.getvalue())
    data = await state.get_data()
    photos = data.get("collage_photos", [])
    if len(photos) >= 6:
        await message.reply("Максимум 6 фото. Введите /done для создания коллажа.")
        return
    photos.append(save_path)
    await state.update_data(collage_photos=photos)
    await message.reply(f"Фото {len(photos)}/6 добавлено. Ещё или /done.")


@dp.message(Command("done"))
async def collage_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("collage_photos", [])
    if len(photos) < 2:
        await message.reply("Нужно минимум 2 фото для коллажа.")
        return
    user_id = message.from_user.id
    output_path = os.path.join(COLLAGE_DIR, f"collage_{user_id}.jpg")
    try:
        create_collage_from_paths(photos, output_path, cols=3)
        await message.reply_photo(types.FSInputFile(output_path), caption="🖼 Коллаж готов!")
        logger.info(f"Collage created for user {user_id} from {len(photos)} photos")
    except Exception as e:
        logger.error(f"Collage error: {e}")
        await message.reply(f"Ошибка создания коллажа: {e}")
    finally:
        await state.clear()


# --- ЗАПУСК ---

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
