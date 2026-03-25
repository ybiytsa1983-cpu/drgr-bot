import os
import re
import json
import asyncio
import logging
import aiofiles
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

# DuckDuckGo поиск
from ddgs import DDGS

# ── Загрузка настроек ────────────────────────────────────────────────────────
# Priority: vm/settings.json > .env > defaults

load_dotenv()

def _load_vm_settings() -> dict:
    """Load vm/settings.json if it exists, return {} otherwise."""
    settings_path = os.path.join(os.path.dirname(__file__), "vm", "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_vm = _load_vm_settings()

def _setting(key: str, env_key: str, default: str = "") -> str:
    """Return value from vm/settings.json, then .env, then default."""
    v = _vm.get(key, "")
    if v:
        return v
    return os.getenv(env_key, default)

# Получение токенов и настроек
BOT_TOKEN = _setting("bot_token", "BOT_TOKEN")
HUGGINGFACE_API_KEY = _setting("huggingface_api_key", "HUGGINGFACE_API_KEY")  # optional
BOT_MODE = _setting("bot_mode", "BOT_MODE", "polling")          # "polling" | "webhook"
WEBHOOK_URL = _setting("webhook_url", "WEBHOOK_URL", "")
# Default: try cloud VM first, then fall back to lmstudio, then huggingface
AI_BACKEND = _setting("ai_backend", "AI_BACKEND", "cloud_vm")
CLOUD_VM_URL = _setting("cloud_vm_url", "CLOUD_VM_URL", "").rstrip("/")
LMSTUDIO_URL = _setting("lmstudio_url", "LMSTUDIO_URL", "http://localhost:1234").rstrip("/")
LMSTUDIO_MODEL = _setting("lmstudio_model", "LMSTUDIO_MODEL", "")
OLLAMA_URL = _setting("ollama_url", "OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = _setting("ollama_model", "OLLAMA_MODEL", "llama3")

if not BOT_TOKEN:
    raise ValueError("Добавьте BOT_TOKEN в .env файл или в настройки (vm/settings.json).")

# HuggingFace key is optional — only required when ai_backend == "huggingface"
if not HUGGINGFACE_API_KEY and AI_BACKEND == "huggingface":
    logging.warning("HUGGINGFACE_API_KEY не задан, huggingface backend будет недоступен.")

# ── AI backend resolution ─────────────────────────────────────────────────────
import urllib.request

def _vm_health_check(url: str, timeout: int = 4) -> bool:
    """Return True if the VM server at *url* responds to /api/bot/status."""
    try:
        req = urllib.request.urlopen(f"{url}/api/bot/status", timeout=timeout)
        return req.status == 200
    except Exception:
        return False

def _lms_health_check(url: str, timeout: int = 3) -> bool:
    """Return True if an OpenAI-compatible server at *url* is reachable."""
    try:
        req = urllib.request.urlopen(f"{url}/v1/models", timeout=timeout)
        return req.status == 200
    except Exception:
        return False

def _ollama_health_check(url: str, timeout: int = 3) -> bool:
    """Return True if Ollama at *url* is reachable."""
    try:
        req = urllib.request.urlopen(f"{url}/api/tags", timeout=timeout)
        return req.status == 200
    except Exception:
        return False

def _resolve_llm_backend() -> str:
    """
    Determine which backend to actually use at startup.

    Priority (auto-fallback):
      1. cloud_vm  — if CLOUD_VM_URL is set and the server responds
      2. lmstudio  — if LM Studio is running on LMSTUDIO_URL
      3. ollama    — if Ollama is running on OLLAMA_URL
      4. huggingface — only when HUGGINGFACE_API_KEY is set

    When AI_BACKEND is explicitly set to a non-cloud_vm value in settings,
    that value is honoured directly (no auto-fallback).
    """
    backend = AI_BACKEND
    if backend == "cloud_vm":
        if CLOUD_VM_URL and _vm_health_check(CLOUD_VM_URL):
            logging.info("AI backend: cloud_vm (%s)", CLOUD_VM_URL)
            return "cloud_vm"
        logging.warning("cloud_vm не доступен — пробуем lmstudio…")
        if _lms_health_check(LMSTUDIO_URL):
            logging.info("AI backend: lmstudio (fallback, %s)", LMSTUDIO_URL)
            return "lmstudio"
        logging.warning("lmstudio не доступен — пробуем ollama…")
        if _ollama_health_check(OLLAMA_URL):
            logging.info("AI backend: ollama (fallback, %s)", OLLAMA_URL)
            return "ollama"
        if HUGGINGFACE_API_KEY:
            logging.warning("ollama не доступен — используем huggingface")
            return "huggingface"
        logging.warning("Нет доступного AI-бэкенда. Бот запустится без генерации текста.")
        return "none"
    return backend

# Resolve at startup (synchronous probes are fast / tiny)
ACTIVE_BACKEND = _resolve_llm_backend()

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

# ── AI chat helper ─────────────────────────────────────────────────────────────
import urllib.error

async def ai_chat(prompt: str, system: str = "Ты умный помощник. Отвечай на русском языке.") -> str:
    """
    Send *prompt* to the active AI backend and return the reply text.
    Routes to: cloud_vm → lmstudio → ollama.
    Falls back gracefully with a human-readable error message.
    """
    backend = ACTIVE_BACKEND

    # ── Cloud VM (/generate endpoint of vm/server.py style) ──────────────────
    if backend == "cloud_vm" and CLOUD_VM_URL:
        try:
            payload = json.dumps({
                "prompt": prompt,
                "system": system,
                "max_tokens": 512,
            }).encode()
            req = urllib.request.Request(
                f"{CLOUD_VM_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data.get("text") or data.get("response") or str(data)
        except Exception as e:
            return f"⚠️ Cloud VM недоступен: {e}"

    # ── LM Studio (OpenAI-compatible) ─────────────────────────────────────────
    if backend == "lmstudio":
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            payload = json.dumps({
                "model": LMSTUDIO_MODEL or "local-model",
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.7,
            }).encode()
            req = urllib.request.Request(
                f"{LMSTUDIO_URL}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"⚠️ LM Studio недоступен: {e}"

    # ── Ollama ────────────────────────────────────────────────────────────────
    if backend == "ollama":
        try:
            payload = json.dumps({
                "model": OLLAMA_MODEL,
                "prompt": f"{system}\n\n{prompt}",
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
                return data.get("response", "").strip()
        except Exception as e:
            return f"⚠️ Ollama недоступен: {e}"

    # ── HuggingFace (optional) ────────────────────────────────────────────────
    if backend == "huggingface" and HUGGINGFACE_API_KEY:
        try:
            from huggingface_hub import InferenceClient as _HFClient
            hf = _HFClient(api_key=HUGGINGFACE_API_KEY)
            model = _setting("huggingface_model", "HUGGINGFACE_MODEL",
                             "HuggingFaceH4/zephyr-7b-beta")
            result = await asyncio.to_thread(
                lambda: hf.text_generation(
                    f"{system}\n\n{prompt}",
                    model=model,
                    max_new_tokens=512,
                )
            )
            return result.strip()
        except Exception as e:
            return f"⚠️ HuggingFace ошибка: {e}"

    return "⚠️ Нет доступного AI-бэкенда. Настройте cloud_vm_url или запустите LM Studio / Ollama."

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
        "Привет! Я DRGR-бот 🤖\n\n"
        "Доступные команды:\n"
        "/chat &lt;сообщение&gt; — поговорить с AI\n"
        "/search &lt;запрос&gt; — поиск в интернете\n"
        "/status — статус подключения к AI\n"
        "/install — 📦 установить бота (PowerShell)\n"
        "/update — 🔄 обновить бота (PowerShell)\n"
        "/help — справка\n\n"
        "Или просто напишите мне что-нибудь!",
        parse_mode="HTML",
    )
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    """Показать текущий статус подключения к AI-бэкенду."""
    backend_names = {
        "cloud_vm": f"☁️ Облачная ВМ ({CLOUD_VM_URL or 'URL не задан'})",
        "lmstudio": f"🖥 LM Studio ({LMSTUDIO_URL})",
        "ollama": f"🦙 Ollama ({OLLAMA_URL}, модель: {OLLAMA_MODEL})",
        "huggingface": "🤗 HuggingFace Inference",
        "none": "❌ Нет доступного бэкенда",
    }
    name = backend_names.get(ACTIVE_BACKEND, ACTIVE_BACKEND)
    await message.reply(
        f"📡 <b>Активный AI-бэкенд:</b> {name}\n"
        f"⚙️ <b>Настроен:</b> {AI_BACKEND}",
        parse_mode="HTML",
    )


@dp.message(Command("chat"))
async def cmd_chat(message: types.Message):
    """Поговорить с AI. Использование: /chat <сообщение>"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "Использование: <code>/chat ваш вопрос</code>\n"
            "Или просто напишите сообщение без команды.",
            parse_mode="HTML",
        )
        return
    prompt = args[1].strip()
    await message.reply("⏳ Думаю…")
    reply = await ai_chat(prompt)
    await message.reply(reply, parse_mode="HTML")


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    """Обрабатывает произвольный текст как запрос к AI."""
    prompt = message.text.strip()
    if not prompt:
        return
    await message.reply("⏳ Думаю…")
    reply = await ai_chat(prompt)
    await message.reply(reply, parse_mode="HTML")



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


_INSTALL_PS_CMD = (
    "Set-ExecutionPolicy -Scope Process Bypass; "
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
    "$f=\"$env:TEMP\\install_drgr.ps1\"; "
    "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/"
    "main/install.ps1' "
    "-OutFile $f -UseBasicParsing; "
    "if (Test-Path $f) { &amp; $f } "
    "else { Write-Host 'Ошибка: файл не скачался' -ForegroundColor Red }"
)

_INSTALL_TEXT = (
    "📦 <b>Установка DRGR-бота (первый раз)</b>\n\n"
    "Откройте <b>PowerShell</b> (Win+X → Windows PowerShell) и вставьте:\n\n"
    f"<code>{_INSTALL_PS_CMD}</code>\n\n"
    "Скрипт сам:\n"
    "• проверит Python и Git\n"
    "• скачает репозиторий на Рабочий стол\n"
    "• установит зависимости\n"
    "• создаст файл .env с токеном\n"
    "• создаст ярлыки на Рабочем столе\n\n"
    "Или дважды кликните <b>УСТАНОВИТЬ.bat</b> из папки репозитория."
)

_UPDATE_TEXT = (
    "🔄 <b>Обновление бота</b>\n\n"
    "Если бот уже установлен — откройте <b>PowerShell</b> и вставьте:\n\n"
    "<code>Set-ExecutionPolicy -Scope Process Bypass; "
    '&amp; "$env:USERPROFILE\\Desktop\\drgr-bot\\update.ps1"</code>\n\n'
    "Или дважды кликните ярлык <b>«DRGR Bot — Обновить»</b> на Рабочем столе.\n\n"
    "⚠️ Если бот ещё не установлен — используйте команду /install"
)


@dp.message(Command("update"))
@dp.message(Command("обновить"))
async def cmd_update(message: types.Message):
    """Показать команду для обновления бота."""
    await message.reply(_UPDATE_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("install"))
@dp.message(Command("установить"))
async def cmd_install(message: types.Message):
    """Показать команду для первичной установки бота через PowerShell."""
    await message.reply(_INSTALL_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.reply(
        "📋 <b>Справка по командам:</b>\n\n"
        "/chat &lt;сообщение&gt; — 🤖 поговорить с AI\n"
        "/search &lt;запрос&gt; — 🔍 поиск в интернете\n"
        "/status — 📡 статус подключения к AI\n"
        "/install — 📦 установить бота (PowerShell)\n"
        "/установить — то же самое (по-русски)\n"
        "/update — 🔄 обновить бота (PowerShell)\n"
        "/обновить — то же самое (по-русски)\n"
        "/help — показать эту подсказку\n\n"
        "Или просто напишите что-нибудь — бот ответит через AI.",
        parse_mode="HTML",
    )


async def main() -> None:
    logging.info(
        "Starting drgr-bot (mode=%s, configured_backend=%s, active_backend=%s)…",
        BOT_MODE, AI_BACKEND, ACTIVE_BACKEND,
    )

    if BOT_MODE == "webhook" and WEBHOOK_URL:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        from aiohttp import web

        webhook_path = "/webhook"
        full_url = WEBHOOK_URL.rstrip("/") + webhook_path

        await bot.set_webhook(full_url)
        logging.info("Webhook set: %s", full_url)

        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(os.getenv("WEBHOOK_PORT", 8080)))
        await site.start()
        logging.info("Webhook server listening on port %s", os.getenv("WEBHOOK_PORT", 8080))
        await asyncio.Event().wait()
    else:
        # Default: long-polling (works without any external URL or API keys)
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Starting polling…")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
