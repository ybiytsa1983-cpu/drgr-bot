"""
OpenClaw Telegram Bot.

Commands:
  /start              - welcome + menu
  /search <query>     - search WB products with unit econ
  /top                - top-10 products from DB
  /calc <price> <cost>- unit economics calculator
  /category <name>    - search by category
  /report             - daily summary report
  /settings           - view/update unit econ settings
  /ask <question>     - ask AI assistant
  /help               - full help

Voice messages are transcribed (ffmpeg/Whisper) and processed as text.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

import httpx
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

from workers.analytics import (
    UnitEconSettings,
    calculate_unit_econ,
    format_unit_econ_message,
    score_product,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_URL = os.getenv("API_URL", "http://localhost:8000")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required. Add it to .env")

logger = logging.getLogger("openclaw.bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

_HTTP_TIMEOUT = httpx.Timeout(30.0, read=60.0)


# ---------------------------------------------------------------------------
# FSM States
# ---------------------------------------------------------------------------

class SettingsStates(StatesGroup):
    waiting_for_field = State()
    waiting_for_value = State()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def _api(
    method: str,
    path: str,
    json: Optional[Dict] = None,
    params: Optional[Dict] = None,
) -> Optional[Dict[str, Any]]:
    url = f"{API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await getattr(client, method)(url, json=json, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        logger.warning(f"API not reachable at {API_URL}")
        return None
    except Exception as exc:
        logger.error(f"API {method.upper()} {path} error: {exc}")
        return None


async def _ensure_user(tg_user: types.User) -> None:
    await _api(
        "post",
        "/users/upsert",
        json={
            "tg_id": tg_user.id,
            "username": tg_user.username,
            "full_name": tg_user.full_name,
        },
    )


# ---------------------------------------------------------------------------
# Transcription (voice -> text)
# ---------------------------------------------------------------------------

async def _transcribe_voice(file_bytes: bytes) -> Optional[str]:
    """
    Convert OGG voice to text using ffmpeg + whisper.cpp or return None.
    Falls back gracefully if whisper is not available.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(file_bytes)
            ogg_path = f.name

        wav_path = ogg_path.replace(".ogg", ".wav")
        subprocess.run(
            ["ffmpeg", "-i", ogg_path, "-ar", "16000", "-ac", "1", wav_path, "-y", "-loglevel", "quiet"],
            check=True,
            timeout=30,
        )

        # Try whisper.cpp if available
        whisper_bin = os.getenv("WHISPER_BIN", "")
        whisper_model = os.getenv("WHISPER_MODEL", "models/ggml-base.bin")
        if whisper_bin and os.path.exists(whisper_bin):
            result = subprocess.run(
                [whisper_bin, "-m", whisper_model, "-f", wav_path, "--output-txt", "-l", "ru"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            txt_path = wav_path + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                os.unlink(txt_path)
                return text

        # Clean up
        for p in [ogg_path, wav_path]:
            try:
                os.unlink(p)
            except OSError:
                pass
        return None
    except Exception as exc:
        logger.error(f"Transcription error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_product_short(p: Dict[str, Any], rank: int = 0) -> str:
    prefix = f"{rank}. " if rank else ""
    score_bar = "⭐" * min(5, int((p.get("ai_score") or 0) / 2))
    lines = [
        f"{prefix}<b>{(p.get('name') or '')[:60]}</b> {score_bar}",
        f"   💰 <code>{p.get('price_sale_rub', 0):.0f} ₽</code>",
    ]
    if p.get("margin_pct") is not None:
        lines.append(f"   📊 Маржа: <code>{p['margin_pct']:.1f}%</code>  ROI: <code>{p.get('roi_pct', 0):.1f}%</code>")
    if p.get("sales_30d") is not None:
        lines.append(f"   📦 Продажи/30д: <code>{p['sales_30d']}</code>")
    if p.get("rating"):
        lines.append(f"   ⭐ Рейтинг: <code>{p['rating']}</code>  ({p.get('reviews_count', 0)} отзывов)")
    return "\n".join(lines)


def _split_message(text: str, max_len: int = 4000) -> List[str]:
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        parts.append(text[:max_len])
        text = text[max_len:]
    return parts


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await _ensure_user(message.from_user)
    await message.answer(
        "👋 <b>OpenClaw — AI-подбор товаров для WB</b>\n\n"
        "Я помогу найти перспективные товары на Wildberries, "
        "рассчитать юнит-экономику и дать AI-рекомендацию.\n\n"
        "📌 <b>Команды:</b>\n"
        "/search <i>товар</i> — поиск товара\n"
        "/top — топ-10 перспективных товаров\n"
        "/calc <i>цена себестоимость</i> — калькулятор\n"
        "/category <i>категория</i> — анализ категории\n"
        "/ask <i>вопрос</i> — спросить AI\n"
        "/report — дневной отчёт\n"
        "/settings — настройки\n"
        "/help — справка\n\n"
        "🎤 Голосовые сообщения тоже принимаются!"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📖 <b>Справка OpenClaw</b>\n\n"
        "<b>/search маска для лица</b>\n"
        "→ Найдёт товары на WB, рассчитает маржу и даст AI-оценку.\n\n"
        "<b>/calc 1500 400</b>\n"
        "→ Рассчитает юнит-экономику: цена 1500₽, себестоимость 400₽.\n\n"
        "<b>/top</b>\n"
        "→ Топ-10 товаров с наибольшим AI-скором в базе.\n\n"
        "<b>/category электроника</b>\n"
        "→ Анализ категории: лучшие товары, средняя маржа.\n\n"
        "<b>/ask Какие ниши сейчас в тренде?</b>\n"
        "→ Свободный вопрос к AI-агенту OpenClaw.\n\n"
        "<b>/settings</b>\n"
        "→ Изменить ставку комиссии WB, логистику и т.д.\n\n"
        "<b>/report</b>\n"
        "→ Сводный отчёт по базе данных."
    )


@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Использование: <code>/search название товара</code>\n"
            "Пример: <code>/search маска для лица корейская</code>"
        )
        return
    query = args[1].strip()
    await _do_search(message, query)


async def _do_search(message: types.Message, query: str):
    status = await message.answer(f"🔍 Ищу «{query}» на WB…")
    data = await _api("post", "/products/search", json={"query": query, "limit": 20})
    await status.delete()

    if not data or not data.get("products"):
        await message.answer(f"❌ Ничего не найдено по запросу «{query}». Попробуйте другой запрос.")
        return

    products = data["products"][:5]
    lines = [f"🛒 <b>Результаты по «{query}»</b> ({data['total']} найдено):\n"]
    for i, p in enumerate(products, 1):
        lines.append(_fmt_product_short(p, rank=i))
        lines.append("")

    # AI recommendation
    ai_data = await _api(
        "post",
        "/ai/recommend",
        json={"query": query, "products": data["products"][:10], "top_n": 3},
    )
    if ai_data and ai_data.get("recommendation"):
        lines.append("🧠 <b>AI-рекомендация:</b>")
        lines.append(ai_data["recommendation"])

    full_text = "\n".join(lines)
    for chunk in _split_message(full_text):
        await message.answer(chunk, disable_web_page_preview=True)


@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    status = await message.answer("📊 Загружаю топ товаров…")
    data = await _api("get", "/products/top", params={"limit": 10})
    await status.delete()

    if not data or not data.get("products"):
        await message.answer(
            "База данных пуста.\n"
            "Воспользуйтесь командой /search чтобы загрузить товары."
        )
        return

    lines = ["🏆 <b>Топ-10 перспективных товаров:</b>\n"]
    for i, p in enumerate(data["products"], 1):
        lines.append(_fmt_product_short(p, rank=i))
        lines.append("")

    for chunk in _split_message("\n".join(lines)):
        await message.answer(chunk)


@dp.message(Command("calc"))
async def cmd_calc(message: types.Message):
    """
    /calc <sale_price> <unit_cost> [monthly_fixed_costs]
    Example: /calc 1500 400
    """
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "Использование: <code>/calc цена_продажи себестоимость [фикс_затраты]</code>\n"
            "Пример: <code>/calc 1500 400</code>\n"
            "или: <code>/calc 1500 400 30000</code> (с фикс. затратами 30 000 ₽/мес)"
        )
        return
    try:
        sale_price = float(args[1])
        unit_cost = float(args[2])
        fixed = float(args[3]) if len(args) > 3 else 0.0
    except ValueError:
        await message.answer("❌ Неверный формат. Используйте числа: <code>/calc 1500 400</code>")
        return

    data = await _api(
        "post",
        "/products/calc",
        json={
            "sale_price_rub": sale_price,
            "unit_cost_rub": unit_cost,
            "monthly_fixed_costs_rub": fixed,
        },
    )
    if data:
        await message.answer(data["message"])
    else:
        # Local fallback
        result = calculate_unit_econ(sale_price, unit_cost, fixed)
        await message.answer(format_unit_econ_message(result))


@dp.message(Command("category"))
async def cmd_category(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/category электроника</code>")
        return
    await _do_search(message, args[1].strip())


@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Использование: <code>/ask ваш вопрос</code>")
        return
    question = args[1].strip()
    status = await message.answer("🤔 Думаю…")
    data = await _api("post", "/ai/question", json={"question": question})
    await status.delete()
    if data and data.get("answer"):
        await message.answer(f"🧠 {data['answer']}")
    else:
        await message.answer("AI временно недоступен. Попробуйте позже.")


@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    status = await message.answer("📈 Формирую отчёт…")
    data = await _api("get", "/dashboard/stats")
    await status.delete()

    if not data:
        await message.answer("❌ Не удалось получить данные. Убедитесь, что API запущен.")
        return

    top_lines = ""
    for i, p in enumerate(data.get("top_products", [])[:3], 1):
        top_lines += (
            f"  {i}. {p['name'][:40]} — "
            f"маржа {p.get('margin_pct', 0):.1f}%, "
            f"AI⭐{p.get('ai_score', 0):.1f}\n"
        )

    cat_lines = "\n".join(
        f"  • {c['name']}: {c['count']} товаров"
        for c in data.get("categories", [])[:5]
    )

    await message.answer(
        f"📊 <b>Отчёт OpenClaw</b>\n\n"
        f"Товаров в базе: <b>{data['total_products']}</b>\n"
        f"Средняя маржа: <b>{data['avg_margin_pct']:.1f}%</b>\n"
        f"Средний ROI: <b>{data['avg_roi_pct']:.1f}%</b>\n\n"
        f"<b>Топ-3 товара:</b>\n{top_lines}\n"
        f"<b>Топ категории:</b>\n{cat_lines}\n\n"
        f"🌐 Dashboard: http://localhost:8080"
    )


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    tg_id = message.from_user.id
    data = await _api("get", f"/users/{tg_id}/settings")
    if not data:
        await _ensure_user(message.from_user)
        await message.answer(
            "⚙️ <b>Настройки по умолчанию:</b>\n"
            "Комиссия WB: 15%\nЛогистика: 150₽\nХранение: 15%\nВозвраты: 10%\n\n"
            "Для изменения: <code>/set commission 20</code>"
        )
        return
    await message.answer(
        f"⚙️ <b>Ваши настройки:</b>\n\n"
        f"Комиссия WB: <code>{data['wb_commission_pct']}%</code>\n"
        f"Логистика: <code>{data['logistics_rub']} ₽</code>\n"
        f"Хранение: <code>{data['storage_rate'] * 100:.0f}%</code>\n"
        f"Возвраты: <code>{data['return_rate'] * 100:.0f}%</code>\n\n"
        "Изменить: <code>/set commission 20</code>, "
        "<code>/set logistics 200</code>"
    )


@dp.message(Command("set"))
async def cmd_set(message: types.Message):
    """
    /set commission 20
    /set logistics 200
    /set storage 10
    /set returns 8
    """
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: <code>/set commission 20</code>")
        return
    field, value_str = args[1].lower(), args[2]
    try:
        value = float(value_str)
    except ValueError:
        await message.answer("❌ Значение должно быть числом")
        return

    mapping = {
        "commission": "wb_commission_pct",
        "logistics": "logistics_rub",
        "storage": "storage_rate",
        "returns": "return_rate",
    }
    api_field = mapping.get(field)
    if not api_field:
        await message.answer(
            f"❌ Неизвестное поле. Доступны: {', '.join(mapping.keys())}"
        )
        return

    # storage and returns are fractions
    if field in ("storage", "returns") and value > 1:
        value = value / 100

    await _ensure_user(message.from_user)
    result = await _api(
        "post",
        f"/users/{message.from_user.id}/settings",
        json={api_field: value},
    )
    if result:
        await message.answer(f"✅ Настройка <b>{field}</b> обновлена: <code>{value_str}</code>")
    else:
        await message.answer("❌ Не удалось сохранить настройки. Попробуйте позже.")


# ---------------------------------------------------------------------------
# Voice message handler
# ---------------------------------------------------------------------------

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    status = await message.answer("🎤 Обрабатываю голосовое сообщение…")
    try:
        file_info = await bot.get_file(message.voice.file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        text = await _transcribe_voice(file_bytes.read())
    except Exception as exc:
        logger.error(f"Voice download error: {exc}")
        text = None

    await status.delete()

    if not text:
        await message.answer(
            "🎤 Получил голосовое сообщение!\n"
            "Whisper не установлен — транскрипция недоступна.\n\n"
            "Отправьте запрос текстом: <code>/search маска для лица</code>"
        )
        return

    # Treat transcribed text as a search query
    await message.answer(f"🎤 Распознано: «{text}»")
    await _do_search(message, text)


# ---------------------------------------------------------------------------
# Free text fallback
# ---------------------------------------------------------------------------

@dp.message(F.text)
async def handle_text(message: types.Message):
    text = message.text.strip()
    if not text or text.startswith("/"):
        return
    # Treat as search query
    await _do_search(message, text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    logger.info("Starting OpenClaw bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
