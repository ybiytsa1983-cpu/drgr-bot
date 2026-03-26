"""
OpenClaw AI Agent — product recommendation and analysis.

Supports:
  - Ollama (local LLM)
  - OpenAI-compatible API (GPT-4o, etc.)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("openclaw.ai_agent")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "llama3")

_TIMEOUT = httpx.Timeout(60.0, read=120.0)

_SYSTEM_PROMPT = """
Ты — AI-помощник OpenClaw для подбора перспективных товаров на маркетплейсах (Wildberries).
Твоя задача:
1. Анализировать данные о товарах (продажи, маржа, конкуренция, тренды).
2. Давать конкретные рекомендации: стоит ли заходить с этим товаром.
3. Предлагать ценовые стратегии и ниши с низкой конкуренцией.
4. Отвечать кратко и по делу (не более 3-5 предложений), на русском языке.

При анализе учитывай:
- Маржинальность > 20% — хороший показатель
- ROI > 50% — хороший показатель
- Продажи > 100 шт/30 дней — стабильный спрос
- Конкурентов < 200 — нише есть место
"""


async def _ollama_chat(messages: List[Dict[str, str]], model: str) -> str:
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()


async def _openai_chat(messages: List[Dict[str, str]], model: str) -> str:
    url = f"{OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


async def _chat(messages: List[Dict[str, str]]) -> str:
    """Route to appropriate backend."""
    if OPENAI_API_KEY:
        return await _openai_chat(messages, AI_MODEL)
    return await _ollama_chat(messages, AI_MODEL)


async def analyse_product(product: Dict[str, Any]) -> str:
    """
    Ask AI to analyse a single product and give a verdict.
    product should have: name, price_sale_rub, margin_pct, roi_pct,
    sales_30d, rating, reviews_count, competitors_count.
    """
    context = (
        f"Товар: {product.get('name', 'N/A')}\n"
        f"Цена: {product.get('price_sale_rub', 0):.0f} ₽\n"
        f"Маржа: {product.get('margin_pct', 0):.1f}%\n"
        f"ROI: {product.get('roi_pct', 0):.1f}%\n"
        f"Продажи за 30 дней: {product.get('sales_30d', 'нет данных')}\n"
        f"Рейтинг: {product.get('rating', 'нет данных')}\n"
        f"Отзывов: {product.get('reviews_count', 0)}\n"
        f"Конкурентов: {product.get('competitors_count', 'нет данных')}\n"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Оцени перспективность этого товара для выхода на WB:\n\n{context}",
        },
    ]
    try:
        return await _chat(messages)
    except Exception as exc:
        logger.error(f"AI analyse_product error: {exc}")
        return _local_verdict(product)


async def recommend_products(
    query: str,
    products: List[Dict[str, Any]],
    top_n: int = 5,
) -> str:
    """
    Ask AI to pick the top *top_n* products from a list and explain why.
    """
    products_text = "\n".join(
        f"{i+1}. {p.get('name','')} | "
        f"цена {p.get('price_sale_rub',0):.0f}₽ | "
        f"маржа {p.get('margin_pct',0):.1f}% | "
        f"ROI {p.get('roi_pct',0):.1f}% | "
        f"продажи/мес {p.get('sales_30d','?')} | "
        f"рейтинг {p.get('rating','?')}"
        for i, p in enumerate(products[:20])
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Пользователь ищет: «{query}»\n\n"
                f"Вот список товаров:\n{products_text}\n\n"
                f"Выбери топ-{top_n} наиболее перспективных и объясни выбор кратко."
            ),
        },
    ]
    try:
        return await _chat(messages)
    except Exception as exc:
        logger.error(f"AI recommend_products error: {exc}")
        return _local_top(products, top_n)


async def answer_question(question: str) -> str:
    """Answer a free-form question about marketplace analytics."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    try:
        return await _chat(messages)
    except Exception as exc:
        logger.error(f"AI answer_question error: {exc}")
        return (
            "AI-агент временно недоступен. "
            "Проверьте, запущен ли Ollama (docker compose up ollama), "
            "или укажите OPENAI_API_KEY в .env."
        )


def _local_verdict(product: Dict[str, Any]) -> str:
    """Fallback verdict without AI."""
    margin = product.get("margin_pct", 0) or 0
    roi = product.get("roi_pct", 0) or 0
    if margin >= 20 and roi >= 50:
        verdict = "✅ Товар перспективный: хорошая маржа и ROI."
    elif margin >= 10:
        verdict = "⚠️ Средняя перспективность: маржа низкая, стоит снизить себестоимость."
    else:
        verdict = "❌ Нецелесообразно: маржа отрицательная или слишком низкая."
    return verdict + " (AI offline — локальный анализ)"


def _local_top(products: List[Dict[str, Any]], top_n: int) -> str:
    """Fallback top-N without AI."""
    scored = sorted(
        products,
        key=lambda p: (p.get("margin_pct") or 0) + (p.get("roi_pct") or 0) / 2,
        reverse=True,
    )[:top_n]
    lines = [f"🏆 Топ-{top_n} по маржинальности + ROI (AI offline):"]
    for i, p in enumerate(scored, 1):
        lines.append(
            f"{i}. {p.get('name','')[:50]} — "
            f"маржа {p.get('margin_pct',0):.1f}%, ROI {p.get('roi_pct',0):.1f}%"
        )
    return "\n".join(lines)
