"""
Wildberries scraper.
Collects product data from WB search API and statistics API.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("openclaw.wb_scraper")

WB_SEARCH_URL = os.getenv("WB_SEARCH_URL", "https://search.wb.ru")
WB_API_URL = os.getenv("WB_API_URL", "https://suppliers-api.wildberries.ru")
WB_STATS_URL = os.getenv("WB_STATS_URL", "https://statistics-api.wildberries.ru")
WB_API_KEY = os.getenv("WB_API_KEY", "")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_TIMEOUT = httpx.Timeout(20.0, read=30.0)


def _auth_headers() -> Dict[str, str]:
    h = dict(_HEADERS)
    if WB_API_KEY:
        h["Authorization"] = WB_API_KEY
    return h


async def search_products(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Search WB catalog for products matching *query*.
    Returns a list of raw product dicts.
    """
    params = {
        "query": query,
        "resultset": "catalog",
        "limit": min(limit, 100),
        "sort": "popular",
        "page": 1,
        "appType": 1,
        "curr": "rub",
        "dest": -1257786,
    }
    url = f"{WB_SEARCH_URL}/catalog/0/search.aspx"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            products = data.get("data", {}).get("products", [])
            logger.info(f"WB search '{query}': {len(products)} results")
            return products
    except Exception as exc:
        logger.error(f"WB search error for '{query}': {exc}")
        return []


async def get_product_stats(wb_sku: int) -> Optional[Dict[str, Any]]:
    """
    Fetch extended sales stats for a single WB SKU (requires WB_API_KEY).
    Returns None if unavailable.
    """
    if not WB_API_KEY:
        return None
    url = f"{WB_STATS_URL}/api/v1/supplier/sales"
    params = {"dateFrom": "2024-01-01", "flag": 1}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=_auth_headers())
            resp.raise_for_status()
            rows = resp.json()
            # Filter rows for this SKU
            sku_rows = [r for r in rows if r.get("nmId") == wb_sku]
            if not sku_rows:
                return None
            total_sales = sum(r.get("quantity", 0) for r in sku_rows)
            total_revenue = sum(r.get("finishedPrice", 0) for r in sku_rows)
            return {"sales_total": total_sales, "revenue_total": total_revenue}
    except Exception as exc:
        logger.error(f"WB stats error for SKU {wb_sku}: {exc}")
        return None


def parse_product(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise a raw WB product dict into our standard schema.
    """
    price_raw = raw.get("priceU", 0) or 0
    sale_price_raw = raw.get("salePriceU", price_raw) or price_raw
    price_rub = price_raw / 100
    sale_price_rub = sale_price_raw / 100
    discount_pct = raw.get("sale", 0) or 0

    return {
        "wb_sku": raw.get("id"),
        "name": raw.get("name", ""),
        "brand": raw.get("brand", ""),
        "seller": raw.get("supplier", ""),
        "price_rub": price_rub,
        "price_sale_rub": sale_price_rub,
        "discount_pct": float(discount_pct),
        "rating": raw.get("rating", 0),
        "reviews_count": raw.get("feedbacks", 0),
        "in_stock": raw.get("volume", 0) > 0,
        "sales_30d": raw.get("sells", {}).get("by30Days", None),
    }


async def search_and_parse(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Convenience wrapper: search + parse."""
    raw_products = await search_products(query, limit=limit)
    return [parse_product(p) for p in raw_products]
