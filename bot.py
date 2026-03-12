"""
AI Research Agent — Telegram bot that autonomously searches the web,
takes screenshots, analyzes content with Ollama AI, replies with full
articles (text + screenshots + HTML + sources), and logs every action
to the VM self-learning store so the VM can constantly improve itself.
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiofiles
import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, FSInputFile, Message

try:
    from playwright.async_api import async_playwright
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    # Try the new package name first, fall back to the old compatibility shim
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore[no-redef]
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан. Укажи токен в .env файле или через настройки VM на http://localhost:5000/"
    )

OLLAMA_BASE        = os.getenv("OLLAMA_HOST",        "http://localhost:11434")
VM_BASE            = os.getenv("VM_BASE",            "http://localhost:5000")
OLLAMA_MODEL       = os.getenv("OLLAMA_MODEL",       "llama2")
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
MAX_SCREENSHOTS    = int(os.getenv("MAX_SCREENSHOTS",    "2"))

SCREENSHOTS_DIR = Path(os.getenv("SCREENSHOTS_DIR", "screenshots"))
ARTICLES_DIR    = Path(os.getenv("ARTICLES_DIR",    "articles"))
LOG_FILE        = os.getenv("LOG_FILE", "bot.log")

SCREENSHOTS_DIR.mkdir(exist_ok=True)
ARTICLES_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Reusable MarkdownV2 fragments
# ---------------------------------------------------------------------------

_MD_INSTALL_CMD = (
    "*Установка и запуск VM \\(PowerShell, Win\\+X → Windows PowerShell\\):*\n"
    "`irm \"https://raw.githubusercontent.com/ybiytsa1983\\-cpu/drgr\\-bot/main/run\\.ps1\" | iex`"
)

_MD_UPDATE_CMD = (
    "*⬇ Обновить \\(PowerShell, Win\\+X → Windows PowerShell\\):*\n"
    "`irm \"https://raw.githubusercontent.com/ybiytsa1983\\-cpu/drgr\\-bot/main/update\\.ps1\" | iex`"
)

_MD_START_CMD = (
    "*▶️ Запуск VM:*\n"
    "`powershell \\-ExecutionPolicy Bypass \\-File "
    "\"$env:USERPROFILE\\\\drgr\\-bot\\\\start\\.ps1\"`"
)

# Plain-text versions (no MarkdownV2 escaping) for fallback messages
_TXT_INSTALL_CMD = (
    "🚀 Установка (PowerShell, Win+X → Windows PowerShell):\n"
    'irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex'
)
_TXT_UPDATE_CMD = (
    "⬇ Обновить (PowerShell, Win+X → Windows PowerShell):\n"
    'irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1" | iex'
)
_TXT_START_CMD = (
    "▶ Запуск VM:\n"
    'powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\\drgr-bot\\start.ps1"'
)

_MD_WEB_URL = "`http://localhost:5000/`"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("AIResearchBot")

# ---------------------------------------------------------------------------
# Bot & dispatcher
# ---------------------------------------------------------------------------

bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ===========================================================================
# ACTION LOGGER
# Every significant agent action is shipped to POST /agent/log on the VM so
# server.py can persist it and use it for self-improvement / retraining.
# ===========================================================================

class ActionLogger:
    """Sends structured action records to the VM self-learning store."""

    def __init__(self, vm_base: str) -> None:
        self._base = vm_base.rstrip("/")

    async def log(
        self,
        action_type: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        success: bool,
        duration_ms: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = {
            "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action_type": action_type,
            "input":       input_data,
            "output":      output_data,
            "success":     success,
            "duration_ms": duration_ms,
            "metadata":    metadata or {},
        }
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self._base}/agent/log",
                    json=record,
                    timeout=aiohttp.ClientTimeout(total=5),
                )
        except Exception as exc:
            logger.debug("ActionLogger.log skipped: %s", exc)

    async def log_search(self, query: str, sources: List[Dict], duration_ms: int) -> None:
        await self.log(
            "search",
            {"query": query},
            {"source_count": len(sources), "titles": [s.get("title", "") for s in sources[:5]]},
            success=len(sources) > 0,
            duration_ms=duration_ms,
        )

    async def log_screenshot(self, url: str, path: str, success: bool, duration_ms: int) -> None:
        await self.log(
            "screenshot",
            {"url": url},
            {"path": path, "saved": success},
            success=success,
            duration_ms=duration_ms,
        )

    async def log_article(
        self,
        query: str,
        title: str,
        model: str,
        source_count: int,
        screenshot_count: int,
        duration_ms: int,
    ) -> None:
        await self.log(
            "article",
            {"query": query, "model": model},
            {
                "title": title,
                "source_count": source_count,
                "screenshot_count": screenshot_count,
            },
            success=True,
            duration_ms=duration_ms,
        )

    async def log_image_description(
        self, image_path: str, description: str, success: bool, duration_ms: int
    ) -> None:
        await self.log(
            "describe_image",
            {"image_path": image_path},
            {"description": description[:300]},
            success=success,
            duration_ms=duration_ms,
        )


action_logger = ActionLogger(VM_BASE)


def _push_tg_message_to_vm(
    from_name: str,
    text: str,
    chat_title: str = "",
    has_photo: bool = False,
    has_document: bool = False,
    file_name: str = "",
) -> None:
    """Fire-and-forget: push a TG message to the VM chat panel via /chat/push."""
    import threading
    import urllib.request as _ureq

    def _do():
        try:
            data: dict = {"from_name": from_name, "text": text}
            if chat_title:
                data["chat_title"] = chat_title
            if has_photo:
                data["has_photo"] = True
            if has_document:
                data["has_document"] = True
                data["file_name"] = file_name
            payload = json.dumps(data).encode()
            req = _ureq.Request(
                f"{VM_BASE}/chat/push",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _ureq.urlopen(req, timeout=3):
                pass
        except Exception as exc:
            logger.debug("_push_tg_message_to_vm: %s", exc)

    threading.Thread(target=_do, daemon=True).start()


# ===========================================================================
# PER-USER CHAT HISTORY  (used by chat_via_vm)
# ===========================================================================

_chat_history: Dict[int, List[Dict[str, str]]] = {}  # user_id -> [{role, text}, ...]
_MAX_CHAT_TURNS = 20  # keep last N turns in context (mirrors _MAX_CHAT_HISTORY_TURNS in server.py)

# Regex matching http/https URLs in plain text (compiled once at module level)
_URL_IN_TEXT_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)

# Russian keywords that signal a web-search intent
_SEARCH_KEYWORDS_RU = (
    "найди", "поищи", "погугли", "загугли",
    "расскажи о ", "расскажи про ",
    "что такое ", "кто такой ", "кто такая ",
    "что нового", "последние новости",
    "новости о ", "новости про ",
)


def _clean_url(raw: str) -> str:
    """Strip trailing punctuation from a URL, but preserve balanced parentheses.

    For example:
      'https://example.com.'        → 'https://example.com'
      'https://example.com/path)'   → 'https://example.com/path'
      'https://en.wikipedia.org/wiki/Python_(language)' → unchanged (parens balanced)
    """
    # Strip simple trailing punctuation (not parentheses yet)
    _simple_punct = frozenset(".,:;!?>")
    while raw and raw[-1] in _simple_punct:
        raw = raw[:-1]
    # Handle trailing ')': strip only if unbalanced (more ')' than '(' in URL)
    while raw and raw[-1] == ")":
        if raw.count("(") < raw.count(")"):
            raw = raw[:-1]
        else:
            break
    return raw


# ===========================================================================
# OLLAMA HELPERS
# ===========================================================================

async def get_ollama_models() -> List[str]:
    """Return list of available Ollama model names.

    Tries the VM /ollama/models endpoint first (auto-discovered Ollama port)
    and falls back to querying Ollama directly.
    """
    # 1. Try VM endpoint (preferred — uses auto-discovered Ollama port)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_BASE}/ollama/models",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    names = [m["name"] for m in data.get("models", [])]
                    if names:
                        return names
    except Exception as exc:
        logger.debug("VM /ollama/models: %s", exc)

    # 2. Fallback: query Ollama directly
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{OLLAMA_BASE}/api/tags",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        logger.warning("Cannot list Ollama models: %s", exc)
    return []


async def get_best_model() -> str:
    """Return the first available Ollama model name, or fall back to OLLAMA_MODEL."""
    models = await get_ollama_models()
    return models[0] if models else OLLAMA_MODEL


async def chat_via_vm(user_id: int, text: str, message: Message) -> bool:
    """Send a conversational message to the VM /chat/stream endpoint (SSE).

    Maintains per-user history (up to _MAX_CHAT_TURNS turns).
    Injects a system context so the model knows it is connected to the VM
    and can explain/suggest use of its capabilities.
    Returns True if the VM responded successfully, False otherwise
    (caller should fall back to research_and_reply).
    """
    model = await get_best_model()
    history = _chat_history.get(user_id, [])

    # Build a VM-awareness system prefix (injected as the first turn context)
    _VM_SYSTEM = (
        "Ты — AI-агент DRGR VM, подключённый к локальной Code VM по адресу "
        f"{VM_BASE}. "
        "Отвечай на русском языке, кратко и по делу.\n\n"
        "Возможности пользователя (команды Telegram-бота):\n"
        "• /visor <url> или /browse <url> — 🖥 ВИЗОР: скриншот страницы + AI анализ vision-моделью\n"
        "• /visor watch <url> — слежение за изменениями на странице\n"
        "• /agent <задание> — автономный браузер-агент (Playwright + vision): кликает, заполняет формы\n"
        "• /research <запрос> — текстовый веб-агент: ищет в интернете, читает страницы\n"
        "• /search <тема> — исследование с полной статьёй и скриншотами\n"
        "• /code <задача> — написать и выполнить код (Python, JS, HTML)\n"
        "• /generate <описание> — сгенерировать HTML-страницу\n"
        "• /convert — конвертер файлов\n"
        "• Пришли URL в чат → бот автоматически сделает скриншот + AI анализ\n"
        "• Пришли файл .py/.js/.sh → VM выполнит и вернёт результат\n\n"
        "ВАЖНО: Ты НЕ можешь самостоятельно открыть браузер или сделать поиск прямо сейчас. "
        "Когда пользователь просит найти что-то в интернете — скажи ему использовать "
        "/research или /agent. Когда просит открыть URL — скажи прислать URL в чат или "
        "использовать /visor. Не выдумывай информацию из интернета — ты не подключён к нему.\n"
    )

    full_response = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/chat/stream",
                json={
                    "message":    text,
                    "model":      model,
                    "history":    history,
                    "system":     _VM_SYSTEM,
                },
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    return False
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if "error" in chunk:
                        logger.debug("VM chat/stream error: %s", chunk["error"])
                        return False
                    full_response += chunk.get("token", "")
    except Exception as exc:
        logger.debug("VM chat/stream unreachable: %s", exc)
        return False

    if not full_response.strip():
        return False

    # Persist updated history
    history = history + [
        {"role": "user", "text": text},
        {"role": "assistant", "text": full_response},
    ]
    _chat_history[user_id] = history[-_MAX_CHAT_TURNS * 2:]

    # Log the chat action to VM for self-learning
    await action_logger.log(
        "chat",
        {"user_id": user_id, "message": text[:200]},
        {"length": len(full_response)},
        True,
    )

    # Split long replies into chunks to respect Telegram 4096-char limit
    for chunk in _split_text(full_response, 4000):
        try:
            await message.answer(chunk)
        except Exception:
            await message.answer(chunk, parse_mode=None)
    return True


async def ask_ollama(prompt: str, model: Optional[str] = None) -> str:
    """Generate text with Ollama.

    Tries the VM /ollama/ask endpoint first (uses VM's auto-discovered Ollama
    port), then falls back to querying Ollama directly.
    Returns empty string on failure.
    """
    model = model or OLLAMA_MODEL
    # 1. Try VM endpoint (preferred — uses auto-discovered Ollama port)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/ollama/ask",
                json={"model": model, "prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    text = data.get("response", "")
                    if text:
                        return text
    except Exception as exc:
        logger.debug("VM /ollama/ask: %s", exc)
    # 2. Fallback: query Ollama directly
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response", "")
                err = await resp.text()
                logger.error("Ollama %s: %s", resp.status, err[:200])
    except Exception as exc:
        logger.error("ask_ollama failed: %s", exc)
    return ""


async def describe_image_ollama(image_path: str, model: Optional[str] = None) -> str:
    """
    Describe an image using Ollama vision endpoint or the VM /agent/describe_image.
    Prefers qwen3-vl:8b as the vision model.
    Result is logged to the VM for self-improvement training.
    """
    if not os.path.exists(image_path):
        return ""
    t0 = time.monotonic()
    description = ""

    # 1. Try VM dedicated endpoint (auto-selects best vision model — qwen3-vl:8b first)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/agent/describe_image",
                json={"image_path": os.path.abspath(image_path)},
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    description = data.get("description", "")
    except Exception as exc:
        logger.debug("VM describe_image: %s", exc)

    # 2. Fallback: call Ollama directly with base64-encoded image
    if not description:
        try:
            with open(image_path, "rb") as fh:
                img_b64 = base64.b64encode(fh.read()).decode()
            # Prefer qwen3-vl, fall back to llava
            vis_model = model or "qwen3-vl:8b"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": vis_model,
                        "prompt": (
                            "Describe this image in detail in Russian. "
                            "Include all visible text, objects, and context."
                        ),
                        "images": [img_b64],
                        "stream": False,
                    },
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        description = data.get("response", "")
        except Exception as exc:
            logger.debug("Ollama vision fallback: %s", exc)

    dur = int((time.monotonic() - t0) * 1000)
    await action_logger.log_image_description(image_path, description, bool(description), dur)
    return description


# ===========================================================================
# WEB SEARCH
# ===========================================================================

async def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search DuckDuckGo via library or fall back to VM /search endpoint."""
    t0 = time.monotonic()
    # Try library first
    if DDG_AVAILABLE:
        try:
            def _sync() -> List[Dict[str, str]]:
                # Support both old (context-manager) and new (direct call) API styles
                try:
                    with DDGS() as ddgs_inst:
                        raw = ddgs_inst.text(query, max_results=max_results)
                except TypeError:
                    # Newer ddgs may not support context-manager style
                    raw = DDGS().text(query, max_results=max_results)
                return [
                    {
                        "title": r.get("title", ""),
                        "href":  r.get("href", "") or r.get("url", ""),
                        "body":  r.get("body", "") or r.get("snippet", ""),
                    }
                    for r in (raw or [])
                ]
            results = await asyncio.to_thread(_sync)
            if results:
                await action_logger.log_search(f"ddg:{query}", results, int((time.monotonic()-t0)*1000))
                return results
        except Exception as exc:
            logger.warning("DuckDuckGo library: %s", exc)

    # Fall back to VM /search endpoint (works without duckduckgo-search library)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/search",
                json={"query": query, "max_results": max_results},
                # 20s: server-side search may need to try ddgs + HTML scraping in sequence
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success") and data.get("results"):
                        results = [
                            {
                                "title": r.get("title", ""),
                                "href":  r.get("url", "") or r.get("href", ""),
                                "body":  r.get("snippet", "") or r.get("body", ""),
                            }
                            for r in data["results"]
                        ]
                        await action_logger.log_search(f"vm:{query}", results, int((time.monotonic()-t0)*1000))
                        return results
    except Exception as exc:
        logger.warning("VM /search fallback: %s", exc)
        await action_logger.log("search", {"query": f"ddg:{query}"}, {"error": str(exc)}, False)
    return []


async def search_wikipedia(query: str) -> Dict[str, str]:
    """Fetch Wikipedia summary; log action to VM."""
    t0 = time.monotonic()
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {
                        "title": f"Wikipedia: {data.get('title', query)}",
                        "href":  data.get("content_urls",{}).get("desktop",{}).get("page",""),
                        "body":  data.get("extract",""),
                    }
                    await action_logger.log_search(
                        f"wiki:{query}", [result], int((time.monotonic()-t0)*1000)
                    )
                    return result
    except Exception as exc:
        logger.warning("Wikipedia: %s", exc)
    return {}


async def search_reddit(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Search Reddit posts via Reddit JSON API (no auth required)."""
    t0 = time.monotonic()
    results: List[Dict[str, str]] = []
    try:
        url = (
            f"https://www.reddit.com/search.json"
            f"?q={quote_plus(query)}&sort=relevance&limit={max_results}&type=link"
        )
        headers = {"User-Agent": "drgr-bot/1.0 (+https://github.com/ybiytsa1983-cpu/drgr-bot)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for child in data.get("data", {}).get("children", [])[:max_results]:
                        post = child.get("data", {})
                        title = post.get("title", "")
                        permalink = post.get("permalink", "")
                        href = f"https://www.reddit.com{permalink}" if permalink else ""
                        selftext = (post.get("selftext") or post.get("url_overridden_by_dest") or "")[:400]
                        body = post.get("selftext_html") or selftext
                        if title and href:
                            results.append({
                                "title": f"Reddit: {title}",
                                "href":  href,
                                "body":  body,
                            })
        if results:
            await action_logger.log_search(f"reddit:{query}", results, int((time.monotonic()-t0)*1000))
    except Exception as exc:
        logger.warning("Reddit search: %s", exc)
    return results


async def search_hackernews(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Search Hacker News via Algolia API (no auth required)."""
    t0 = time.monotonic()
    results: List[Dict[str, str]] = []
    try:
        url = (
            f"https://hn.algolia.com/api/v1/search"
            f"?query={quote_plus(query)}&hitsPerPage={max_results}&tags=story"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for hit in data.get("hits", [])[:max_results]:
                        title = hit.get("title", "")
                        story_url = hit.get("url", "")
                        hn_url = f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
                        href = story_url or hn_url
                        body = (hit.get("story_text") or "")[:400]
                        if title and href:
                            results.append({
                                "title": f"HackerNews: {title}",
                                "href":  href,
                                "body":  body,
                            })
        if results:
            await action_logger.log_search(f"hn:{query}", results, int((time.monotonic()-t0)*1000))
    except Exception as exc:
        logger.warning("HackerNews search: %s", exc)
    return results


# ===========================================================================
# PLAYWRIGHT BROWSER
# ===========================================================================

async def take_screenshot(url: str, output_path: str) -> bool:
    """Capture a screenshot via local Playwright or VM /browse/screenshot endpoint."""
    t0 = time.monotonic()
    success = False
    # Try local Playwright first
    if PLAYWRIGHT_AVAILABLE:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    await page.wait_for_timeout(800)
                    await page.screenshot(path=output_path, full_page=False)
                    success = True
                except PlaywrightTimeout:
                    logger.warning("Screenshot timeout: %s", url)
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("take_screenshot local (%s): %s — trying VM", url, exc)

    # Fall back to VM /browse/screenshot endpoint
    if not success:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{VM_BASE}/browse/screenshot",
                    json={"url": url},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        img_b64 = data.get("screenshot_base64") or data.get("screenshot") or data.get("image") or ""
                        if img_b64:
                            img_bytes = base64.b64decode(img_b64)
                            with open(output_path, "wb") as fh:
                                fh.write(img_bytes)
                            success = True
        except Exception as exc:
            logger.warning("take_screenshot VM (%s): %s", url, exc)

    dur = int((time.monotonic() - t0) * 1000)
    await action_logger.log_screenshot(url, output_path, success, dur)
    return success


async def extract_page_text(url: str, max_chars: int = 3000) -> str:
    """Extract visible text from a page via local Playwright or VM /browse/page."""
    # Try local Playwright first
    if PLAYWRIGHT_AVAILABLE:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    text: str = await page.evaluate(
                        "() => {"
                        "document.querySelectorAll('script,style,nav,footer,header,aside').forEach(e=>e.remove());"
                        "return (document.body||{}).innerText||'';"
                        "}"
                    )
                    if text:
                        return text[:max_chars]
                except Exception:
                    pass
                finally:
                    await browser.close()
        except Exception as exc:
            logger.warning("extract_page_text local (%s): %s — trying VM", url, exc)

    # Fall back to VM /browse/page endpoint
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/browse/page",
                json={"url": url, "max_chars": max_chars},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        return data.get("text", "")
    except Exception as exc:
        logger.error("extract_page_text VM (%s): %s", url, exc)
    return ""


# ===========================================================================
# HTML ARTICLE BUILDER
# ===========================================================================

def _to_data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def _safe_href(url: str) -> str:
    """Return url only if it starts with http(s), otherwise '#'."""
    return url if re.match(r"^https?://", url or "") else "#"


def _build_source_chart_js(sources: List[Dict[str, str]]) -> str:
    """Return a Chart.js bar chart showing word count per source (inline script)."""
    import html as _html
    labels = []
    values = []
    for s in sources[:8]:
        label = _html.escape(s.get("title", "")[:30] or "—")
        word_count = len((s.get("body") or "").split())
        labels.append(label)
        values.append(word_count)
    if not any(v > 0 for v in values):
        return ""
    labels_js  = ", ".join(f'"{l}"' for l in labels)
    values_js  = ", ".join(str(v) for v in values)
    return (
        '<div class="chart-wrap">'
        '<h2>\U0001f4ca Объём данных по источникам</h2>'
        '<canvas id="srcChart" height="120"></canvas>'
        "</div>\n"
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>\n'
        "<script>\n"
        "(function(){\n"
        "  var ctx=document.getElementById('srcChart').getContext('2d');\n"
        "  new Chart(ctx,{\n"
        "    type:'bar',\n"
        "    data:{\n"
        f"      labels:[{labels_js}],\n"
        f"      datasets:[{{label:'Слов в источнике',data:[{values_js}],"
        "backgroundColor:'rgba(14,132,212,0.6)',borderColor:'rgba(14,132,212,1)',"
        "borderWidth:1}}]\n"
        "    },\n"
        "    options:{responsive:true,plugins:{legend:{display:false}},"
        "scales:{y:{beginAtZero:true,ticks:{stepSize:10}}}}\n"
        "  });\n"
        "})();\n"
        "</script>\n"
    )


def _build_svg_diagram(title: str) -> str:
    """Return a simple SVG diagram representing the research pipeline."""
    import html as _html
    t = _html.escape(title[:40])
    return (
        '<div class="svg-wrap">'
        '<h2>\U0001f5fa Структура статьи</h2>'
        '<svg viewBox="0 0 600 90" xmlns="http://www.w3.org/2000/svg" '
        'style="width:100%;max-width:600px;font-family:sans-serif;font-size:12px">\n'
        '  <rect x="10"  y="20" width="110" height="50" rx="8" fill="#0e84d4" opacity=".85"/>\n'
        '  <text x="65"  y="49" text-anchor="middle" fill="#fff">Поиск</text>\n'
        '  <rect x="160" y="20" width="110" height="50" rx="8" fill="#1aad5a" opacity=".85"/>\n'
        '  <text x="215" y="49" text-anchor="middle" fill="#fff">Скриншоты</text>\n'
        '  <rect x="310" y="20" width="110" height="50" rx="8" fill="#e94560" opacity=".85"/>\n'
        '  <text x="365" y="49" text-anchor="middle" fill="#fff">AI-анализ</text>\n'
        '  <rect x="460" y="20" width="110" height="50" rx="8" fill="#7b3f9e" opacity=".85"/>\n'
        f' <text x="515" y="43" text-anchor="middle" fill="#fff">{t}</text>\n'
        '  <text x="515" y="58" text-anchor="middle" fill="#fff" font-size="10">статья</text>\n'
        '  <line x1="120" y1="45" x2="160" y2="45" stroke="#555" stroke-width="2" marker-end="url(#arr)"/>\n'
        '  <line x1="270" y1="45" x2="310" y2="45" stroke="#555" stroke-width="2" marker-end="url(#arr)"/>\n'
        '  <line x1="420" y1="45" x2="460" y2="45" stroke="#555" stroke-width="2" marker-end="url(#arr)"/>\n'
        '  <defs><marker id="arr" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto">'
        '<path d="M0,0 L6,3 L0,6 Z" fill="#555"/></marker></defs>\n'
        "</svg>\n"
        "</div>\n"
    )


def build_html_article(
    title: str,
    body: str,
    sources: List[Dict[str, str]],
    screenshot_paths: List[str],
    image_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """Return a self-contained HTML article with CSS-grid gallery, Chart.js, and SVG diagram."""
    import html as _html
    image_descriptions = image_descriptions or {}

    # ── Photo gallery (CSS grid) ──────────────────────────────────────────
    gallery_items = ""
    valid_screenshots: List[str] = []
    for i, path in enumerate(screenshot_paths[:6]):
        if not os.path.exists(path):
            continue
        uri  = _to_data_uri(path)
        desc = image_descriptions.get(path, "")
        cap  = _html.escape(desc[:120] if desc else f"Рисунок {i + 1}")
        src_href = ""
        if i < len(sources):
            src_href = _safe_href(sources[i].get("href", ""))
        link_open  = f'<a href="{src_href}" target="_blank" rel="noopener noreferrer">' if src_href else ""
        link_close = "</a>" if src_href else ""
        gallery_items += (
            '<figure class="gallery-item">'
            f"{link_open}"
            f'<img src="{uri}" alt="{cap}" loading="lazy"/>'
            f"{link_close}"
            f"<figcaption>{cap}</figcaption>"
            "</figure>\n"
        )
        valid_screenshots.append(path)

    gallery_html = ""
    if gallery_items:
        gallery_html = (
            '<section class="gallery">\n'
            '<h2>\U0001f4f7 Галерея скриншотов</h2>\n'
            '<div class="gallery-grid">\n'
            f"{gallery_items}"
            "</div>\n</section>\n"
        )

    # ── Body: split on markdown-style headings ────────────────────────────
    sections_html = ""
    current_section_lines: List[str] = []

    def _flush_section(lines: List[str]) -> str:
        if not lines:
            return ""
        text = "\n".join(lines).strip()
        if not text:
            return ""
        para = re.sub(r"\n{2,}", "</p><p>", _html.escape(text))
        para = para.replace("\n", "<br>")
        return f'<div class="section-body"><p>{para}</p></div>\n'

    for raw_line in body.splitlines():
        line = raw_line.strip()
        # Treat lines starting with # / ## / ### as section headings
        if re.match(r"^#{1,3}\s+", line):
            sections_html += _flush_section(current_section_lines)
            current_section_lines = []
            heading_text = _html.escape(re.sub(r"^#{1,3}\s+", "", line))
            sections_html += f"<h2>{heading_text}</h2>\n"
        else:
            current_section_lines.append(raw_line)
    sections_html += _flush_section(current_section_lines)

    # ── Sources list ──────────────────────────────────────────────────────
    sources_items = "".join(
        f'<li><a href="{_safe_href(s.get("href",""))}" target="_blank" rel="noopener noreferrer">'
        f'{_html.escape(s.get("title", f"Источник {i+1}"))}</a></li>\n'
        for i, s in enumerate(sources)
    )

    # ── Chart.js + SVG ───────────────────────────────────────────────────
    chart_html = _build_source_chart_js(sources)
    svg_html   = _build_svg_diagram(title)

    # ── CSS ───────────────────────────────────────────────────────────────
    css = (
        "body{font-family:Georgia,serif;max-width:960px;margin:0 auto;padding:24px;"
        "background:#f4f4f4;color:#222}"
        "h1{color:#1a1a2e;border-bottom:3px solid #e94560;padding-bottom:8px;margin-bottom:20px}"
        "h2{color:#16213e;margin-top:28px;margin-bottom:8px}"
        "article{background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12)}"
        ".section-body p{line-height:1.8;margin:0 0 12px}"
        "blockquote{border-left:3px solid #e94560;margin:10px 0;padding-left:15px;"
        "color:#555;font-style:italic}"
        ".gallery{margin:32px 0}"
        ".gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));"
        "gap:16px;margin-top:12px}"
        ".gallery-item{background:#f9f9f9;border-radius:8px;overflow:hidden;"
        "box-shadow:0 2px 6px rgba(0,0,0,.1);transition:transform .2s}"
        ".gallery-item:hover{transform:translateY(-3px)}"
        ".gallery-item img{width:100%;display:block;border-bottom:1px solid #ddd}"
        ".gallery-item figcaption{padding:8px 10px;font-size:.82em;color:#555;font-style:italic}"
        ".gallery-item a{display:block}"
        ".chart-wrap{margin:32px 0;background:#f9f9f9;border-radius:8px;padding:20px;"
        "border:1px solid #e0e0e0}"
        ".svg-wrap{margin:32px 0}"
        ".sources{background:#f9f9f9;border-left:4px solid #e94560;padding:16px 20px;"
        "margin-top:32px;border-radius:0 6px 6px 0}"
        ".sources h3{color:#e94560;margin-top:0}"
        ".sources a{color:#0f3460;word-break:break-all}"
        ".sources ol{padding-left:20px}"
        ".sources li{margin-bottom:6px;line-height:1.5}"
    )

    return (
        '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_html.escape(title)}</title>\n"
        f"<style>{css}</style>\n"
        f"</head>\n<body>\n<article>\n<h1>{_html.escape(title)}</h1>\n"
        f"{svg_html}"
        f"{gallery_html}"
        f'<section class="article-body">\n{sections_html}</section>\n'
        f"{chart_html}"
        '<div class="sources">\n<h3>\U0001f4da Источники</h3>\n'
        f"<ol>{sources_items}</ol>\n</div>\n"
        "</article>\n</body>\n</html>"
    )


# ===========================================================================
# RESEARCH PIPELINE
# ===========================================================================

async def research_and_reply(query: str, message: Message) -> None:
    """
    Full autonomous research pipeline:
      1. Search DuckDuckGo + Wikipedia + Reddit + HackerNews (parallel)
      2. Take screenshots of top pages
      3. Describe screenshots with Ollama vision (background)
      4. Generate article with Ollama text model
      5. Reply: text + screenshots + HTML (CSS grid gallery, Chart.js, SVG) + sources
      6. All actions logged to VM for self-improvement
    """
    t0     = time.monotonic()
    status = await message.answer("\U0001f50d Ищу информацию\u2026")

    # 1. Search all sources in parallel
    ddg_task     = asyncio.create_task(search_duckduckgo(query, MAX_SEARCH_RESULTS))
    wiki_task    = asyncio.create_task(search_wikipedia(query))
    reddit_task  = asyncio.create_task(search_reddit(query, max_results=3))
    hn_task      = asyncio.create_task(search_hackernews(query, max_results=3))
    ddg_results, wiki_result, reddit_results, hn_results = await asyncio.gather(
        ddg_task, wiki_task, reddit_task, hn_task
    )

    all_sources: List[Dict[str, str]] = []
    if wiki_result.get("body"):
        all_sources.append(wiki_result)
    all_sources.extend(ddg_results)
    all_sources.extend(reddit_results)
    all_sources.extend(hn_results)

    if not all_sources:
        await status.edit_text(
            "❌ Ничего не найдено по запросу\\. Попробуйте другой запрос\\.",
            parse_mode="MarkdownV2",
        )
        await action_logger.log(
            "research", {"query": query}, {"error": "no sources"}, False,
            int((time.monotonic() - t0) * 1000),
        )
        return

    await status.edit_text(
        f"\U0001f4d6 Найдено {len(all_sources)} источников "
        f"(DDG, Wikipedia, Reddit, HackerNews). Делаю скриншоты\u2026"
    )

    # 2. Screenshots
    screenshot_paths: List[str] = []
    image_descriptions: Dict[str, str] = {}

    for src in all_sources[:MAX_SCREENSHOTS + 2]:
        url = src.get("href", "")
        if not url.startswith("http"):
            continue
        slug = hashlib.md5(url.encode()).hexdigest()[:8]
        out  = str(SCREENSHOTS_DIR / f"ss_{slug}_{int(time.time())}.png")
        if await take_screenshot(url, out):
            screenshot_paths.append(out)
            image_descriptions[out] = ""
        if len(screenshot_paths) >= MAX_SCREENSHOTS:
            break

    # 3. Aggregate text for AI (use more sources with multi-source pipeline)
    blocks = [
        f"[{s['title']}]: {s.get('body','')[:600]}"
        for s in all_sources[:10]
        if s.get("body")
    ]
    aggregated = "\n\n".join(blocks)

    await status.edit_text("\U0001f916 Генерирую статью\u2026")

    # 4. Ollama article
    model  = await get_best_model()

    prompt = (
        f'Ты — экспертный AI-журналист. Напиши полноценную статью на русском языке по теме: "{query}".\n\n'
        f"Данные из источников (DuckDuckGo, Wikipedia, Reddit, HackerNews):\n{aggregated}\n\n"
        "Требования:\n"
        "1. Дай заголовок статьи (первая строка, без # или *).\n"
        "2. Введение (2-3 предложения, без заголовка).\n"
        "3. Несколько разделов с подзаголовками (формат: ## Название раздела).\n"
        "4. Выдели редкую и малоизвестную информацию по теме (## Интересные факты).\n"
        "5. Заключение (## Заключение).\n"
        "Пиши связно и информативно."
    )
    article_text = await ask_ollama(prompt, model)
    if not article_text:
        article_text = f"{query}\n\n" + aggregated

    # 5. Build and save HTML
    lines = article_text.strip().splitlines()
    title = lines[0].lstrip("#* ").strip() if lines else query
    html  = build_html_article(title, article_text, all_sources, screenshot_paths, image_descriptions)
    ts    = int(time.time())
    article_path = str(ARTICLES_DIR / f"article_{ts}.html")
    async with aiofiles.open(article_path, "w", encoding="utf-8") as fh:
        await fh.write(html)

    # 6. Log the full article event to VM
    total_dur = int((time.monotonic() - t0) * 1000)
    await action_logger.log_article(
        query, title, model, len(all_sources), len(screenshot_paths), total_dur
    )

    # 7. Describe screenshots in background (enriches training data)
    for path in screenshot_paths:
        asyncio.create_task(describe_image_ollama(path))

    # 8. Send to Telegram
    try:
        await status.delete()
    except Exception:
        pass  # message may have been deleted already

    header = f"\U0001f4f0 *{_esc(title)}*\n\n"
    chunks = _split_text(article_text, 4000)
    first  = True
    for chunk in chunks[:4]:
        if not chunk.strip():
            continue
        prefix = header if first else ""
        first  = False
        try:
            await message.answer(prefix + _esc(chunk), parse_mode="MarkdownV2")
        except Exception:
            plain = _unescape_md(prefix + chunk)
            try:
                await message.answer(plain[:4096])
            except Exception:
                pass

    for i, path in enumerate(screenshot_paths):
        if os.path.exists(path):
            try:
                src_title = all_sources[i].get("title", "") if i < len(all_sources) else ""
                cap = f"\U0001f4f8 Скриншот {i+1} — {src_title[:60]}"
                await message.answer_photo(FSInputFile(path), caption=cap)
            except Exception as exc:
                logger.warning("screenshot send: %s", exc)

    src_lines = ["\U0001f4da *Источники:*"]
    for i, src in enumerate(all_sources[:10], 1):
        href = src.get("href", "#") or "#"
        ttl  = src.get("title", f"Источник {i}")
        src_lines.append(f"{i}\\. [{_esc(ttl)}]({href})")
    try:
        await message.answer(
            "\n".join(src_lines),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
    except Exception:
        plain = "\U0001f4da Источники:\n" + "\n".join(
            f"{i}. {s.get('title','')} — {s.get('href','')}"
            for i, s in enumerate(all_sources[:10], 1)
        )
        await message.answer(plain[:4096])

    try:
        await message.answer_document(
            FSInputFile(article_path, filename="article.html"),
            caption="\U0001f4c4 Полная HTML-версия статьи",
        )
    except Exception as exc:
        logger.warning("HTML send: %s", exc)


# ===========================================================================
# UTILITY
# ===========================================================================

_ESC_CHARS = r"\_*[]()~`>#+-=|{}.!"


def _esc(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([" + re.escape(_ESC_CHARS) + r"])", r"\\\1", text)


def _unescape_md(text: str) -> str:
    """Remove MarkdownV2 escape backslashes to produce clean plain text."""
    return re.sub(r"\\([_*\[\]()~`>#+\-=|{}.!])", r"\1", text)


def _split_text(text: str, max_len: int) -> List[str]:
    """Split text into chunks no longer than max_len on newline boundaries."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_len:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


# ===========================================================================
# TELEGRAM HANDLERS
# ===========================================================================

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "\U0001f916 *AI Research Agent \\+ Code VM*\n\n"
        "Я автономный агент для исследования, генерации кода и HTML\\.\n\n"
        f"\U0001f5a5 *Веб\\-интерфейс VM \\(откройте в браузере\\):* {_MD_WEB_URL}\n\n"
        "*Команды:*\n"
        "/agent `<задание>` — \U0001f916 автономный браузер\\-агент: Playwright \\+ vision\n"
        "/research `<задание>` — \U0001f50e текстовый агент: ищет, читает страницы, отвечает\n"
        "/search `<запрос>` — исследовать тему, статья \\+ скриншоты\n"
        "/browse `<url>` — скриншот страницы \\+ AI анализ \\(qwen3\\-vl\\)\n"
        "/visor `<url>` — 🖥 ВИЗОР: скриншот \\+ AI анализ \\(qwen3\\-vl\\)\n"
        "/code `[python|js|html|...]` `<задача>` — написать, запустить, исправить\n"
        "/execute `<код>` — выполнить код в VM sandbox\n"
        "/download `<url>` — \U0001f4e5 скачать файл по URL\n"
        "/generate `<описание>` — HTML\\-страница \\(скачать файл\\)\n"
        "/screenshot `<url>` — быстрый скриншот страницы\n"
        "/convert — форматы конвертера; отправьте фото или файл \\(json/csv/md/html\\) для конвертации\n"
        "/retrain — запустить цикл самообучения VM\n"
        "/vm — статус VM, URL и команда запуска\n"
        "/update — скачать и установить новые файлы\n"
        "/settoken — сохранить новый токен бота\n"
        "/models — доступные AI\\-модели\n"
        "/stats — статистика самообучения\n"
        "/help — помощь\n\n"
        "_Отправьте фото — AI опишет его \\(или с подписью `jpeg`/`png` — конвертирует\\)_\n"
        "_Отправьте \\.py/\\.js/\\.sh файл — VM выполнит его и вернёт вывод_\n\n"
        "*Или просто напишите запрос* — агент исследует тему и создаст статью\\.\n\n"
        f"\U0001f4bb {_MD_INSTALL_CMD}\n\n"
        f"{_MD_UPDATE_CMD}\n\n"
        "\U0001f5a5 После установки: ярлык *«Code VM»* и *«ЗАПУСТИТЬ ВМ»* на Рабочем столе",
        parse_mode="MarkdownV2",
    )


@router.message(Command("web", "open"))
async def cmd_web(message: Message) -> None:
    """Show the URL to the Code VM web interface (the extension page)."""
    await message.answer(
        "\U0001f5a5 *Code VM — веб\\-интерфейс*\n\n"
        "Откройте в браузере на компьютере, где запущена VM:\n\n"
        f"\U0001f517 {_MD_WEB_URL}\n\n"
        "*Что доступно в веб\\-интерфейсе:*\n"
        "• 🧑‍💻 Monaco редактор кода\n"
        "• 🌐 HTML\\-генератор \\(вкладка **HTML**\\)\n"
        "• 💬 Чат с AI \\(вкладка **AI**\\)\n"
        "• 🖥 ВИЗОР — браузер\\-инспектор\n"
        "• 🔧 Workshop — управление моделями Ollama\n"
        "• ⚙️ Настройки — токен бота, модель, промпт\n\n"
        f"*Если VM не запущена —* {_MD_INSTALL_CMD}\n\n"
        "После установки — двойной клик на ярлыке *«Code VM»* на Рабочем столе\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "\U0001f4d6 *Помощь — все команды*\n\n"
        f"\U0001f5a5 *Веб\\-интерфейс:* {_MD_WEB_URL} \\| /web\n\n"
        "*Автономный агент и браузер:*\n"
        "• `/agent <задание>` — \U0001f916 автономный браузер\\-агент: Playwright \\+ vision модель\n"
        "• `/research <задание>` — \U0001f50e текстовый агент: ищет в интернете, читает страницы, отвечает\n"
        "• `/search <тема>` — полное исследование, статья \\+ скриншоты \\+ HTML\n"
        "• `/visor <url>` — 🖥 ВИЗОР: скриншот \\+ AI анализ \\(qwen3\\-vl:8b\\)\n"
        "• `/visor watch <url>` — слежение за изменениями на странице \\(3 снимка\\)\n"
        "• `/browse <url>` — скриншот страницы \\+ AI анализ \\(qwen3\\-vl:8b\\)\n"
        "• `/screenshot <url>` — быстрый скриншот с описанием\n\n"
        "*Генерация и выполнение кода:*\n"
        "• `/code <задача>` — написать код, запустить, исправить ошибки, прислать файл\n"
        "• `/code python|js|html|go|... <задача>` — выбрать язык\n"
        "• `/execute <код>` — выполнить код в VM sandbox\n"
        "• `/generate <описание>` — HTML\\-страница \\(файл `.html`\\)\n"
        "• _Отправьте \\.py, \\.js, \\.sh файл_ — VM выполнит и вернёт результат\n\n"
        "*Файлы:*\n"
        "• `/download <url>` — \U0001f4e5 скачать файл по URL через VM\n"
        "• _Отправьте любой код\\-файл_ — VM выполнит его\n"
        "• _Отправьте \\.json/\\.csv/\\.html/\\.md_ — конвертация формата\n\n"
        "*VM и самообучение:*\n"
        "• `/web` — ссылка на веб\\-интерфейс Code VM\n"
        "• `/models` — список AI\\-моделей \\(включая drgr\\-visor\\)\n"
        "• `/stats` — что VM узнала из своих действий\n"
        "• `/retrain` — запустить цикл самообучения VM вручную\n"
        "• `/vm` — статус VM и команды запуска\n"
        "• `/update` — команда для скачивания и установки новых файлов\n"
        "• `/settoken <токен>` — сохранить новый токен бота \\(@BotFather\\)\n\n"
        "*Конвертер файлов и фото \\(через VM\\):*\n"
        "• `/convert` — список всех доступных конвертаций\n"
        "• Отправьте фото — AI опишет содержимое \\(vision\\-модель\\)\n"
        "• Отправьте фото с подписью `jpeg`, `png`, `webp` или `bmp` — конвертация изображения\n"
        "• Отправьте файл `.json`, `.csv`, `.html` или `.md` — конвертация текстового формата\n\n"
        f"{_MD_INSTALL_CMD}\n\n"
        "Примеры: `/agent https://github\\.com` или `/research цена Bitcoin сегодня`\n"
        "Просто пришлите URL — ВИЗОР сделает скриншот и AI анализ автоматически\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("models"))
async def cmd_models(message: Message) -> None:
    models = await get_ollama_models()
    if models:
        lines = ["\U0001f916 *Доступные модели Ollama:*"] + [f"• {_esc(m)}" for m in models]
        await message.answer("\n".join(lines), parse_mode="MarkdownV2")
    else:
        await message.answer(
            "\u26a0\ufe0f Ollama не запущена или нет доступных моделей\\.\n\n"
            "Запустите Ollama: `ollama serve`\n"
            f"Потом скачайте модель: `ollama pull {_esc(OLLAMA_MODEL)}`\n\n"
            f"_Если недавно было обновление — попробуйте_ /update _чтобы скачать новые файлы_",
            parse_mode="MarkdownV2",
        )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show VM self-learning statistics."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_BASE}/agent/stats",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    aa    = data.get("agent_actions", {})
                    inst  = data.get("training_instructions", [])
                    text  = (
                        "\U0001f9e0 *Статистика самообучения VM*\n\n"
                        f"\U0001f50d Поисков: *{_esc(str(aa.get('total_searches', 0)))}*\n"
                        f"\U0001f4f8 Скриншотов: *{_esc(str(aa.get('total_screenshots', 0)))}*\n"
                        f"\U0001f4f0 Статей: *{_esc(str(aa.get('total_articles', 0)))}*\n"
                        f"\U0001f5bc Описаний картинок: *{_esc(str(aa.get('total_image_descriptions', 0)))}*\n"
                        f"\U0001f504 Циклов обучения: *{_esc(str(aa.get('retrain_cycles', 0)))}*\n"
                        f"\U0001f4cb Правил сейчас: *{_esc(str(len(inst)))}*\n\n"
                        "Последние правила:\n"
                        + "\n".join(f"• {_esc(r[:80])}" for r in inst[-3:])
                    )
                    await message.answer(text, parse_mode="MarkdownV2")
                    return
    except Exception as exc:
        logger.warning("stats endpoint: %s", exc)
    await message.answer(
        "\u26a0\ufe0f VM не отвечает\\. Убедитесь, что vm/server\\.py запущен\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("retrain"))
async def cmd_retrain(message: Message) -> None:
    """Trigger a VM self-improvement cycle via POST /retrain."""
    status = await message.answer("\U0001f504 Запускаю цикл самообучения VM\u2026")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/retrain",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        inst  = data.get("training_instructions", [])
                        aa    = data.get("agent_actions", {})
                        stats = data.get("statistics", {})
                        text  = (
                            "\U0001f9e0 *Самообучение завершено\\!*\n\n"
                            f"\U0001f504 Циклов всего: *{_esc(str(aa.get('retrain_cycles', 0)))}*\n"
                            f"\u2705 Успешных запусков: *{_esc(str(stats.get('successful_runs', 0)))}*\n"
                            f"\u274c Ошибок: *{_esc(str(stats.get('failed_runs', 0)))}*\n"
                            f"\U0001f4cb Правил сейчас: *{_esc(str(len(inst)))}*\n\n"
                            "Последние правила:\n"
                            + "\n".join(f"\u2022 {_esc(r[:80])}" for r in inst[-3:])
                        )
                        await status.delete()
                        await message.answer(text, parse_mode="MarkdownV2")
                        return
                    error = data.get("error", "Неизвестная ошибка")
                    await status.edit_text(f"\u274c {error[:300]}")
                    return
    except Exception as exc:
        logger.warning("cmd_retrain: %s", exc)
    await status.edit_text(
        "\u26a0\ufe0f VM не отвечает\\. Убедитесь, что vm/server\\.py запущен\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("screenshot"))
async def cmd_screenshot(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/screenshot <url>`", parse_mode="MarkdownV2")
        return
    url = parts[1].strip()
    if not url.startswith("http"):
        url = "https://" + url
    status = await message.answer("📸 Делаю скриншот…")
    out = str(SCREENSHOTS_DIR / f"manual_{int(time.time())}.png")
    ok  = await take_screenshot(url, out)
    await status.delete()
    if ok and os.path.exists(out):
        desc    = await describe_image_ollama(out)
        caption = f"\U0001f310 {url[:200]}"
        if desc:
            caption += f"\n\n\U0001f5bc {desc[:200]}"
        await message.answer_photo(FSInputFile(out), caption=caption[:1024])
    else:
        await message.answer(
            "\u274c Не удалось сделать скриншот\\. Проверьте URL\\.",
            parse_mode="MarkdownV2",
        )


@router.message(Command("browse"))
async def cmd_browse(message: Message) -> None:
    """Screenshot a URL and analyse it with qwen3-vl:8b vision AI.

    Usage: /browse <url>
    Uses the VM /browse/screenshot endpoint which runs Playwright headless and
    describes the result with the best available vision model (qwen3-vl:8b).
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🌐 *Браузер + AI анализ страницы*\n\n"
            "Использование: `/browse <url>`\n\n"
            "Примеры:\n"
            "• `/browse https://google.com`\n"
            "• `/browse github.com`\n\n"
            "Делает скриншот страницы и анализирует её с помощью qwen3\\-vl:8b",
            parse_mode="MarkdownV2",
        )
        return

    url = parts[1].strip()
    if not url.startswith("http"):
        url = "https://" + url

    status = await message.answer(f"🌐 Делаю скриншот и анализирую `{url[:80]}`\u2026", parse_mode="MarkdownV2")
    t0 = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/browse/screenshot",
                json={"url": url},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    await status.edit_text(f"\u274c VM вернула ошибку {resp.status}")
                    return
                data = await resp.json()
    except Exception as exc:
        await status.edit_text(f"\u274c Ошибка: {str(exc)[:200]}")
        return

    dur = int((time.monotonic() - t0) * 1000)
    screenshot_b64 = data.get("screenshot_base64", "")
    description    = data.get("description", "")
    model_used     = data.get("model", "")
    success        = data.get("success", False)

    await status.delete()

    await action_logger.log(
        "browse_screenshot",
        {"url": url},
        {"has_screenshot": bool(screenshot_b64), "description": description[:200]},
        success,
        dur,
        {"model": model_used},
    )

    if screenshot_b64:
        import base64 as _b64
        img_bytes = _b64.b64decode(screenshot_b64)
        ts = int(time.time())
        shot_path = str(SCREENSHOTS_DIR / f"browse_{ts}.png")
        with open(shot_path, "wb") as fh:
            fh.write(img_bytes)

        caption = f"🌐 {url[:100]}"
        if model_used:
            caption += f"\n🧠 Модель: {model_used}"
        if description:
            caption += f"\n\n{description[:800]}"

        try:
            await message.answer_photo(FSInputFile(shot_path), caption=caption[:1024])
        except Exception:
            # If photo too large send as document
            try:
                await message.answer_document(
                    FSInputFile(shot_path, filename="screenshot.png"),
                    caption=caption[:1024],
                )
            except Exception as exc:
                await message.answer(caption[:4096])
        return

    # No screenshot — text fallback
    text_fb = data.get("text_fallback", False)
    fallback_desc = description or data.get("error", "Нет данных")
    prefix = "⚠ Скриншот недоступен.\n\n" if text_fb else "❌ "
    await message.answer(prefix + fallback_desc[:3000])


@router.message(Command("visor"))
async def cmd_visor(message: Message) -> None:
    """Analyse current page in ВИЗОР using qwen3-vl vision AI.

    Usage: /visor <url>     — screenshot + detailed AI analysis
           /visor watch <url> — start watching for page changes (3 snapshots)
    """
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "🖥 *ВИЗОР — браузер\\-инспектор*\n\n"
            "Команды:\n"
            "• `/visor <url>` — скриншот \\+ AI анализ страницы\n"
            "• `/visor watch <url>` — слежение за изменениями \\(3 снимка\\)\n\n"
            "Примеры:\n"
            "• `/visor https://google\\.com`\n"
            "• `/visor watch https://news\\.ycombinator\\.com`\n\n"
            "Использует qwen3\\-vl:8b или drgr\\-visor \\(переученная модель\\)",
            parse_mode="MarkdownV2",
        )
        return

    # /visor watch <url>
    if parts[1].lower() == "watch" and len(parts) >= 3:
        watch_url = parts[2].strip()
        if not watch_url.startswith("http"):
            watch_url = "https://" + watch_url

        status = await message.answer(
            f"👁 Слежу за изменениями на `{watch_url[:80]}`\\.\\.\\. (3 снимка с интервалом 10 сек)",
            parse_mode="MarkdownV2",
        )
        t0 = time.monotonic()
        results = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{VM_BASE}/visor/watch",
                    json={"url": watch_url, "interval": 10, "max_snapshots": 3},
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            break
                        try:
                            snap = json.loads(payload)
                            if snap.get("description"):
                                results.append(snap)
                        except ValueError:
                            continue
        except Exception as exc:
            await status.edit_text(f"❌ Ошибка: {str(exc)[:200]}")
            return

        await status.delete()
        dur = int((time.monotonic() - t0) * 1000)

        if not results:
            await message.answer("❌ Не удалось получить снимки. Проверьте URL и наличие Playwright.")
            return

        report = f"👁 *Наблюдение за страницей* — {watch_url[:60]}\n\n"
        for snap in results:
            n = snap.get("snapshot", "?")
            desc = snap.get("description", "")[:500]
            change = snap.get("change", "")
            report += f"*Снимок {n}:* {desc}\n"
            if change:
                report += f"🔄 {change}\n"
            report += "\n"
        report += f"⏱ {dur // 1000} сек | модель: {results[0].get('model', '?') if results else '?'}"

        try:
            await message.answer(report[:4096])
        except Exception:
            await message.answer(report[:4096], parse_mode=None)
        return

    # /visor <url> — same as /browse but with explicit ВИЗОР framing
    url = parts[1].strip()
    if not url.startswith("http"):
        url = "https://" + url

    status = await message.answer(
        f"🖥 ВИЗОР анализирует `{url[:80]}`\\.\\.\\.",
        parse_mode="MarkdownV2",
    )
    t0 = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/browse/screenshot",
                json={"url": url},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    await status.edit_text(f"❌ VM вернула ошибку {resp.status}")
                    return
                data = await resp.json()
    except Exception as exc:
        await status.edit_text(f"❌ Ошибка: {str(exc)[:200]}")
        return

    dur = int((time.monotonic() - t0) * 1000)
    screenshot_b64 = data.get("screenshot_base64", "")
    description    = data.get("description", "")
    model_used     = data.get("model", "")

    await status.delete()

    if screenshot_b64:
        import base64 as _b64
        img_bytes = _b64.b64decode(screenshot_b64)
        ts = int(time.time())
        shot_path = str(SCREENSHOTS_DIR / f"visor_{ts}.png")
        with open(shot_path, "wb") as fh:
            fh.write(img_bytes)

        caption = f"🖥 ВИЗОР: {url[:80]}"
        if model_used:
            caption += f"\n🧠 {model_used}"
        if description:
            caption += f"\n\n{description[:800]}"

        try:
            await message.answer_photo(FSInputFile(shot_path), caption=caption[:1024])
        except Exception:
            await message.answer(caption[:4096])
    else:
        desc = description or data.get("error", "Нет данных")
        await message.answer(f"🖥 ВИЗОР: {url}\n\n{desc[:3000]}")


@router.message(Command("generate"))
async def cmd_generate(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/generate <описание>`", parse_mode="MarkdownV2")
        return
    prompt = parts[1].strip()
    status = await message.answer(
        "\U0001f528 Генерирую HTML\\-страницу через VM\u2026", parse_mode="MarkdownV2"
    )
    try:
        model = await get_best_model()
        full_html = ""

        # Use the streaming endpoint so the bot stays responsive during generation
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/generate/html/stream",
                json={"prompt": prompt, "model": model},
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status == 200:
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if "error" in chunk:
                            await status.edit_text(f"\u274c {chunk['error'][:300]}")
                            return
                        full_html += chunk.get("token", "")

        if full_html.strip():
            ts   = int(time.time())
            path = str(ARTICLES_DIR / f"gen_{ts}.html")
            async with aiofiles.open(path, "w", encoding="utf-8") as fh:
                await fh.write(full_html)
            await status.delete()
            await action_logger.log(
                "generate_html",
                {"prompt": prompt, "model": model},
                {"path": path, "length": len(full_html)},
                True,
            )
            await message.answer_document(
                FSInputFile(path, filename=f"page_{ts}.html"),
                caption=f"\U0001f4c4 HTML по запросу: {prompt[:100]}",
            )
            return

        await status.edit_text(
            "\u274c VM не вернула HTML\\.\n\n"
            f"Убедитесь, что VM и Ollama запущены\\. {_MD_WEB_URL}\n\n"
            f"Для обновления файлов: /update\n\n"
            "Подробности: /vm",
            parse_mode="MarkdownV2",
        )
    except Exception as exc:
        logger.error("generate failed: %s", exc)
        await action_logger.log(
            "generate_html", {"prompt": prompt}, {"error": str(exc)}, False
        )
        await status.edit_text(
            "\u274c VM не запущена или недоступна\\.\n\n"
            f"\U0001f4bb {_MD_INSTALL_CMD}\n\n"
            f"{_MD_UPDATE_CMD}\n\n"
            f"После запуска откройте: {_MD_WEB_URL}\n"
            "Или используйте /vm для подробностей\\.",
            parse_mode="MarkdownV2",
        )


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/search <запрос>`", parse_mode="MarkdownV2")
        return
    await research_and_reply(parts[1].strip(), message)


# ---------------------------------------------------------------------------
# /code command — generate code and send as downloadable file
# ---------------------------------------------------------------------------

_LANG_ALIASES: Dict[str, str] = {
    "python": "python", "py": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "go": "go", "golang": "go",
    "rust": "rust", "rs": "rust",
    "cpp": "cpp", "c++": "cpp",
    "c": "c",
    "java": "java",
    "bash": "bash", "sh": "bash",
    "php": "php",
    "ruby": "ruby", "rb": "ruby",
    "swift": "swift",
    "kotlin": "kotlin", "kt": "kotlin",
    "html": "html",
    "css": "css",
    "sql": "sql",
}

_LANG_EXT: Dict[str, str] = {
    "python": "py", "javascript": "js", "typescript": "ts",
    "go": "go", "rust": "rs", "cpp": "cpp", "c": "c",
    "java": "java", "bash": "sh", "php": "php",
    "ruby": "rb", "swift": "swift", "kotlin": "kt",
    "html": "html", "css": "css", "sql": "sql",
}


@router.message(Command("code"))
async def cmd_code(message: Message) -> None:
    """Generate code, execute it, auto-fix errors, and send the verified file.

    Uses POST /generate/auto/complete which iterates up to 3 times:
      1. Generate code with Ollama
      2. Execute it in the VM sandbox
      3. If it fails: re-prompt with the error and try again

    Usage:
      /code <task description>            — auto-detect language
      /code python <task description>
      /code js <task description>
      /code html <task description>
    """
    parts = (message.text or "").split(maxsplit=2)

    if len(parts) < 2:
        await message.answer(
            "\U0001f4bb *Генерация и проверка кода*\n\n"
            "Использование:\n"
            "`/code <задача>` — автовыбор языка\n"
            "`/code python|js|html|go|rust|cpp|... <задача>`\n\n"
            "VM автоматически:\n"
            "1\\. Пишет код\n"
            "2\\. Запускает его\n"
            "3\\. Исправляет ошибки \\(до 3 попыток\\)\n"
            "4\\. Отправляет проверенный рабочий файл\n\n"
            "Примеры:\n"
            "• `/code python скрипт для парсинга JSON файла`\n"
            "• `/code js анимированный счётчик`\n"
            "• `/code html лендинг для кофейни`",
            parse_mode="MarkdownV2",
        )
        return

    # Determine language and prompt
    lang   = ""
    prompt = ""
    if len(parts) >= 3 and parts[1].lower() in _LANG_ALIASES:
        lang   = _LANG_ALIASES[parts[1].lower()]
        prompt = parts[2]
    else:
        prompt = " ".join(parts[1:])

    if not prompt.strip():
        await message.answer("Укажите описание задачи после команды.")
        return

    ext    = _LANG_EXT.get(lang, lang or "py")
    lang_label = f" {lang}" if lang else ""
    status = await message.answer(
        f"\u2699\ufe0f Пишу{_esc(lang_label)} код\\, запускаю\\, проверяю\u2026",
        parse_mode="MarkdownV2",
    )

    try:
        model  = await get_best_model()

        # Use auto-complete endpoint: generates + executes + auto-fixes
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/generate/auto/complete",
                json={"model": model, "prompt": prompt, "max_attempts": 3},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status == 200:
                    data     = await resp.json()
                    code     = data.get("code", "")
                    output   = data.get("output", "")
                    lang_det = data.get("language", lang or "python")
                    success  = data.get("success", False)
                    attempts = data.get("attempts", 1)
                    err_msg  = data.get("error", "")

                    if code:
                        ts   = int(time.time())
                        ext  = _LANG_EXT.get(lang_det, lang_det)
                        path = str(ARTICLES_DIR / f"code_{ts}.{ext}")
                        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
                            await fh.write(code)
                        await status.delete()
                        await action_logger.log(
                            "generate_code",
                            {"prompt": prompt, "language": lang_det, "model": model},
                            {
                                "path": path, "length": len(code),
                                "attempts": attempts, "success": success,
                            },
                            success,
                        )
                        # Build caption
                        status_icon = "\u2705" if success else "\u26a0\ufe0f"
                        attempt_str = f"{attempts} попытк{'а' if attempts == 1 else 'и' if attempts < 5 else 'ок'}"
                        caption = (
                            f"{status_icon} *{_esc(lang_det.title())}* "
                            f"\\({_esc(attempt_str)}\\) по запросу:\n"
                            f"{_esc(prompt[:200])}"
                        )
                        if output:
                            caption += f"\n\n📤 Вывод:\n`{_esc(output[:300])}`"
                        if not success and err_msg:
                            caption += (
                                f"\n\n⚠ Не удалось исправить за {attempts} попытки\\. "
                                f"Последняя ошибка:\n`{_esc(err_msg[:200])}`"
                            )
                        try:
                            await message.answer_document(
                                FSInputFile(path, filename=f"code_{ts}.{ext}"),
                                caption=caption[:1024],
                                parse_mode="MarkdownV2",
                            )
                        except Exception:
                            await message.answer_document(
                                FSInputFile(path, filename=f"code_{ts}.{ext}"),
                                caption=f"Код готов ({lang_det}, {attempt_str})",
                            )
                        return

                    error_text = data.get("error", "Пустой ответ от модели")
                    await status.edit_text(f"\u274c {error_text[:300]}")
                    return

                text_err = await resp.text()
                await status.edit_text(f"\u274c VM вернула {resp.status}: {text_err[:200]}")
                return

    except Exception as exc:
        logger.error("cmd_code failed: %s", exc)
        await action_logger.log(
            "generate_code",
            {"prompt": prompt, "language": lang},
            {"error": str(exc)},
            False,
        )
    await status.edit_text(
        "\u274c Ошибка генерации\\. Убедитесь, что VM и Ollama запущены\\.",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# /execute (/run) command — run code in the VM sandbox
# ---------------------------------------------------------------------------


@router.message(Command("execute", "run"))
async def cmd_execute(message: Message) -> None:
    """Execute code in the VM sandbox via POST /execute.

    Usage:
      /execute <code>                — Python by default
      /execute python|js <code>
      /run <code>
    """
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "\U0001f4bb *Выполнение кода в VM*\n\n"
            "Использование:\n"
            "`/execute <код>` — Python \\(по умолчанию\\)\n"
            "`/execute python|js <код>` — выбрать язык\n\n"
            "Примеры:\n"
            "• `/execute print\\('Hello, World\\!'\\)`\n"
            "• `/execute js console\\.log\\('test'\\)`",
            parse_mode="MarkdownV2",
        )
        return

    lang = "python"
    code = ""
    if len(parts) >= 3 and parts[1].lower() in ("python", "py", "js", "javascript"):
        lang = "python" if parts[1].lower() in ("python", "py") else "javascript"
        code = parts[2]
    else:
        code = " ".join(parts[1:])

    if not code.strip():
        await message.answer("Укажите код для выполнения.")
        return

    status = await message.answer(f"\u2699\ufe0f Выполняю {lang} код в VM\u2026")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/execute",
                json={"code": code, "language": lang},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data    = await resp.json()
                    output  = data.get("output", "")
                    error   = data.get("error", "")
                    success = data.get("success", False)
                    await action_logger.log(
                        "execute_code",
                        {"code": code[:200], "language": lang},
                        {"output": output[:200], "success": success},
                        success,
                    )
                    if success:
                        result = (
                            f"\u2705 *{_esc(lang.title())} \u2014 результат:*\n\n"
                            f"```\n{output[:3000] or '(нет вывода)'}\n```"
                        )
                    else:
                        result = (
                            f"\u274c *{_esc(lang.title())} \u2014 ошибка:*\n\n"
                            f"```\n{error[:3000]}\n```"
                        )
                    await status.delete()
                    try:
                        await message.answer(result, parse_mode="MarkdownV2")
                    except Exception:
                        await message.answer(result[:4096], parse_mode=None)
                    return
                text = await resp.text()
                await status.edit_text(f"\u274c VM вернула {resp.status}: {text[:200]}")
                return
    except Exception as exc:
        logger.error("cmd_execute: %s", exc)
        await action_logger.log(
            "execute_code", {"code": code[:200], "language": lang}, {"error": str(exc)}, False
        )
    await status.edit_text(
        "\u274c Ошибка\\. Убедитесь, что VM запущена \\(http://localhost:5000/\\)\\.",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# /convert command — show file converter capabilities
# ---------------------------------------------------------------------------


@router.message(Command("convert"))
async def cmd_convert(message: Message) -> None:
    """Show file converter capabilities available in the VM."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_BASE}/convert/formats",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data      = await resp.json()
                    img_info  = data.get("image", {})
                    text_info = data.get("text", {}).get("conversions", [])

                    lines = ["\U0001f504 *Конвертер файлов VM*\n"]
                    lines.append("*\U0001f5bc Изображения \\(Pillow\\):*")
                    to_fmts = ", ".join(f.upper() for f in img_info.get("to", []))
                    from_fmts = ", ".join(f.upper() for f in img_info.get("from", []))
                    lines.append(f"  Из: `{_esc(from_fmts)}`")
                    lines.append(f"  В:  `{_esc(to_fmts)}`")
                    lines.append(f"  _{_esc(img_info.get('note', ''))}_")

                    lines.append("\n*\U0001f4dd Текстовые форматы:*")
                    for conv in text_info:
                        lines.append(
                            f"  `{_esc(conv['from'])}` → `{_esc(conv['to'])}` — "
                            f"{_esc(conv['description'])}"
                        )

                    lines.append(
                        "\n*API VM:*\n"
                        "`POST http://localhost:5000/convert/image`\n"
                        "`POST http://localhost:5000/convert/text`\n"
                        "`GET  http://localhost:5000/convert/formats`"
                    )
                    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
                    return
    except Exception as exc:
        logger.warning("convert formats: %s", exc)
    await message.answer(
        "\U0001f504 *Конвертер файлов VM*\n\n"
        "\u26a0\ufe0f VM не отвечает\\. Убедитесь, что vm/server\\.py запущен\\.",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# /download command — download a file from a URL via VM /files/download
# ---------------------------------------------------------------------------


@router.message(Command("download"))
async def cmd_download(message: Message) -> None:
    """Download a file from a URL via VM /files/download and send it back.

    Usage: /download <url>
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "\U0001f4e5 *Скачать файл по URL*\n\n"
            "Использование: `/download <url>`\n\n"
            "Примеры:\n"
            "• `/download https://example.com/script.py`\n"
            "• `/download https://raw.githubusercontent.com/user/repo/main/file.js`\n\n"
            "Файл скачивается через VM и отправляется вам как документ\\.",
            parse_mode="MarkdownV2",
        )
        return

    url = parts[1].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    status = await message.answer(
        f"\U0001f4e5 Скачиваю `{_esc(url[:80])}{'...' if len(url) > 80 else ''}`\u2026",
        parse_mode="MarkdownV2",
    )
    t0 = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/files/download",
                json={"url": url, "save": True},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    await status.edit_text(f"\u274c VM вернула {resp.status}: {err[:200]}")
                    return
                data = await resp.json()
    except Exception as exc:
        await status.edit_text(f"\u274c Ошибка: {str(exc)[:200]}")
        return

    dur = int((time.monotonic() - t0) * 1000)

    if not data.get("success"):
        await status.edit_text(f"\u274c {data.get('error', 'Ошибка скачивания')[:300]}")
        return

    await action_logger.log(
        "download_file",
        {"url": url},
        {"filename": data.get("filename", ""), "size": data.get("size", 0)},
        True,
        dur,
    )

    # If file was saved on the VM, serve it back
    saved_path = data.get("path", "")
    # Sanitize filename to prevent path traversal
    raw_name   = data.get("filename") or url.rsplit("/", 1)[-1] or "downloaded_file"
    filename   = re.sub(r"[^\w.\-]", "_", raw_name)[:120] or "downloaded_file"

    if saved_path and os.path.exists(saved_path):
        await status.delete()
        size_kb = os.path.getsize(saved_path) // 1024
        await message.answer_document(
            FSInputFile(saved_path, filename=filename),
            caption=f"\u2705 Скачано: `{_esc(filename)}` \\({size_kb} КБ\\)\n\U0001f517 {_esc(url[:200])}",
            parse_mode="MarkdownV2",
        )
        return

    # If only content returned (not saved to disk), write a temp file
    content = data.get("content", "")
    if content:
        ts   = int(time.time())
        path = str(ARTICLES_DIR / f"download_{ts}_{filename}")
        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(content)
        await status.delete()
        await message.answer_document(
            FSInputFile(path, filename=filename),
            caption=f"\u2705 Скачано: `{_esc(filename)}`\n\U0001f517 {_esc(url[:200])}",
            parse_mode="MarkdownV2",
        )
        return

    await status.edit_text(f"\u274c Файл не получен от VM для URL: {url[:100]}")


# ---------------------------------------------------------------------------
# /agent command — autonomous browsing agent: search + read pages + summarise
# ---------------------------------------------------------------------------


@router.message(Command("research"))
async def cmd_research(message: Message) -> None:
    """Text-based web research agent: searches the web, reads pages, summarises results.

    Usage: /research <task>
    The agent will:
      1. Search DuckDuckGo for the task
      2. Open top pages and extract text via VM /browse/page
      3. Ask Ollama to synthesise the findings
      4. Reply with a detailed answer
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "\U0001f916 *Текстовый веб\\-агент*\n\n"
            "Использование: `/research <задание>`\n\n"
            "Агент автономно:\n"
            "1\\. Ищет информацию в интернете\n"
            "2\\. Открывает страницы и читает их\n"
            "3\\. Анализирует и обобщает найденное\n"
            "4\\. Отвечает подробным отчётом\n\n"
            "Примеры:\n"
            "• `/research последние новости о Python 3.13`\n"
            "• `/research цена Bitcoin сегодня`\n"
            "• `/research как установить Docker на Windows`\n\n"
            "Для автономного браузер\\-агента используйте `/agent`",
            parse_mode="MarkdownV2",
        )
        return

    task   = parts[1].strip()
    status = await message.answer(
        f"\U0001f916 Исследую: _{_esc(task[:120])}_\u2026",
        parse_mode="MarkdownV2",
    )
    t0 = time.monotonic()

    collected_texts: List[str] = []
    sources_used: List[str]    = []

    try:
        # Step 1: Search via VM /search
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/search",
                json={"query": task, "max_results": 5},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                search_data = await resp.json() if resp.status == 200 else {}

        results = search_data.get("results", [])

        if not results:
            # Fall back to local search helper
            results = await search_duckduckgo(task, max_results=5)

        await status.edit_text(
            f"\U0001f916 Нашёл {len(results)} источников, читаю страницы\u2026"
        )

        # Step 2: Fetch text from top pages (15 s per page, skip if too slow)
        async with aiohttp.ClientSession() as session:
            for item in results[:4]:
                url = item.get("url", "")
                if not url or not url.startswith("http"):
                    continue
                sources_used.append(url)
                try:
                    async with session.post(
                        f"{VM_BASE}/browse/page",
                        json={"url": url, "max_chars": 2000},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as page_resp:
                        if page_resp.status == 200:
                            pdata = await page_resp.json()
                            page_text = pdata.get("text", "").strip()
                            if page_text:
                                collected_texts.append(
                                    f"[{item.get('title', url[:60])}]\n{page_text[:1500]}"
                                )
                        else:
                            # Fallback: extract text directly
                            page_text = await extract_page_text(url, max_chars=1500)
                            if page_text:
                                collected_texts.append(
                                    f"[{item.get('title', url[:60])}]\n{page_text}"
                                )
                except Exception as page_exc:
                    logger.debug("agent browse_page failed for %s: %s", url, page_exc)
                    page_text = await extract_page_text(url, max_chars=1500)
                    if page_text:
                        collected_texts.append(
                            f"[{item.get('title', url[:60])}]\n{page_text}"
                        )

        if not collected_texts and results:
            # Use snippets if no full text available
            for item in results:
                snippet = item.get("snippet", "").strip()
                if snippet:
                    collected_texts.append(f"[{item.get('title', '')}]\n{snippet}")

        await status.edit_text("\U0001f916 Анализирую найденную информацию\u2026")

        # Step 3: Synthesise with Ollama
        context = "\n\n---\n\n".join(collected_texts[:6])
        prompt  = (
            f"Задание: {task}\n\n"
            f"Информация из интернета:\n{context[:4000]}\n\n"
            "На основе найденной информации дай подробный, структурированный ответ на задание. "
            "Отвечай на русском языке. Упомяни важные факты и детали."
        )
        answer = await ask_ollama(prompt)

    except Exception as exc:
        logger.error("cmd_agent error: %s", exc)
        try:
            await status.edit_text(f"\u274c Ошибка агента: {str(exc)[:200]}")
        except Exception:
            try:
                await message.answer(f"❌ Ошибка агента: {str(exc)[:200]}")
            except Exception:
                pass
        return

    dur = int((time.monotonic() - t0) * 1000)
    await action_logger.log(
        "agent_browse",
        {"task": task},
        {"sources": len(sources_used), "texts_fetched": len(collected_texts)},
        bool(answer),
        dur,
    )

    try:
        await status.delete()
    except Exception:
        pass  # message may have been deleted already

    # Format response — body MUST be escaped for MarkdownV2
    header   = f"\U0001f916 *Агент: {_esc(task[:100])}*\n\n"
    body_raw = answer or "Не удалось получить ответ от AI."
    body_md  = _esc(body_raw)
    footer   = ""
    if sources_used:
        src_lines = ["\n\n\U0001f517 *Источники:*"]
        for i, u in enumerate(sources_used[:5], 1):
            src_lines.append(f"{i}\\. {_esc(u[:100])}")
        footer = "\n".join(src_lines)

    full_md = header + body_md + footer
    for chunk in _split_text(full_md, 4000):
        try:
            await message.answer(chunk, parse_mode="MarkdownV2")
        except Exception:
            # Strip MarkdownV2 formatting — send clean plain text
            plain = _unescape_md(chunk)
            try:
                await message.answer(plain[:4096])
            except Exception:
                pass


# /update command — show the PowerShell command to download and install new files
# ---------------------------------------------------------------------------


@router.message(Command("update"))
async def cmd_update(message: Message) -> None:
    """Show the PowerShell one-liner to check for updates and install new files."""
    text_md = (
        "\u2b07\ufe0f *Скачать и установить новые файлы*\n\n"
        "Открой *PowerShell* \\(Win\\+X → Windows PowerShell\\) и вставь:\n\n"
        f"{_MD_UPDATE_CMD}\n\n"
        "Команда автоматически:\n"
        "1\\. Проверяет наличие обновлений\n"
        "2\\. Показывает список изменённых файлов\n"
        "3\\. Скачивает и устанавливает новые версии\n\n"
        "После завершения запусти VM:\n"
        f"{_MD_START_CMD}\n\n"
        "_Если папки `drgr\\-bot` нет — используй_ /vm _для полной установки с нуля_"
    )
    try:
        await message.answer(text_md, parse_mode="MarkdownV2")
    except Exception:
        await message.answer(
            "⬇ Скачать и установить новые файлы\n\n"
            "Открой PowerShell (Win+X → Windows PowerShell) и вставь:\n\n"
            f"{_TXT_UPDATE_CMD}\n\n"
            "Команда автоматически:\n"
            "1. Проверяет наличие обновлений\n"
            "2. Показывает список изменённых файлов\n"
            "3. Скачивает и устанавливает новые версии\n\n"
            "После завершения запусти VM:\n"
            f"{_TXT_START_CMD}\n\n"
            "Если папки drgr-bot нет — используй /vm для полной установки с нуля"
        )


# /settoken command — save a new Telegram bot token via VM /settings API
# ---------------------------------------------------------------------------


@router.message(Command("settoken"))
async def cmd_settoken(message: Message) -> None:
    """Save a new Telegram bot token.  Usage: /settoken <token>"""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "ℹ️ Использование: /settoken <токен>\n\n"
            "Пример:\n"
            "/settoken 1234567890:ABCdefGHIjklMNOpqrSTUvwxyz\n\n"
            "Токен можно получить у @BotFather.\n"
            "После сохранения бот автоматически перезапустится с новым токеном."
        )
        return

    new_token = args[1].strip()
    if not re.match(r"^\d{8,}:[A-Za-z0-9_-]{35,}$", new_token):
        await message.answer(
            "❌ Неверный формат токена.\n"
            "Токен должен иметь вид: 1234567890:ABCdefGHIjklMNOpqrSTUvwxyz\n\n"
            "Получи токен у @BotFather командой /newbot или /token."
        )
        return

    saved = False
    # First try via VM /settings API (VM will restart the bot automatically)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/settings",
                json={"bot_token": new_token},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    saved = True
    except Exception as exc:
        logger.warning("cmd_settoken: VM /settings unreachable (%s), falling back to .env write", exc)

    if not saved:
        # Fallback: write directly to .env in repo root
        try:
            env_path = Path(__file__).resolve().parent / ".env"
            lines: list[str] = []
            if env_path.exists():
                lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
            token_found = False
            for i, line in enumerate(lines):
                if line.startswith("BOT_TOKEN="):
                    lines[i] = f"BOT_TOKEN={new_token}\n"
                    token_found = True
                    break
            if not token_found:
                lines.append(f"BOT_TOKEN={new_token}\n")
            env_path.write_text("".join(lines), encoding="utf-8")
            saved = True
        except Exception as exc:
            await message.answer(f"❌ Не удалось сохранить токен: {exc}")
            return

    try:
        await message.answer(
            "✅ *Токен сохранён\\!*\n\n"
            "Бот перезапускается с новым токеном\\.\n"
            "Если бот не отвечает через 10 секунд — запусти заново:\n\n"
            f"{_MD_INSTALL_CMD}\n\n"
            f"{_MD_START_CMD}",
            parse_mode="MarkdownV2",
        )
    except Exception:
        await message.answer(
            "✅ Токен сохранён!\n\n"
            "Бот перезапускается с новым токеном.\n"
            "Если бот не отвечает через 10 секунд — запусти заново:\n\n"
            f"{_TXT_INSTALL_CMD}\n\n"
            f"{_TXT_START_CMD}"
        )


# /vm command — show VM status, URL and PowerShell launch command
# ---------------------------------------------------------------------------


@router.message(Command("vm"))
async def cmd_vm(message: Message) -> None:
    """Show VM status and how to launch it."""
    vm_ok    = False
    ollama_ok = False
    lms_ok   = False
    lms_url  = ""
    lms_cfg  = False
    models: List[str] = []
    lms_models: List[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_BASE}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    hdata       = await resp.json()
                    vm_ok       = hdata.get("vm", {}).get("status") == "ok"
                    ollama_ok   = hdata.get("ollama", {}).get("status") == "ok"
                    models      = hdata.get("ollama", {}).get("models", [])
                    lms_data    = hdata.get("lm_studio", {})
                    lms_ok      = lms_data.get("status") == "ok"
                    lms_cfg     = lms_data.get("status") != "not_configured"
                    lms_url     = lms_data.get("url", "") or ""
                    lms_models  = lms_data.get("models", [])
    except Exception:
        pass

    vm_icon     = "\u2705" if vm_ok     else "\u274c"
    ollama_icon = "\u2705" if ollama_ok else "\u274c"
    lms_icon    = "\u2705" if lms_ok    else ("\u26a0\ufe0f" if lms_cfg else "\u2796")
    all_models  = (models + lms_models)[:5]
    models_str  = ", ".join(all_models) if all_models else "нет"

    lms_status_str = "подключен" if lms_ok else ("недоступен" if lms_cfg else "не настроен")
    lms_url_str    = f" \\(`{_esc(lms_url)}`\\)" if lms_url else ""

    text_md = (
        "\U0001f5a5 *Статус VM*\n\n"
        f"{vm_icon} VM \\(`{_esc(VM_BASE)}`\\): {'работает' if vm_ok else 'не запущена'}\n"
        f"{ollama_icon} Ollama: {'подключена' if ollama_ok else 'не подключена'}\n"
        f"{lms_icon} LM Studio: {_esc(lms_status_str)}{lms_url_str}\n"
        f"\U0001f9e0 Модели: `{_esc(models_str)}`\n\n"
        f"\U0001f680 {_MD_INSTALL_CMD}\n\n"
        f"{_MD_UPDATE_CMD}\n\n"
        f"{_MD_START_CMD}\n\n"
        f"*\U0001f5a5 Адрес VM в браузере:* {_MD_WEB_URL}\n\n"
        "_Или дважды кликни ярлык «Code VM» на Рабочем столе_\n"
        "_Для подключения LM Studio: откройте настройки \\(☰\\) в VM → введите URL LM Studio_"
    )
    try:
        await message.answer(text_md, parse_mode="MarkdownV2")
    except Exception:
        await message.answer(
            f"🖥 Статус VM\n\n"
            f"{vm_icon} VM ({VM_BASE}): {'работает' if vm_ok else 'не запущена'}\n"
            f"{ollama_icon} Ollama: {'подключена' if ollama_ok else 'не подключена'}\n"
            f"{lms_icon} LM Studio: {lms_status_str}{(' (' + lms_url + ')') if lms_url else ''}\n"
            f"🧠 Модели: {models_str}\n\n"
            "🚀 Установка и запуск VM (PowerShell, Win+X → Windows PowerShell):\n"
            f'irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/run.ps1" | iex\n\n'
            "⬇ Обновить (скачать новые файлы):\n"
            f'irm "https://raw.githubusercontent.com/ybiytsa1983-cpu/drgr-bot/main/update.ps1" | iex\n\n'
            "▶ Запуск VM:\n"
            f'powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\\drgr-bot\\start.ps1"\n\n'
            f"🖥 Адрес VM в браузере: {VM_BASE}\n\n"
            "Или дважды кликни ярлык «Code VM» на Рабочем столе\n"
            "Для подключения LM Studio: откройте настройки (☰) в VM → введите URL LM Studio"
        )


# ---------------------------------------------------------------------------
# Photo handler — convert image via VM /convert/image
# Send a photo with a caption like "jpeg", "png", "webp", or "bmp"
# ---------------------------------------------------------------------------

_IMAGE_FMT_ALIASES = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "bmp": "bmp"}


@router.message(F.photo)
async def handle_photo_convert(message: Message) -> None:
    """Analyze photo with AI or convert to another format via VM.

    - Caption contains a format (jpeg/png/webp/bmp) → convert image
    - Any other caption or no caption → analyze photo with AI vision model
    """
    caption = (message.caption or "").strip()
    caption_lower = caption.lower()

    # Look for a target format anywhere in the caption
    target_format = None
    for word in caption_lower.split():
        if word in _IMAGE_FMT_ALIASES:
            target_format = _IMAGE_FMT_ALIASES[word]
            break
    if not target_format:
        for alias, fmt in _IMAGE_FMT_ALIASES.items():
            if alias in caption_lower:
                target_format = fmt
                break

    if not target_format:
        # No format specified — analyze the photo with AI vision model
        # Forward photo notification to VM chat panel
        _push_tg_message_to_vm(
            from_name=(message.from_user.full_name if message.from_user else "TG"),
            text=caption or "(без подписи)",
            chat_title=getattr(message.chat, "title", "") or "",
            has_photo=True,
        )
        status = await message.answer("\U0001f50d Анализирую фото\u2026")
        try:
            photo     = message.photo[-1]  # highest resolution
            file_info = await bot.get_file(photo.file_id)
            buf       = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            img_b64   = base64.b64encode(buf.getvalue()).decode()

            # Build prompt: use caption as user question if provided
            prompt_extra = f" Вопрос пользователя: {caption}" if caption else ""

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{VM_BASE}/agent/describe_image",
                    json={"image_base64": img_b64, "filename": "photo.jpg"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        description = data.get("description", "").strip()
                        model_used  = data.get("model", "")
                        if description:
                            reply = f"\U0001f5bc {description}"
                            await status.delete()
                            # Split long descriptions
                            for chunk in _split_text(reply, 4000):
                                await message.answer(chunk)
                            if model_used:
                                await message.answer(
                                    f"_Модель: {_esc(model_used)}_",
                                    parse_mode="MarkdownV2",
                                )
                            return
                        err = data.get("error", "")
                        if "No vision model" in err:
                            await status.edit_text(
                                "\u26a0\ufe0f Нет vision\\-модели\\. Установите:\n"
                                "`ollama pull llava`\n\n"
                                "Или для конвертации фото отправьте с подписью: `jpeg`, `png`, `webp`, `bmp`",
                                parse_mode="MarkdownV2",
                            )
                            return
                        await status.edit_text(f"\u274c {err[:300] or 'Ошибка анализа фото'}")
                        return
                    await status.edit_text(f"\u274c VM: HTTP {resp.status}")
                    return
        except Exception as exc:
            logger.error("photo_analyze: %s", exc)
        await status.edit_text(
            "\u274c VM недоступна\\. Убедитесь, что VM запущена \\(/vm\\)\\.\n\n"
            "Для конвертации фото отправьте с подписью: `jpeg`, `png`, `webp`, `bmp`\n\n"
            f"_Для обновления файлов используйте_ /update",
            parse_mode="MarkdownV2",
        )
        return

    status = await message.answer(f"\U0001f504 Конвертирую в {target_format.upper()}\u2026")
    try:
        photo     = message.photo[-1]  # highest resolution
        file_info = await bot.get_file(photo.file_id)
        buf       = io.BytesIO()
        await bot.download_file(file_info.file_path, buf)
        img_b64   = base64.b64encode(buf.getvalue()).decode()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/convert/image",
                json={"image_base64": img_b64, "to_format": target_format},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        result_bytes = base64.b64decode(data["result_base64"])
                        ts           = int(time.time())
                        fname        = f"converted_{ts}.{target_format}"
                        out_path     = str(ARTICLES_DIR / fname)
                        async with aiofiles.open(out_path, "wb") as fh:
                            await fh.write(result_bytes)
                        await action_logger.log(
                            "convert_image",
                            {"to_format": target_format},
                            {"size_bytes": data.get("size_bytes", 0),
                             "dimensions": data.get("dimensions", "")},
                            True,
                        )
                        await status.delete()
                        await message.answer_document(
                            FSInputFile(out_path, filename=fname),
                            caption=(
                                f"\u2705 Конвертировано в {target_format.upper()}\n"
                                f"Размер: {data.get('dimensions', '?')}, "
                                f"{data.get('size_bytes', 0) // 1024} КБ"
                            ),
                        )
                        return
                    await status.edit_text(f"\u274c {data.get('error', 'Ошибка конвертации')[:300]}")
                    return
                await status.edit_text(f"\u274c VM: HTTP {resp.status}")
                return
    except Exception as exc:
        logger.error("photo_convert: %s", exc)
    await status.edit_text(
        "\u274c Ошибка конвертации\\. Убедитесь, что VM запущена\\.",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# Document handler — convert text file via VM /convert/text
# Supported: JSON→CSV, CSV→JSON, HTML→text, Markdown→HTML
# ---------------------------------------------------------------------------

_TEXT_CONVERT_DEFAULTS = {
    "json": "csv", "csv": "json", "html": "text", "htm": "text", "md": "html", "markdown": "html"
}


_CODE_EXTS = {"py", "js", "ts", "sh", "bash", "rb", "go", "rs", "cpp", "c", "java", "php", "swift", "kt", "sql"}


@router.message(F.document)
async def handle_document_convert(message: Message) -> None:
    """Handle uploaded documents.

    • Code files (.py, .js, .sh, …) — upload to VM and execute via /execute.
      Caption triggers execution; no caption shows file content in editor.
    • Text format files (JSON, CSV, HTML, Markdown) — convert via /convert/text.
    """
    doc   = message.document
    if not doc:
        return
    fname   = (doc.file_name or "").lower()
    caption = (message.caption or "").strip()
    caption_lower = caption.lower()

    # Detect extension
    ext = fname.rsplit(".", 1)[-1] if "." in fname else ""

    # --- Branch 1: code file upload → execute in VM ---
    if ext in _CODE_EXTS:
        # Limit size to 512 KB
        if doc.file_size and doc.file_size > 524_288:
            await message.answer("\u26a0\ufe0f Файл слишком большой \\(макс 512 КБ\\)\\.", parse_mode="MarkdownV2")
            return

        _ext_lang = {
            "py": "python", "js": "javascript", "ts": "typescript",
            "sh": "shell", "bash": "bash", "rb": "ruby",
            "go": "go", "rs": "rust", "cpp": "cpp", "c": "c",
            "java": "java", "php": "php", "swift": "swift", "kt": "kotlin",
            "sql": "sql",
        }
        lang = _ext_lang.get(ext, ext)

        status = await message.answer(
            f"\u2699\ufe0f Запускаю `{_esc(doc.file_name or fname)}` в VM sandbox\u2026",
            parse_mode="MarkdownV2",
        )
        try:
            file_info = await bot.get_file(doc.file_id)
            buf       = io.BytesIO()
            await bot.download_file(file_info.file_path, buf)
            raw_bytes = buf.getvalue()
            try:
                code = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    code = raw_bytes.decode("cp1251")
                except UnicodeDecodeError:
                    await status.edit_text("\u274c Файл содержит не-текстовые данные \\(не UTF\\-8\\)\\.", parse_mode="MarkdownV2")
                    return

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{VM_BASE}/execute",
                    json={"code": code, "language": lang},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data    = await resp.json()
                        success = data.get("success", False)
                        output  = (data.get("output") or "").strip()
                        error   = (data.get("error") or "").strip()
                        await action_logger.log(
                            "execute_upload",
                            {"filename": doc.file_name, "language": lang},
                            {"success": success, "output": output[:200]},
                            success,
                        )
                        icon = "\u2705" if success else "\u274c"
                        lines = [f"{icon} `{_esc(doc.file_name or fname)}` \\({_esc(lang)}\\)"]
                        if output:
                            lines.append(f"\n\U0001f4e4 *Вывод:*\n```\n{_esc(output[:800])}\n```")
                        if not success and error:
                            lines.append(f"\n\U0001f6a8 *Ошибка:*\n```\n{_esc(error[:600])}\n```")
                        await status.delete()
                        try:
                            await message.answer("\n".join(lines), parse_mode="MarkdownV2")
                        except Exception:
                            await message.answer(f"{icon} {output or error}")
                        return
                    err_text = await resp.text()
                    await status.edit_text(f"\u274c VM {resp.status}: {err_text[:200]}")
        except Exception as exc:
            logger.error("handle_document code exec: %s", exc)
            await status.edit_text(f"\u274c Ошибка: {str(exc)[:200]}")
        return

    # --- Branch 2: text format conversion ---
    from_fmt = ext if ext in _TEXT_CONVERT_DEFAULTS else None
    if not from_fmt:
        return  # Not a file format we handle — silently ignore

    # Detect target format from caption; fall back to default
    to_fmt = None
    valid_targets = {
        "json": {"csv"},
        "csv":  {"json"},
        "html": {"text", "txt"},
        "htm":  {"text", "txt"},
        "md":   {"html"},
        "markdown": {"html"},
    }.get(from_fmt, set())
    for word in caption_lower.split():
        if word in valid_targets or (word == "txt" and "text" in valid_targets):
            to_fmt = "text" if word == "txt" else word
            break
    if not to_fmt:
        to_fmt = _TEXT_CONVERT_DEFAULTS[from_fmt]

    # Map source extension to canonical server format name
    server_from = {"htm": "html", "markdown": "md"}.get(from_fmt, from_fmt)

    # Limit file size to 1 MB
    if doc.file_size and doc.file_size > 1_048_576:
        await message.answer(
            "\u26a0\ufe0f Файл слишком большой \\(макс 1 МБ\\)\\.", parse_mode="MarkdownV2"
        )
        return

    status = await message.answer(
        f"\U0001f504 Конвертирую {from_fmt.upper()} \u2192 {to_fmt.upper()} через VM\u2026"
    )
    try:
        file_info = await bot.get_file(doc.file_id)
        buf       = io.BytesIO()
        await bot.download_file(file_info.file_path, buf)
        content   = buf.getvalue().decode("utf-8", errors="replace")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/convert/text",
                json={"content": content, "from_format": server_from, "to_format": to_fmt},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        result_text = data.get("result", "")
                        ts          = int(time.time())
                        out_ext     = to_fmt if to_fmt != "text" else "txt"
                        out_fname   = f"converted_{ts}.{out_ext}"
                        out_path    = str(ARTICLES_DIR / out_fname)
                        async with aiofiles.open(out_path, "w", encoding="utf-8") as fh:
                            await fh.write(result_text)
                        await action_logger.log(
                            "convert_text",
                            {"from_format": from_fmt, "to_format": to_fmt},
                            {"length": len(result_text)},
                            True,
                        )
                        await status.delete()
                        await message.answer_document(
                            FSInputFile(out_path, filename=out_fname),
                            caption=f"\u2705 {from_fmt.upper()} \u2192 {to_fmt.upper()}",
                        )
                        return
                    await status.edit_text(f"\u274c {data.get('error', 'Ошибка')[:300]}")
                    return
                await status.edit_text(f"\u274c VM: HTTP {resp.status}")
                return
    except Exception as exc:
        logger.error("doc_convert: %s", exc)
    await status.edit_text(
        "\u274c Ошибка конвертации\\. Убедитесь, что VM запущена\\.",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# /agent command — autonomous browser agent (DRGRBrowserAgent)
# ---------------------------------------------------------------------------


@router.message(Command("agent"))
async def cmd_agent(message: Message) -> None:
    """Run the autonomous DRGRBrowserAgent to complete a browser task.

    Usage: /agent <task description>
           /agent <url> <task description>
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🤖 *Автономный браузер\\-агент*\n\n"
            "Использование:\n"
            "`/agent <задание>` — агент сам откроет браузер и выполнит задачу\n\n"
            "Примеры:\n"
            "• `/agent Найди последние новости о Python 3\\.13`\n"
            "• `/agent https://github\\.com Найди самый популярный репозиторий Python`\n\n"
            "Агент делает скриншоты, кликает, заполняет формы и отвечает на задачу\\.\n"
            "Требуется: Ollama \\+ модель qwen3\\-vl:8b или drgr\\-visor",
            parse_mode="MarkdownV2",
        )
        return

    task_text = parts[1].strip()
    start_url = ""
    # If task starts with a URL, extract it
    task_words = task_text.split(maxsplit=1)
    if task_words[0].startswith(("http://", "https://", "www.")):
        start_url = task_words[0]
        if not start_url.startswith("http"):
            start_url = "https://" + start_url
        task_text = task_words[1] if len(task_words) > 1 else task_text

    model = await get_best_model()
    status = await message.answer(
        f"🤖 Запускаю автономный агент\\.\\.\\.\n"
        f"Задание: {_esc(task_text[:100])}\n"
        f"Модель: {_esc(model or 'не найдена')}",
        parse_mode="MarkdownV2",
    )

    log_lines: list = [f"🤖 Агент: {task_text[:200]}"]
    if start_url:
        log_lines.append(f"🌐 Стартовый URL: {start_url}")
    log_lines.append("")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/browse/agent/run",
                json={
                    "task": task_text,
                    "model": model,
                    "max_steps": 10,
                    "start_url": start_url,
                },
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    await status.edit_text(f"❌ VM вернула {resp.status}")
                    return
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except ValueError:
                        continue
                    if obj.get("error"):
                        log_lines.append(f"❌ {obj['error'][:200]}")
                        break
                    cycle     = obj.get("cycle", "?")
                    url_now   = obj.get("url", "")
                    status_v  = obj.get("status", "running")
                    thoughts  = obj.get("thoughts", {})
                    plan      = (thoughts.get("plan_short") or "")[:100]
                    results   = obj.get("results", [])
                    log_lines.append(f"⚙ Цикл {cycle}: {url_now[:60]}")
                    if plan:
                        log_lines.append(f"  → {plan}")
                    for r in results:
                        ok_mark = "✓" if r.get("ok") else "✗"
                        log_lines.append(f"  {ok_mark} {r.get('type','')}: {(r.get('info') or '')[:60]}")
                    if status_v.startswith("finished_"):
                        log_lines.append(f"\n🏁 {status_v}")
                        break
                    # Update status message every 3 cycles
                    if isinstance(cycle, int) and cycle % 3 == 0:
                        try:
                            await status.edit_text(
                                "\n".join(log_lines[-20:])[:4000],
                                parse_mode=None,
                            )
                        except Exception:
                            pass
    except Exception as exc:
        logger.error("cmd_agent: %s", exc)
        log_lines.append(f"❌ Ошибка: {str(exc)[:200]}")

    await action_logger.log(
        "browser_agent",
        {"task": task_text[:200], "start_url": start_url},
        {"cycles": len(log_lines), "success": any("finished_success" in ln for ln in log_lines)},
        any("finished_success" in ln for ln in log_lines),
    )

    final = "\n".join(log_lines)[:4000]
    try:
        await status.edit_text(final, parse_mode=None)
    except Exception:
        await message.answer(final[:4096], parse_mode=None)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    query = (message.text or "").strip()
    if len(query) < 3:
        await message.answer(
            "Запрос слишком короткий\\. Напишите что хотите найти\\.",
            parse_mode="MarkdownV2",
        )
        return
    user_id = message.from_user.id if message.from_user else 0

    # Forward the incoming TG message to the VM chat panel (fire-and-forget)
    _push_tg_message_to_vm(
        from_name=(message.from_user.full_name if message.from_user else "TG"),
        text=query,
        chat_title=getattr(message.chat, "title", "") or "",
    )

    # Smart routing: if message contains a URL, treat it as a ВИЗОР/browse request
    url_match = _URL_IN_TEXT_RE.search(query)
    if url_match:
        url = _clean_url(url_match.group(0))
        status = await message.answer(
            f"🖥 ВИЗОР анализирует `{url[:80]}`\\.\\.\\.",
            parse_mode="MarkdownV2",
        )
        t0 = time.monotonic()
        try:
            async with aiohttp.ClientSession() as _sess:
                async with _sess.post(
                    f"{VM_BASE}/browse/screenshot",
                    json={"url": url},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    data = await resp.json() if resp.status == 200 else {}
        except Exception as exc:
            await status.edit_text(f"❌ Ошибка: {str(exc)[:200]}")
            return
        dur = int((time.monotonic() - t0) * 1000)
        screenshot_b64 = data.get("screenshot_base64", "")
        description    = data.get("description", "")
        model_used     = data.get("model", "")
        await status.delete()
        if screenshot_b64:
            img_bytes = base64.b64decode(screenshot_b64)
            ts = int(time.time())
            shot_path = str(SCREENSHOTS_DIR / f"visor_{ts}.png")
            with open(shot_path, "wb") as fh:
                fh.write(img_bytes)
            caption = f"🖥 *ВИЗОР* — {_esc(url[:60])}\n\n{_esc(description[:900])}"
            if model_used:
                caption += f"\n\n_Модель: {_esc(model_used)}_"
            caption += f"\n⏱ {dur} мс"
            try:
                await message.answer_photo(
                    FSInputFile(shot_path),
                    caption=caption[:1024],
                    parse_mode="MarkdownV2",
                )
            except Exception:
                await message.answer(caption[:4096], parse_mode=None)
        else:
            await message.answer(
                (description or "❌ Не удалось получить скриншот")[:4096]
            )
        return

    q_lower = query.lower()

    # Smart routing: general PowerShell/install question → show all commands via /vm
    _PS_CMD_KEYWORDS = (
        "команда для повершел", "команда для повершелл",
        "команда powershell", "powershell команда",
        "где команда", "пауэршелл", "повершелл",
        "как установить", "установка vm", "установить vm",
        "run.ps1", "start.ps1",
        "lm studio", "lm-studio", "лм студио", "подключить лм", "подключить vm",
        "подключение vm", "подключение вм", "статус vm", "статус вм",
    )
    if any(kw in q_lower for kw in _PS_CMD_KEYWORDS):
        await cmd_vm(message)
        return

    # Smart routing: detect update intent → show update command
    _UPDATE_KEYWORDS = (
        "обновл", "скачать файл", "скачать обновл", "установить обновл",
        "новые файл", "команда для скачивания", "команда для обновл",
        "update.ps1", "как обновить",
        "апгрейд", "апдейт", "upgrade", "запуска апгрейд", "запустить апгрейд",
        "скачивания", "скачать и запустить", "скачать и запуск",
    )
    if any(kw in q_lower for kw in _UPDATE_KEYWORDS):
        await cmd_update(message)
        return

    # Smart routing: detect clear search intent keywords → use research_and_reply
    if any(kw in q_lower for kw in _SEARCH_KEYWORDS_RU):
        await research_and_reply(query, message)
        return

    # Default: conversational VM chat with per-user history.
    # Falls back to full web research if VM is unreachable or returns nothing.
    try:
        if not await chat_via_vm(user_id, query, message):
            await research_and_reply(query, message)
    except Exception as exc:
        logger.error("handle_text error: %s", exc)
        try:
            await message.answer(
                "⚠ Произошла ошибка при обработке запроса\\. "
                "Убедитесь, что VM и Ollama запущены \\(см\\. /vm\\)\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass


# ===========================================================================
# ENTRY POINT
# ===========================================================================

async def main() -> None:
    logger.info(
        "AI Research Agent starting. Playwright=%s, DDG=%s, VM=%s",
        PLAYWRIGHT_AVAILABLE,
        DDG_AVAILABLE,
        VM_BASE,
    )
    # Register bot commands so Telegram shows them in the menu
    await bot.set_my_commands([
        BotCommand(command="agent",      description="🤖 Автономный браузер-агент (Playwright + vision)"),
        BotCommand(command="research",   description="🔎 Текстовый веб-агент: ищет и читает страницы"),
        BotCommand(command="search",     description="Исследовать тему (статья + скриншоты)"),
        BotCommand(command="browse",     description="Скриншот страницы + AI анализ"),
        BotCommand(command="visor",      description="ВИЗОР: скриншот + AI анализ страницы"),
        BotCommand(command="code",       description="Написать и выполнить код (авто-исправление)"),
        BotCommand(command="execute",    description="Выполнить код в VM sandbox"),
        BotCommand(command="download",   description="📥 Скачать файл по URL через VM"),
        BotCommand(command="generate",   description="Сгенерировать HTML-страницу"),
        BotCommand(command="screenshot", description="Быстрый скриншот страницы"),
        BotCommand(command="convert",    description="Конвертер файлов (фото, json, csv, md)"),
        BotCommand(command="retrain",    description="Запустить цикл самообучения VM"),
        BotCommand(command="vm",         description="Статус VM и команды запуска"),
        BotCommand(command="update",     description="⬇ Скачать и установить новые файлы"),
        BotCommand(command="models",     description="Доступные AI-модели"),
        BotCommand(command="stats",      description="Статистика самообучения"),
        BotCommand(command="help",       description="Все команды и справка"),
        BotCommand(command="web",        description="🌐 Открыть веб-интерфейс Code VM (localhost:5000)"),
    ])
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
