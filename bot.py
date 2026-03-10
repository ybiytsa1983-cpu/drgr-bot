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
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Set BOT_TOKEN in your .env file.")

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


# ===========================================================================
# PER-USER CHAT HISTORY  (used by chat_via_vm)
# ===========================================================================

_chat_history: Dict[int, List[Dict[str, str]]] = {}  # user_id -> [{role, text}, ...]
_MAX_CHAT_TURNS = 20  # keep last N turns in context (mirrors _MAX_CHAT_HISTORY_TURNS in server.py)


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
        "Ты работаешь через расширение Code VM которое даёт тебе доступ к браузеру, "
        "Monaco редактору, ВИЗОРУ и HTML-генератору.\n\n"
        "Твои возможности:\n"
        "• 🖥 ВИЗОР — браузер-инспектор со скриншотами и AI-анализом — /visor <url> или /browse <url>\n"
        "• 🧑‍💻 Генерация и выполнение кода (Python, JS, HTML) — /execute, /code\n"
        "• 🌐 HTML-генератор Monaco — создание полных страниц — /generate <описание>\n"
        "• 🔍 Поиск в интернете и написание статей — /search <тема>\n"
        "• 📂 Конвертация файлов (изображения, JSON, CSV, Markdown) — /convert\n"
        "• 🧠 Управление моделями Ollama (pull, delete, retrain)\n"
        "• 🔄 Самообучение VM на основе накопленного опыта — /retrain\n"
        "• 📸 Скриншот + qwen3-vl анализ страницы — /browse <url>\n\n"
        "ВАЖНО: Ты ПОДКЛЮЧЁН к расширению Code VM. Ты МОЖЕШЬ:\n"
        "1. Делать скриншоты ЛЮБЫХ веб-страниц через /browse\n"
        "2. Анализировать страницы с помощью qwen3-vl:8b (vision model)\n"
        "3. Запускать код прямо в VM sandbox\n"
        "4. Генерировать HTML и сразу видеть его в ВИЗОРЕ\n"
        "Когда пользователь просит что-то — ДЕЛАЙ это немедленно, не объясняй как это сделать.\n"
        "Отвечай на русском языке, кратко и по делу.\n\n"
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
    """Search DuckDuckGo; log action to VM."""
    if not DDG_AVAILABLE:
        return []
    t0 = time.monotonic()
    try:
        def _sync() -> List[Dict[str, str]]:
            with DDGS() as ddgs:
                return [
                    {"title": r.get("title",""), "href": r.get("href",""), "body": r.get("body","")}
                    for r in ddgs.text(query, max_results=max_results)
                ]
        results = await asyncio.to_thread(_sync)
        await action_logger.log_search(f"ddg:{query}", results, int((time.monotonic()-t0)*1000))
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo: %s", exc)
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


# ===========================================================================
# PLAYWRIGHT BROWSER
# ===========================================================================

async def take_screenshot(url: str, output_path: str) -> bool:
    """Capture a 1280x800 viewport screenshot; log action to VM."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    t0 = time.monotonic()
    success = False
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
        logger.error("take_screenshot(%s): %s", url, exc)
    dur = int((time.monotonic() - t0) * 1000)
    await action_logger.log_screenshot(url, output_path, success, dur)
    return success


async def extract_page_text(url: str, max_chars: int = 3000) -> str:
    """Extract visible text from a page using Playwright."""
    if not PLAYWRIGHT_AVAILABLE:
        return ""
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
                return text[:max_chars]
            except Exception:
                return ""
            finally:
                await browser.close()
    except Exception as exc:
        logger.error("extract_page_text(%s): %s", url, exc)
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


def build_html_article(
    title: str,
    body: str,
    sources: List[Dict[str, str]],
    screenshot_paths: List[str],
    image_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """Return a self-contained HTML article with embedded screenshots and AI captions."""
    import html as _html  # stdlib html.escape
    image_descriptions = image_descriptions or {}

    screenshots_html = ""
    for i, path in enumerate(screenshot_paths[:3]):
        if not os.path.exists(path):
            continue
        uri  = _to_data_uri(path)
        desc = image_descriptions.get(path, "")
        cap  = _html.escape(desc[:120] if desc else f"Рисунок {i + 1}")
        screenshots_html += (
            '<figure class="ss">'
            f'<img src="{uri}" alt="{cap}"/>'
            f"<figcaption>{cap}</figcaption>"
            "</figure>\n"
        )

    sources_items = "".join(
        f'<li><a href="{_safe_href(s.get("href",""))}" target="_blank" rel="noopener noreferrer">'
        f'{_html.escape(s.get("title", f"Источник {i+1}"))}</a></li>\n'
        for i, s in enumerate(sources)
    )

    body_html = re.sub(r"\n{2,}", "</p><p>", _html.escape(body.strip()))
    body_html = body_html.replace("\n", "<br>")

    css = (
        "body{font-family:Georgia,serif;max-width:860px;margin:0 auto;padding:24px;"
        "background:#f4f4f4;color:#222}"
        "h1{color:#1a1a2e;border-bottom:3px solid #e94560;padding-bottom:8px}"
        "h2{color:#16213e;margin-top:28px}"
        "article{background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12)}"
        "figure.ss{margin:24px 0;text-align:center}"
        "figure.ss img{max-width:100%;border:1px solid #ddd;border-radius:6px;"
        "box-shadow:0 3px 8px rgba(0,0,0,.15)}"
        "figcaption{color:#555;font-style:italic;font-size:.88em;margin-top:6px}"
        ".sources{background:#f9f9f9;border-left:4px solid #e94560;padding:16px 20px;"
        "margin-top:32px;border-radius:0 6px 6px 0}"
        ".sources h3{color:#e94560;margin-top:0}"
        ".sources a{color:#0f3460;word-break:break-all}"
        "p{line-height:1.7}"
        "blockquote{border-left:3px solid #e94560;margin:10px 0;padding-left:15px;"
        "color:#555;font-style:italic}"
    )

    return (
        '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>{css}</style>\n"
        f"</head>\n<body>\n<article>\n<h1>{title}</h1>\n"
        f"{screenshots_html}"
        f'<div class="content"><p>{body_html}</p></div>\n'
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
      1. Search DuckDuckGo + Wikipedia (parallel)
      2. Take screenshots of top pages
      3. Describe screenshots with Ollama vision (background)
      4. Generate article with Ollama text model
      5. Reply: text + screenshots + HTML + sources
      6. All actions logged to VM for self-improvement
    """
    t0     = time.monotonic()
    status = await message.answer("\U0001f50d Ищу информацию\u2026")

    # 1. Search (parallel)
    ddg_task  = asyncio.create_task(search_duckduckgo(query, MAX_SEARCH_RESULTS))
    wiki_task = asyncio.create_task(search_wikipedia(query))
    ddg_results, wiki_result = await asyncio.gather(ddg_task, wiki_task)

    all_sources: List[Dict[str, str]] = []
    if wiki_result.get("body"):
        all_sources.append(wiki_result)
    all_sources.extend(ddg_results)

    if not all_sources:
        await status.edit_text("\u274c Ничего не найдено. Попробуйте другой запрос.")
        await action_logger.log(
            "research", {"query": query}, {"error": "no sources"}, False,
            int((time.monotonic() - t0) * 1000),
        )
        return

    await status.edit_text(
        f"\U0001f4d6 Найдено {len(all_sources)} источников. Делаю скриншоты\u2026"
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

    # 3. Aggregate text for AI
    blocks = [
        f"[{s['title']}]: {s.get('body','')[:600]}"
        for s in all_sources[:6]
        if s.get("body")
    ]
    aggregated = "\n\n".join(blocks)

    await status.edit_text("\U0001f916 Генерирую статью\u2026")

    # 4. Ollama article
    model  = await get_best_model()

    prompt = (
        f'Ты — экспертный AI-журналист. Напиши полноценную статью на русском языке по теме: "{query}".\n\n'
        f"Данные из источников:\n{aggregated}\n\n"
        "Требования:\n"
        "1. Дай заголовок статьи (первая строка, без # или *).\n"
        "2. Введение (2-3 предложения).\n"
        "3. Несколько разделов с подзаголовками.\n"
        "4. Выдели редкую и малоизвестную информацию по теме.\n"
        "5. Заключение.\n"
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
    await status.delete()

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
            await message.answer((prefix + chunk)[:4096])

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
        "*Команды:*\n"
        "/search `<запрос>` — исследовать тему, статья \\+ скриншоты\n"
        "/visor `<url>` — 🖥 ВИЗОР: скриншот \\+ AI анализ \\(qwen3\\-vl\\)\n"
        "/browse `<url>` — скриншот страницы \\+ AI анализ \\(qwen3\\-vl\\)\n"
        "/code `[python|js|html|...]` `<задача>` — написать, запустить, исправить\n"
        "/execute `<код>` — выполнить код в VM sandbox\n"
        "/generate `<описание>` — HTML\\-страница \\(скачать файл\\)\n"
        "/screenshot `<url>` — быстрый скриншот страницы\n"
        "/convert — форматы конвертера; отправьте фото или файл \\(json/csv/md/html\\) для конвертации\n"
        "/retrain — запустить цикл самообучения VM\n"
        "/vm — статус VM, URL и команда запуска\n"
        "/models — доступные AI\\-модели\n"
        "/stats — статистика самообучения\n"
        "/help — помощь\n\n"
        "*Или просто напишите запрос* — агент исследует тему и создаст статью\\.\n\n"
        "\U0001f4bb *Запуск VM \\(PowerShell\\):*\n"
        "`irm \"https://raw.githubusercontent.com/ybiytsa1983\\-cpu/drgr\\-bot/main/run\\.ps1\" | iex`\n\n"
        "\U0001f5a5 После установки: ярлык *«Code VM»* и *«ЗАПУСТИТЬ ВМ»* на Рабочем столе",
        parse_mode="MarkdownV2",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "\U0001f4d6 *Помощь — все команды*\n\n"
        "*Исследование и браузер:*\n"
        "• `/search <тема>` — полное исследование, статья \\+ скриншоты \\+ HTML\n"
        "• `/visor <url>` — 🖥 ВИЗОР: скриншот \\+ AI анализ \\(qwen3\\-vl:8b\\)\n"
        "• `/visor watch <url>` — слежение за изменениями на странице \\(3 снимка\\)\n"
        "• `/browse <url>` — скриншот страницы \\+ AI анализ \\(qwen3\\-vl:8b\\)\n"
        "• `/screenshot <url>` — быстрый скриншот с описанием\n\n"
        "*Генерация и выполнение кода:*\n"
        "• `/code <задача>` — написать код, запустить, исправить ошибки, прислать файл\n"
        "• `/code python|js|html|go|... <задача>` — выбрать язык\n"
        "• `/execute <код>` — выполнить код в VM sandbox\n"
        "• `/generate <описание>` — HTML\\-страница \\(файл `.html`\\)\n\n"
        "*VM и самообучение:*\n"
        "• `/models` — список AI\\-моделей \\(включая drgr\\-visor\\)\n"
        "• `/stats` — что VM узнала из своих действий\n"
        "• `/retrain` — запустить цикл самообучения VM вручную\n"
        "• `/vm` — статус VM и команды запуска\n\n"
        "*Конвертер файлов \\(через VM\\):*\n"
        "• `/convert` — список всех доступных конвертаций\n"
        "• Отправьте фото с подписью `jpeg`, `png`, `webp` или `bmp` — конвертация изображения\n"
        "• Отправьте файл `.json`, `.csv`, `.html` или `.md` — конвертация текстового формата\n\n"
        "*Установка VM \\(один раз\\):*\n"
        "`irm \"https://raw.githubusercontent.com/ybiytsa1983\\-cpu/drgr\\-bot/main/run\\.ps1\" | iex`\n\n"
        "Пример: `/visor watch https://news.ycombinator.com`",
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
            "\u26a0\ufe0f Ollama не запущена или нет доступных моделей\\.\n"
            "Запустите: `ollama pull llama2`",
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
    if not PLAYWRIGHT_AVAILABLE:
        await message.answer(
            "\u26a0\ufe0f Playwright не установлен\\. Запустите `playwright install chromium`\\.",
            parse_mode="MarkdownV2",
        )
        return
    status = await message.answer("\U0001f4f8 Делаю скриншот\u2026")
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
    prefix = "⚠ Скриншот недоступен (установите Playwright: `playwright install chromium`).\n\n" if text_fb else "\u274c "
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
            "\u274c VM не вернула HTML\\. Убедитесь, что VM и Ollama запущены\\.",
            parse_mode="MarkdownV2",
        )
    except Exception as exc:
        logger.error("generate failed: %s", exc)
        await action_logger.log(
            "generate_html", {"prompt": prompt}, {"error": str(exc)}, False
        )
        await status.edit_text(
            "\u274c Ошибка генерации\\. Убедитесь, что VM запущена\\.",
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
# /vm command — show VM status, URL and PowerShell launch command
# ---------------------------------------------------------------------------


@router.message(Command("vm"))
async def cmd_vm(message: Message) -> None:
    """Show VM status and how to launch it."""
    vm_ok    = False
    ollama_ok = False
    models: List[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{VM_BASE}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    hdata     = await resp.json()
                    vm_ok     = hdata.get("vm", {}).get("status") == "ok"
                    ollama_ok = hdata.get("ollama", {}).get("status") == "ok"
                    models    = hdata.get("ollama", {}).get("models", [])
    except Exception:
        pass

    vm_icon     = "\u2705" if vm_ok     else "\u274c"
    ollama_icon = "\u2705" if ollama_ok else "\u274c"
    models_str  = ", ".join(models[:5]) if models else "нет"

    await message.answer(
        "\U0001f5a5 *Статус VM*\n\n"
        f"{vm_icon} VM \\(`{_esc(VM_BASE)}`\\): {'работает' if vm_ok else 'не запущена'}\n"
        f"{ollama_icon} Ollama: {'подключена' if ollama_ok else 'не подключена'}\n"
        f"\U0001f9e0 Модели: `{_esc(models_str)}`\n\n"
        "*\U0001f680 Установка \\(один раз\\):*\n"
        "`irm \"https://raw.githubusercontent.com/ybiytsa1983\\-cpu/drgr\\-bot/main/run\\.ps1\" | iex`\n\n"
        "*\u25b6\ufe0f Запуск VM:*\n"
        "`powershell \\-ExecutionPolicy Bypass \\-File \"$env:USERPROFILE\\\\drgr\\-bot\\\\start\\.ps1\"`\n\n"
        "*\U0001f5a5 Адрес VM в браузере:*\n"
        "`http://localhost:5000/`\n\n"
        "_Или дважды кликни ярлык «Code VM» на Рабочем столе_",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# Photo handler — convert image via VM /convert/image
# Send a photo with a caption like "jpeg", "png", "webp", or "bmp"
# ---------------------------------------------------------------------------

_IMAGE_FMT_ALIASES = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "bmp": "bmp"}


@router.message(F.photo)
async def handle_photo_convert(message: Message) -> None:
    """Convert a received photo to another image format via VM /convert/image."""
    caption = (message.caption or "").strip().lower()

    # Look for a target format anywhere in the caption
    target_format = None
    for word in caption.split():
        if word in _IMAGE_FMT_ALIASES:
            target_format = _IMAGE_FMT_ALIASES[word]
            break
    if not target_format:
        for alias, fmt in _IMAGE_FMT_ALIASES.items():
            if alias in caption:
                target_format = fmt
                break

    if not target_format:
        await message.answer(
            "\U0001f5bc *Конвертация фото через VM*\n\n"
            "Отправьте фото с подписью нужного формата:\n"
            "\u2022 `jpeg` — JPEG \\(меньше размер\\)\n"
            "\u2022 `png` — PNG \\(без потерь\\)\n"
            "\u2022 `webp` — WebP \\(современный\\)\n"
            "\u2022 `bmp` — BMP\n\n"
            "Пример подписи: `webp` или `jpeg`",
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


@router.message(F.document)
async def handle_document_convert(message: Message) -> None:
    """Convert a text document (JSON/CSV/HTML/Markdown) via VM /convert/text."""
    doc   = message.document
    if not doc:
        return
    fname   = (doc.file_name or "").lower()
    caption = (message.caption or "").strip().lower()

    # Detect source format from file extension
    ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
    from_fmt = ext if ext in _TEXT_CONVERT_DEFAULTS else None
    if not from_fmt:
        return  # Not a text format we handle — silently ignore

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
    for word in caption.split():
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
    # Try VM chat/stream first (conversational AI with per-user history).
    # Falls back to full web research if VM is unreachable or returns nothing.
    if not await chat_via_vm(user_id, query, message):
        await research_and_reply(query, message)


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
        BotCommand(command="search",     description="Исследовать тему (статья + скриншоты)"),
        BotCommand(command="generate",   description="Сгенерировать HTML-страницу"),
        BotCommand(command="visor",      description="ВИЗОР: скриншот + AI анализ страницы"),
        BotCommand(command="browse",     description="Скриншот страницы + AI анализ"),
        BotCommand(command="code",       description="Написать и выполнить код"),
        BotCommand(command="execute",    description="Выполнить код в VM sandbox"),
        BotCommand(command="screenshot", description="Быстрый скриншот страницы"),
        BotCommand(command="convert",    description="Конвертер файлов (фото, json, csv, md)"),
        BotCommand(command="vm",         description="Статус VM и команды запуска"),
        BotCommand(command="models",     description="Доступные AI-модели"),
        BotCommand(command="retrain",    description="Запустить цикл самообучения VM"),
        BotCommand(command="stats",      description="Статистика самообучения"),
        BotCommand(command="help",       description="Все команды и справка"),
    ])
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
