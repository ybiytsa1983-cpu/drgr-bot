import os
import re
import random
import asyncio
import logging
import aiofiles
import aiohttp
from typing import List, Dict, Optional
from collections import defaultdict, deque
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
from ddgs import DDGS

# Загрузка переменных окружения
load_dotenv()

# Получение токенов и настроек
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Добавьте BOT_TOKEN в .env файл.")

# URL расширения VM (по умолчанию — локальный сервер)
VM_URL = os.getenv("VM_URL", "http://localhost:5001")

# Hugging Face API ключ опциональный — бот запустится и без него
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

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

# Логирование: и в файл, и в консоль (для облачных платформ)
log_handlers: List[logging.Handler] = [
    logging.StreamHandler(),
    logging.FileHandler(LOG_FILE, encoding="utf-8"),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger("FSMMediaBot")

# Инициализация клиента Hugging Face (опционально)
if HUGGINGFACE_API_KEY:
    client = InferenceClient(api_key=HUGGINGFACE_API_KEY)
else:
    client = None
    logger.warning("HUGGINGFACE_API_KEY не задан — функции Hugging Face недоступны.")

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
dp = Dispatcher()

# Per-user selected AI model (e.g. 'ollama:llama3', 'lms:qwen2-7b', or '')
_user_model: Dict[int, str] = {}


def _get_user_model(user_id: int) -> str:
    return _user_model.get(user_id, '')


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(
        "👋 <b>Привет! Я DRGR-бот.</b>\n\n"
        "📌 <b>Доступные команды:</b>\n"
        "/search &lt;запрос&gt; — поиск в DuckDuckGo\n"
        "/task &lt;описание&gt; — задание для AI через VM\n"
        "/research &lt;тема&gt; — сгенерировать статью с графиками и изображениями\n"
        "/model — выбрать AI-модель для VM\n"
        "/vm — статус VM и AI-сервисов\n"
        "/help — справка\n\n"
        "🔗 VM-интерфейс: <code>http://localhost:5001</code>",
        parse_mode="HTML",
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.reply(
        "📖 <b>Справка DRGR-бота</b>\n\n"
        "<b>🔍 Поиск:</b>\n"
        "/search &lt;запрос&gt; — поиск через DuckDuckGo\n\n"
        "<b>🤖 AI через VM:</b>\n"
        "/task &lt;описание&gt; — отправить задание на VM\n"
        "/research &lt;тема&gt; — сгенерировать HTML-статью по теме\n"
        "/model — показать и выбрать AI-модель\n"
        "/vm — проверить статус VM и всех AI-сервисов\n\n"
        "<b>Примеры:</b>\n"
        "<code>/search Python asyncio</code>\n"
        "<code>/task Напиши парсер Wildberries</code>\n"
        "<code>/research Искусственный интеллект 2024</code>\n"
        "<code>/model</code> — покажет доступные модели Ollama и LM Studio",
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


async def _vm_get(path: str, timeout: int = 8) -> Optional[dict]:
    """GET request to VM server. Returns dict or None on error."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_URL}{path}", timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.content_type == 'application/json':
                    return await resp.json()
                return {'text': await resp.text()}
    except Exception as e:
        logger.warning(f"VM GET {path} failed: {e}")
        return None


async def _vm_post(path: str, payload: dict, timeout: int = 120) -> Optional[dict]:
    """POST JSON to VM server. Returns dict or None on error."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_URL}{path}", json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.content_type == 'application/json':
                    return await resp.json()
                return {'text': await resp.text()}
    except aiohttp.ClientConnectorError:
        logger.warning(f"VM недоступна по адресу {VM_URL}")
        return None
    except Exception as e:
        logger.error(f"VM POST {path} error: {e}")
        return None


@dp.message(Command("vm"))
async def cmd_vm(message: types.Message):
    """Статус VM и AI-сервисов."""
    status_msg = await message.reply("🔄 Проверяю статус VM…")
    data = await _vm_get('/health', timeout=10)
    if data is None:
        await status_msg.edit_text(
            f"❌ VM недоступна по адресу <code>{VM_URL}</code>\n"
            "Запустите VM командой <code>ЗАПУСТИТЬ_БОТА.bat</code>.",
            parse_mode="HTML"
        )
        return

    services = data.get('services', {})
    lines = [f"🖥 <b>VM статус</b> — <code>{VM_URL}</code>\n"]
    icons = {'ok': '🟢', 'warn': '🟡', 'error': '🔴', 'off': '⚪'}
    for name, info in services.items():
        status = info.get('status', 'off')
        note   = info.get('note', info.get('model', ''))
        icon   = icons.get(status, '⚪')
        lines.append(f"{icon} <b>{name}</b>: {note or status}")

    cur_model = _get_user_model(message.from_user.id)
    if cur_model:
        lines.append(f"\n🤖 Ваша модель: <code>{cur_model}</code>")
    else:
        lines.append("\n🤖 Модель: авто (используй /model)")

    await status_msg.edit_text('\n'.join(lines), parse_mode="HTML")


@dp.message(Command("model"))
async def cmd_model(message: types.Message):
    """Показать доступные модели и выбрать одну. /model [model_id]"""
    args = message.text.split(maxsplit=1)
    user_id = message.from_user.id

    # If user passed a model id directly: /model ollama:llama3
    if len(args) == 2 and args[1].strip():
        chosen = args[1].strip()
        _user_model[user_id] = chosen
        await message.reply(
            f"✅ Модель установлена: <code>{chosen}</code>\n"
            "Она будет использоваться для /task и /research.",
            parse_mode="HTML"
        )
        return

    # Otherwise: fetch models from VM and show keyboard
    status_msg = await message.reply("🔄 Загружаю список моделей с VM…")
    data = await _vm_get('/api/models', timeout=10)
    if data is None:
        await status_msg.edit_text(
            f"❌ VM недоступна (<code>{VM_URL}</code>).\n"
            "Модель можно задать вручную: <code>/model ollama:llama3</code>",
            parse_mode="HTML"
        )
        return

    all_models = data.get('ollama', []) + data.get('lmstudio', [])
    if not all_models:
        await status_msg.edit_text(
            "⚠️ AI-модели не найдены.\n\n"
            "Убедитесь, что <b>Ollama</b> или <b>LM Studio</b> запущены.\n"
            "• Ollama: <code>ollama serve</code>\n"
            "• LM Studio: запустите приложение и загрузите модель",
            parse_mode="HTML"
        )
        return

    kb = InlineKeyboardBuilder()
    cur = _get_user_model(user_id)
    for m in all_models[:10]:
        mid   = m['id']
        name  = m['name']
        src   = m['source']
        label = f"{'✅ ' if mid == cur else ''}{src}: {name}"
        kb.button(text=label, callback_data=f"setmodel:{mid}")
    kb.button(text="🔄 Авто (без предпочтения)", callback_data="setmodel:")
    kb.adjust(1)

    cur_text = f"Текущая модель: <code>{cur}</code>" if cur else "Модель: авто"
    await status_msg.edit_text(
        f"🤖 <b>Выбор AI-модели для VM</b>\n{cur_text}\n\nДоступные модели:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("setmodel:"))
async def cb_set_model(callback: types.CallbackQuery):
    model_id = callback.data[len("setmodel:"):]
    user_id  = callback.from_user.id
    _user_model[user_id] = model_id
    label = f"<code>{model_id}</code>" if model_id else "авто"
    await callback.answer(f"Модель: {model_id or 'авто'}", show_alert=False)
    await callback.message.edit_text(
        f"✅ Модель установлена: {label}\n"
        "Используется в /task и /research.",
        parse_mode="HTML"
    )


async def _call_vm_task(description: str, model: str = '') -> str:
    """
    Отправить задание на VM-расширение (POST /api/task).
    Возвращает текст ответа.
    """
    data = await _vm_post('/api/task', {'description': description, 'model': model}, timeout=120)
    if data is None:
        logger.warning(f"VM недоступна по адресу {VM_URL}, генерирую план локально.")
        return _generate_project_plan_local(description)
    return data.get('content') or data.get('result') or 'VM не вернул результат.'


def _generate_project_plan_local(description: str) -> str:
    """
    Сформировать структурированный план проекта локально
    (когда VM недоступна).
    """
    first_line = description.strip().splitlines()[0][:80]
    return (
        f"📋 <b>Автоплан проекта: {first_line}</b>\n\n"
        "Ниже — типовая структура для полноценного проекта.\n\n"
        "<b>📁 Структура файлов:</b>\n"
        "<pre>"
        "project/\n"
        "├── docker-compose.yml\n"
        "├── .env.example\n"
        "├── README.md\n"
        "├── bot/\n"
        "│   ├── Dockerfile\n"
        "│   ├── requirements.txt\n"
        "│   └── main.py           # Telegram-бот\n"
        "├── api/\n"
        "│   ├── Dockerfile\n"
        "│   ├── requirements.txt\n"
        "│   └── app.py            # FastAPI/Flask сервер\n"
        "├── workers/\n"
        "│   ├── scraper.py        # Парсинг Wildberries / Alibaba\n"
        "│   ├── analytics.py      # Юнит-экономика, скоринг\n"
        "│   └── scheduler.py      # Фоновые задачи (APScheduler)\n"
        "├── db/\n"
        "│   └── migrations/       # SQL-миграции (Alembic)\n"
        "└── dashboard/\n"
        "    └── index.html        # Web-интерфейс\n"
        "</pre>\n\n"
        "<b>🛠 Технологический стек:</b>\n"
        "• <b>Bot:</b> aiogram 3.x\n"
        "• <b>API:</b> FastAPI + SQLAlchemy\n"
        "• <b>DB:</b> PostgreSQL 15\n"
        "• <b>Cache:</b> Redis\n"
        "• <b>AI:</b> OpenClaw / Ollama / HuggingFace\n"
        "• <b>Парсинг:</b> httpx + BeautifulSoup4\n"
        "• <b>Деплой:</b> Docker Compose\n\n"
        "<b>⚙️ Ключевые модули:</b>\n"
        "1. <code>scraper.py</code> — сбор данных с Wildberries, MPStats, Alibaba\n"
        "2. <code>analytics.py</code> — скоринг товаров (маржа, конкуренция, спрос)\n"
        "3. <code>bot/main.py</code> — голосовой и текстовый ввод через Telegram\n"
        "4. <code>dashboard/</code> — дашборд с графиками и фильтрами\n\n"
        "Для запуска откройте расширение по адресу "
        "<code>http://localhost:5001</code>."
    )


@dp.message(Command("task"))
async def cmd_task(message: types.Message):
    """
    Отправить задание на VM-расширение.
    Использование: /task <описание проекта>
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/task описание проекта</code>\n"
            "Например:\n"
            "<code>/task OpenClaw — AI-система подбора товаров для маркетплейсов</code>",
            parse_mode="HTML",
        )
        return
    description = args[1].strip()
    model = _get_user_model(message.from_user.id)
    status_msg = await message.reply(
        f"⚙️ Отправляю задание на VM…"
        + (f"\n🤖 Модель: <code>{model}</code>" if model else ""),
        parse_mode="HTML"
    )
    result = await _call_vm_task(description, model=model)
    await status_msg.delete()
    # Telegram ограничивает сообщения до 4096 символов
    if len(result) > 4000:
        result = result[:3997] + "…"
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("research"))
async def cmd_research(message: types.Message):
    """
    Сгенерировать HTML-статью по теме с графиками и изображениями.
    Использование: /research <тема>
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/research тема статьи</code>\n"
            "Например:\n"
            "<code>/research Искусственный интеллект 2024</code>\n"
            "<code>/research Как работает квантовый компьютер</code>",
            parse_mode="HTML",
        )
        return
    topic = args[1].strip()
    model = _get_user_model(message.from_user.id)
    status_msg = await message.reply(
        f"🔬 Генерирую статью по теме: <b>{topic}</b>\n"
        "⏳ Это может занять 1–3 минуты…"
        + (f"\n🤖 Модель: <code>{model}</code>" if model else ""),
        parse_mode="HTML"
    )
    data = await _vm_post(
        '/research',
        {'topic': topic, 'max_sources': 15, 'model': model},
        timeout=180
    )
    await status_msg.delete()
    if data is None:
        await message.reply(
            f"❌ VM недоступна (<code>{VM_URL}</code>).\n"
            "Запустите VM через <code>ЗАПУСТИТЬ_БОТА.bat</code>.",
            parse_mode="HTML"
        )
        return
    if data.get('error'):
        await message.reply(f"❌ Ошибка: {data['error']}", parse_mode="HTML")
        return

    article_id = data.get('article_id', '')
    src_count  = data.get('sources_count', 0)
    ai_src     = data.get('ai_source', '?')
    article_url = f"{VM_URL}/research/article/{article_id}" if article_id else ''

    reply = (
        f"✅ <b>Статья готова!</b>\n\n"
        f"📄 Тема: <b>{topic}</b>\n"
        f"📚 Источников: {src_count}\n"
        f"🤖 AI: {ai_src}\n"
    )
    if article_url:
        reply += f"\n🔗 <a href='{article_url}'>Открыть статью</a>\n"
        reply += f"<code>{article_url}</code>"

    await message.reply(reply, parse_mode="HTML", disable_web_page_preview=False)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
