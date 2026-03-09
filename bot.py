"""
AI Research Agent — Telegram bot that autonomously searches the web,
takes screenshots, analyzes content with Ollama AI, and replies with
full articles (text + screenshots + HTML + sources).
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

# Optional: Playwright for browser automation
try:
    from playwright.async_api import async_playwright
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Optional: DuckDuckGo search
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

OLLAMA_BASE = os.getenv("OLLAMA_HOST", "http://localhost:11434")
VM_BASE = os.getenv("VM_BASE", "http://localhost:8000")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
MAX_SCREENSHOTS = int(os.getenv("MAX_SCREENSHOTS", "2"))

SCREENSHOTS_DIR = Path(os.getenv("SCREENSHOTS_DIR", "screenshots"))
ARTICLES_DIR = Path(os.getenv("ARTICLES_DIR", "articles"))
LOG_FILE = os.getenv("LOG_FILE", "bot.log")

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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

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


async def ask_ollama(prompt: str, model: str | None = None) -> str:
    """Generate text with Ollama.  Returns empty string on failure."""
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
                text = await resp.text()
                logger.error("Ollama %s: %s", resp.status, text[:200])
    except Exception as exc:
        logger.error("ask_ollama failed: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# Web search helpers
# ---------------------------------------------------------------------------

async def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search DuckDuckGo and return list of {title, href, body} dicts."""
    if not DDG_AVAILABLE:
        return []
    try:
        results: List[Dict[str, str]] = []

        def _sync_search() -> List[Dict[str, str]]:
            with DDGS() as ddgs:
                return [
                    {"title": r.get("title", ""), "href": r.get("href", ""), "body": r.get("body", "")}
                    for r in ddgs.text(query, max_results=max_results)
                ]

        results = await asyncio.to_thread(_sync_search)
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search error: %s", exc)
        return []


async def search_wikipedia(query: str) -> Dict[str, str]:
    """Fetch Wikipedia summary for *query*."""
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "title": f"Wikipedia: {data.get('title', query)}",
                        "href": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "body": data.get("extract", ""),
                    }
    except Exception as exc:
        logger.warning("Wikipedia search error: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# Browser automation (Playwright)
# ---------------------------------------------------------------------------

async def take_screenshot(url: str, output_path: str) -> bool:
    """Capture a 1280×800 screenshot of *url* and save to *output_path*."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                await page.wait_for_timeout(800)
                await page.screenshot(path=output_path, full_page=False)
                return True
            except PlaywrightTimeout:
                logger.warning("Screenshot timeout: %s", url)
                return False
            finally:
                await browser.close()
    except Exception as exc:
        logger.error("take_screenshot(%s): %s", url, exc)
        return False


async def extract_page_text(url: str, max_chars: int = 3000) -> str:
    """Extract visible text from *url* using Playwright."""
    if not PLAYWRIGHT_AVAILABLE:
        return ""
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                text: str = await page.evaluate(
                    """() => {
                        document.querySelectorAll('script,style,nav,footer,header,aside').forEach(e => e.remove());
                        return (document.body || {}).innerText || '';
                    }"""
                )
                return text[:max_chars]
            except Exception:
                return ""
            finally:
                await browser.close()
    except Exception as exc:
        logger.error("extract_page_text(%s): %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# HTML article generator
# ---------------------------------------------------------------------------

def _screenshot_to_data_uri(path: str) -> str:
    with open(path, "rb") as fh:
        return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def build_html_article(
    title: str,
    body: str,
    sources: List[Dict[str, str]],
    screenshot_paths: List[str],
) -> str:
    """Return a self-contained HTML article string."""
    screenshots_html = ""
    for i, path in enumerate(screenshot_paths[:3]):
        if os.path.exists(path):
            uri = _screenshot_to_data_uri(path)
            screenshots_html += (
                f'<figure class="ss">'
                f'<img src="{uri}" alt="Скриншот {i + 1}"/>'
                f'<figcaption>Рисунок {i + 1}</figcaption>'
                f"</figure>\n"
            )

    sources_items = "".join(
        f'<li><a href="{s.get("href", "#")}" target="_blank">{s.get("title", f"Источник {i + 1}")}</a></li>\n'
        for i, s in enumerate(sources)
    )

    body_html = re.sub(r"\n{2,}", "</p><p>", body.strip())
    body_html = body_html.replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{font-family:Georgia,serif;max-width:860px;margin:0 auto;padding:24px;background:#f4f4f4;color:#222}}
  h1{{color:#1a1a2e;border-bottom:3px solid #e94560;padding-bottom:8px}}
  h2{{color:#16213e;margin-top:28px}}
  article{{background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.12)}}
  figure.ss{{margin:24px 0;text-align:center}}
  figure.ss img{{max-width:100%;border:1px solid #ddd;border-radius:6px;box-shadow:0 3px 8px rgba(0,0,0,.15)}}
  figcaption{{color:#666;font-style:italic;font-size:.88em;margin-top:6px}}
  .sources{{background:#f9f9f9;border-left:4px solid #e94560;padding:16px 20px;margin-top:32px;border-radius:0 6px 6px 0}}
  .sources h3{{color:#e94560;margin-top:0}}
  .sources a{{color:#0f3460;word-break:break-all}}
  p{{line-height:1.7}}
</style>
</head>
<body>
<article>
<h1>{title}</h1>
{screenshots_html}
<div class="content"><p>{body_html}</p></div>
<div class="sources">
<h3>📚 Источники</h3>
<ol>{sources_items}</ol>
</div>
</article>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Core research pipeline
# ---------------------------------------------------------------------------

async def research_and_reply(query: str, message: Message) -> None:
    """
    Full pipeline:
      1. Search DuckDuckGo + Wikipedia
      2. Take screenshots of top pages
      3. Ask Ollama to write an article
      4. Reply with text chunks, screenshots, HTML file, and source list
    """
    status = await message.answer("🔍 Ищу информацию…")

    # ── 1. Gather sources ────────────────────────────────────────────────────
    ddg_results = await search_duckduckgo(query, max_results=MAX_SEARCH_RESULTS)
    wiki_result = await search_wikipedia(query)

    all_sources: List[Dict[str, str]] = []
    if wiki_result.get("body"):
        all_sources.append(wiki_result)
    all_sources.extend(ddg_results)

    if not all_sources:
        await status.edit_text("❌ Ничего не найдено. Попробуйте другой запрос.")
        return

    await status.edit_text(f"📖 Найдено {len(all_sources)} источников. Делаю скриншоты…")

    # ── 2. Screenshots ────────────────────────────────────────────────────────
    screenshot_paths: List[str] = []
    for src in all_sources[:MAX_SCREENSHOTS + 1]:
        url = src.get("href", "")
        if not url.startswith("http"):
            continue
        slug = hashlib.md5(url.encode()).hexdigest()[:8]
        out = str(SCREENSHOTS_DIR / f"ss_{slug}_{int(time.time())}.png")
        ok = await take_screenshot(url, out)
        if ok:
            screenshot_paths.append(out)
        if len(screenshot_paths) >= MAX_SCREENSHOTS:
            break

    # ── 3. Aggregate content ─────────────────────────────────────────────────
    content_blocks: List[str] = []
    for src in all_sources[:6]:
        snippet = src.get("body", "")[:600]
        if snippet:
            content_blocks.append(f"[{src['title']}]: {snippet}")
    aggregated = "\n\n".join(content_blocks)

    await status.edit_text("🤖 Генерирую статью…")

    # ── 4. Ask Ollama ─────────────────────────────────────────────────────────
    models = await get_ollama_models()
    model = models[0] if models else OLLAMA_MODEL

    prompt = (
        f'Ты — экспертный AI-журналист. Напиши полноценную статью на русском языке по теме: "{query}".\n\n'
        f"Данные из источников:\n{aggregated}\n\n"
        "Требования:\n"
        "1. Дай заголовок статьи (первая строка).\n"
        "2. Введение (2–3 предложения).\n"
        "3. Несколько разделов с подзаголовками.\n"
        "4. Выдели редкую и малоизвестную информацию по теме.\n"
        "5. Заключение.\n"
        "Пиши связно и информативно."
    )
    article_text = await ask_ollama(prompt, model)

    if not article_text:
        article_text = f"**{query}**\n\n" + aggregated

    # ── 5. Build HTML ─────────────────────────────────────────────────────────
    lines = article_text.strip().splitlines()
    title = lines[0].lstrip("#").strip() if lines else query
    html = build_html_article(title, article_text, all_sources, screenshot_paths)

    ts = int(time.time())
    article_path = str(ARTICLES_DIR / f"article_{ts}.html")
    async with aiofiles.open(article_path, "w", encoding="utf-8") as fh:
        await fh.write(html)

    # ── 6. Send to Telegram ───────────────────────────────────────────────────
    await status.delete()

    # Article text (split into ≤4096-char chunks)
    header = f"📰 *{_esc(title)}*\n\n"
    chunks = _split_text(article_text, 4000)
    first = True
    for chunk in chunks[:4]:
        if not chunk.strip():
            continue
        prefix = header if first else ""
        first = False
        try:
            await message.answer(prefix + _esc(chunk), parse_mode="MarkdownV2")
        except Exception:
            await message.answer((prefix + chunk)[:4096])

    # Screenshots
    for i, path in enumerate(screenshot_paths):
        if os.path.exists(path):
            try:
                await message.answer_photo(
                    FSInputFile(path),
                    caption=f"📸 Скриншот {i + 1} — {all_sources[i].get('title', '')[:60]}",
                )
            except Exception as exc:
                logger.warning("Could not send screenshot: %s", exc)

    # Sources
    src_lines = ["📚 *Источники:*"]
    for i, src in enumerate(all_sources[:10], 1):
        href = src.get("href", "#") or "#"
        ttl = src.get("title", f"Источник {i}")
        src_lines.append(f"{i}\\. [{_esc(ttl)}]({href})")
    try:
        await message.answer(
            "\n".join(src_lines),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
    except Exception:
        plain = "📚 Источники:\n" + "\n".join(
            f"{i}. {s.get('title','')} — {s.get('href','')}"
            for i, s in enumerate(all_sources[:10], 1)
        )
        await message.answer(plain[:4096])

    # HTML file
    try:
        await message.answer_document(
            FSInputFile(article_path, filename="article.html"),
            caption="📄 Полная HTML-версия статьи",
        )
    except Exception as exc:
        logger.warning("Could not send HTML file: %s", exc)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

_ESC_CHARS = r"\_*[]()~`>#+-=|{}.!"


def _esc(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    return re.sub(r"([" + re.escape(_ESC_CHARS) + r"])", r"\\\1", text)


def _split_text(text: str, max_len: int) -> List[str]:
    """Split *text* into chunks of at most *max_len* characters on newlines."""
    chunks: List[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > max_len:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "🤖 *AI Research Agent*\n\n"
        "Я автономный агент для исследования тем\\.\n\n"
        "Просто *напишите запрос*, и я:\n"
        "🔍 Найду информацию из нескольких источников\n"
        "📸 Сделаю скриншоты страниц\n"
        "🤖 Сгенерирую статью с помощью локального ИИ\n"
        "📰 Пришлю текст, скриншоты и HTML\\-версию\n"
        "📚 Укажу все источники\n\n"
        "Команды:\n"
        "/search \\<запрос\\> — исследовать тему\n"
        "/screenshot \\<url\\> — скриншот страницы\n"
        "/generate \\<описание\\> — HTML\\-страница через VM\n"
        "/models — доступные AI модели\n"
        "/help — помощь",
        parse_mode="MarkdownV2",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 *Помощь*\n\n"
        "Отправьте любой текст — агент проведёт исследование и создаст статью\\.\n\n"
        "Команды:\n"
        "• `/search <тема>` — полное исследование\n"
        "• `/screenshot <url>` — скриншот страницы\n"
        "• `/generate <описание>` — создать HTML\\-страницу\n"
        "• `/models` — список AI\\-моделей Ollama\n\n"
        "Пример: `/search квантовые компьютеры`",
        parse_mode="MarkdownV2",
    )


@router.message(Command("models"))
async def cmd_models(message: Message) -> None:
    models = await get_ollama_models()
    if models:
        lines = ["🤖 *Доступные модели Ollama:*"] + [f"• {_esc(m)}" for m in models]
        await message.answer("\n".join(lines), parse_mode="MarkdownV2")
    else:
        await message.answer(
            "⚠️ Ollama не запущена или нет доступных моделей\\.\n"
            "Запустите: `ollama pull llama2`",
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
        await message.answer("⚠️ Playwright не установлен\\. Запустите `playwright install chromium`\\.", parse_mode="MarkdownV2")
        return
    status = await message.answer(f"📸 Делаю скриншот…")
    out = str(SCREENSHOTS_DIR / f"manual_{int(time.time())}.png")
    ok = await take_screenshot(url, out)
    await status.delete()
    if ok and os.path.exists(out):
        await message.answer_photo(FSInputFile(out), caption=f"🌐 {url[:200]}")
    else:
        await message.answer("❌ Не удалось сделать скриншот\\. Проверьте URL\\.", parse_mode="MarkdownV2")


@router.message(Command("generate"))
async def cmd_generate(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/generate <описание>`", parse_mode="MarkdownV2")
        return
    prompt = parts[1].strip()
    status = await message.answer("🔨 Генерирую HTML\\-страницу…", parse_mode="MarkdownV2")
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
                        await message.answer_document(
                            FSInputFile(path, filename="generated.html"),
                            caption=f"📄 HTML по запросу: {prompt[:100]}",
                        )
                        return
    except Exception as exc:
        logger.error("generate failed: %s", exc)
    await status.edit_text("❌ Ошибка генерации\\. Убедитесь, что VM запущена\\.", parse_mode="MarkdownV2")


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
        await message.answer("Запрос слишком короткий\\. Напишите что хотите найти\\.", parse_mode="MarkdownV2")
        return
    await research_and_reply(query, message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info(
        "AI Research Agent starting. Playwright=%s, DDG=%s",
        PLAYWRIGHT_AVAILABLE,
        DDG_AVAILABLE,
    )
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())


# ---------------------------------------------------------------------------
# LEGACY stub — kept so old imports don't break; not used by the agent
# ---------------------------------------------------------------------------

def apply_effect(image: Any, effect: str) -> Any:  # noqa: F821
    """Stub for legacy callers."""
    raise NotImplementedError("apply_effect is not used in the AI Research Agent.")


def is_valid_file_size(file_size: int) -> bool:
    """Stub for legacy callers."""
    raise NotImplementedError
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
