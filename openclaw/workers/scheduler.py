"""
Background scheduler — runs periodic scraping jobs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from workers.wb_scraper import search_and_parse

logger = logging.getLogger("openclaw.scheduler")

SCRAPER_INTERVAL_HOURS = int(os.getenv("SCRAPER_INTERVAL_HOURS", 6))
SCRAPER_CATEGORIES = [
    c.strip()
    for c in os.getenv(
        "SCRAPER_CATEGORIES",
        "одежда,электроника,косметика,товары для дома,спорт,детские товары",
    ).split(",")
    if c.strip()
]
MAX_PRODUCTS_PER_CATEGORY = int(os.getenv("MAX_PRODUCTS_PER_CATEGORY", 100))

# Will be injected from api/main.py or worker entrypoint
_db_save_callback = None


def set_db_save_callback(callback):
    """Register async callback(products: list) to persist scraped products."""
    global _db_save_callback
    _db_save_callback = callback


async def _scrape_category(category: str) -> None:
    logger.info(f"Scraping category: {category}")
    try:
        products = await search_and_parse(category, limit=MAX_PRODUCTS_PER_CATEGORY)
        logger.info(f"Category '{category}': {len(products)} products scraped")
        if _db_save_callback and products:
            await _db_save_callback(products, category=category)
    except Exception as exc:
        logger.error(f"Scraper error for '{category}': {exc}")


async def run_full_scrape() -> None:
    """Scrape all configured categories concurrently."""
    logger.info(f"Starting full scrape: {len(SCRAPER_CATEGORIES)} categories")
    tasks = [_scrape_category(cat) for cat in SCRAPER_CATEGORIES]
    await asyncio.gather(*tasks)
    logger.info("Full scrape finished")


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        run_full_scrape,
        trigger=IntervalTrigger(hours=SCRAPER_INTERVAL_HOURS),
        id="full_scrape",
        name="Full WB scrape",
        replace_existing=True,
        next_run_time=datetime.now(),  # run immediately on start
    )
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.get_event_loop()
    scheduler = create_scheduler()
    scheduler.start()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
