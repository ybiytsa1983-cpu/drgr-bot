"""
AI Research Agent — Telegram bot that autonomously searches the web,
takes screenshots, analyzes content with Ollama AI, replies with full
articles (text + screenshots + HTML + sources), and logs every action
to the VM self-learning store so the VM can constantly improve itself.
"""

import asyncio
import base64
import hashlib
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
from aiogram.types import FSInputFile, Message

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
# OLLAMA HELPERS
# ===========================================================================

async def get_ollama_models() -> List[str]:
    """Return list of locally available Ollama model names."""
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


async def ask_ollama(prompt: str, model: Optional[str] = None) -> str:
    """Generate text with Ollama. Returns empty string on failure."""
    model = model or OLLAMA_MODEL
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
    Result is logged to the VM for self-improvement training.
    """
    if not os.path.exists(image_path):
        return ""
    t0 = time.monotonic()
    description = ""

    # 1. Try VM dedicated endpoint (auto-selects best vision model)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/agent/describe_image",
                json={"image_path": os.path.abspath(image_path)},
                timeout=aiohttp.ClientTimeout(total=60),
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
            vis_model = model or "llava"
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
                    timeout=aiohttp.ClientTimeout(total=60),
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
    models = await get_ollama_models()
    model  = models[0] if models else OLLAMA_MODEL

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
        "\U0001f916 *AI Research Agent*\n\n"
        "Я автономный агент для исследования тем\\.\n\n"
        "Просто *напишите запрос*, и я:\n"
        "\U0001f50d Найду информацию из нескольких источников\n"
        "\U0001f4f8 Сделаю скриншоты и опишу картинки через ИИ\n"
        "\U0001f916 Напишу статью с помощью локального ИИ\n"
        "\U0001f4f0 Пришлю текст, скриншоты и HTML\\-версию\n"
        "\U0001f4da Укажу все источники\n"
        "\U0001f9e0 Сохраню всё в базу знаний VM для обучения\n\n"
        "Команды:\n"
        "/search \\<запрос\\> — исследовать тему\n"
        "/screenshot \\<url\\> — скриншот страницы\n"
        "/generate \\<описание\\> — HTML\\-страница\n"
        "/models — доступные AI модели\n"
        "/stats — статистика самообучения VM\n"
        "/help — помощь",
        parse_mode="MarkdownV2",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "\U0001f4d6 *Помощь*\n\n"
        "Отправьте любой текст — агент исследует тему и создаст статью\\.\n\n"
        "• `/search <тема>` — полное исследование\n"
        "• `/screenshot <url>` — скриншот страницы\n"
        "• `/generate <описание>` — создать HTML\\-страницу\n"
        "• `/models` — список AI\\-моделей Ollama\n"
        "• `/stats` — что VM узнала из своих действий\n\n"
        "Пример: `/search квантовые компьютеры`",
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


@router.message(Command("generate"))
async def cmd_generate(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/generate <описание>`", parse_mode="MarkdownV2")
        return
    prompt = parts[1].strip()
    status = await message.answer(
        "\U0001f528 Генерирую HTML\\-страницу\u2026", parse_mode="MarkdownV2"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{VM_BASE}/generate/html",
                json={"prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    html = data.get("html", "")
                    if html:
                        path = str(ARTICLES_DIR / f"gen_{int(time.time())}.html")
                        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
                            await fh.write(html)
                        await status.delete()
                        await action_logger.log(
                            "generate_html",
                            {"prompt": prompt},
                            {"path": path, "length": len(html)},
                            True,
                        )
                        await message.answer_document(
                            FSInputFile(path, filename="generated.html"),
                            caption=f"\U0001f4c4 HTML по запросу: {prompt[:100]}",
                        )
                        return
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


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    query = (message.text or "").strip()
    if len(query) < 3:
        await message.answer(
            "Запрос слишком короткий\\. Напишите что хотите найти\\.",
            parse_mode="MarkdownV2",
        )
        return
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
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
