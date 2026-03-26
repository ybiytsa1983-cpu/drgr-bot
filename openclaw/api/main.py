"""
OpenClaw FastAPI backend.

Endpoints:
  GET  /health
  POST /products/search      - search WB + calculate unit econ + score
  GET  /products/top         - top-N scored products from DB
  POST /products/calc        - calculate unit economics for a product
  GET  /products/{id}        - get single product
  GET  /categories           - list categories
  POST /ai/recommend         - AI recommendation for a query
  POST /ai/analyse           - AI analysis for a single product
  GET  /dashboard/stats      - aggregated stats for the dashboard
  POST /users/upsert         - create or update TG user
  GET  /users/{tg_id}/settings - get user settings
  POST /users/{tg_id}/settings - update user settings
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Path setup so shared modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.models import (
    Base,
    Category,
    Product,
    ProductStatus,
    ScraperTask,
    TelegramUser,
    UserRequest,
)
from workers.analytics import (
    UnitEconSettings,
    calculate_unit_econ,
    format_unit_econ_message,
    score_product,
)
from workers.wb_scraper import search_and_parse
from ai_agent.agent import analyse_product, recommend_products, answer_question

logger = logging.getLogger("openclaw.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://openclaw:openclaw_secret@localhost:5432/openclaw",
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="OpenClaw API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ProductSearchRequest(BaseModel):
    query: str
    limit: int = 30
    unit_cost_rub: Optional[float] = None
    wb_commission_pct: Optional[float] = None
    logistics_rub: Optional[float] = None


class CalcRequest(BaseModel):
    sale_price_rub: float
    unit_cost_rub: float
    monthly_fixed_costs_rub: float = 0.0
    wb_commission_pct: float = 15.0
    logistics_rub: float = 150.0
    storage_rate: float = 0.15
    return_rate: float = 0.10
    product_name: str = ""


class AIRecommendRequest(BaseModel):
    query: str
    products: List[Dict[str, Any]] = []
    top_n: int = 5


class AIAnalyseRequest(BaseModel):
    product: Dict[str, Any]


class AIQuestionRequest(BaseModel):
    question: str


class UserUpsertRequest(BaseModel):
    tg_id: int
    username: Optional[str] = None
    full_name: Optional[str] = None


class UserSettingsUpdate(BaseModel):
    wb_commission_pct: Optional[float] = None
    logistics_rub: Optional[float] = None
    storage_rate: Optional[float] = None
    return_rate: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_category(db: AsyncSession, name: str) -> Category:
    result = await db.execute(select(Category).where(Category.name == name))
    cat = result.scalar_one_or_none()
    if cat is None:
        cat = Category(name=name)
        db.add(cat)
        await db.flush()
    return cat


async def _save_products(
    db: AsyncSession,
    products: List[Dict[str, Any]],
    category_name: str = "",
    settings: Optional[UnitEconSettings] = None,
) -> List[Product]:
    if settings is None:
        settings = UnitEconSettings()
    saved = []
    cat_id = None
    if category_name:
        cat = await _get_or_create_category(db, category_name)
        cat_id = cat.id

    for p_data in products:
        wb_sku = p_data.get("wb_sku")
        # Try to find existing product
        existing = None
        if wb_sku:
            result = await db.execute(
                select(Product).where(Product.wb_sku == wb_sku)
            )
            existing = result.scalar_one_or_none()

        sale_price = p_data.get("price_sale_rub") or p_data.get("price_rub") or 0.0
        # Unit econ (use mid-price as rough cost if not provided)
        unit_cost = p_data.get("unit_cost_rub") or (sale_price * 0.4)
        margin = roi = ai_score = None
        if sale_price > 0 and unit_cost > 0:
            ue = calculate_unit_econ(sale_price, unit_cost, settings=settings)
            margin = ue.margin_pct
            roi = ue.roi_pct
            ai_score = score_product(
                price_rub=sale_price,
                sales_30d=p_data.get("sales_30d"),
                rating=p_data.get("rating"),
                reviews_count=p_data.get("reviews_count"),
                competitors_count=p_data.get("competitors_count"),
                margin_pct=margin,
                roi_pct=roi,
            )

        if existing:
            existing.price_rub = p_data.get("price_rub") or existing.price_rub
            existing.price_sale_rub = sale_price or existing.price_sale_rub
            existing.discount_pct = p_data.get("discount_pct")
            existing.sales_30d = p_data.get("sales_30d") or existing.sales_30d
            existing.rating = p_data.get("rating") or existing.rating
            existing.reviews_count = p_data.get("reviews_count") or existing.reviews_count
            existing.in_stock = p_data.get("in_stock", True)
            existing.margin_pct = margin
            existing.roi_pct = roi
            existing.ai_score = ai_score
            saved.append(existing)
        else:
            prod = Product(
                wb_sku=wb_sku,
                name=p_data.get("name", ""),
                brand=p_data.get("brand", ""),
                seller=p_data.get("seller", ""),
                category_id=cat_id,
                price_rub=p_data.get("price_rub"),
                price_sale_rub=sale_price or None,
                discount_pct=p_data.get("discount_pct"),
                sales_30d=p_data.get("sales_30d"),
                revenue_30d_rub=p_data.get("revenue_30d_rub"),
                rating=p_data.get("rating"),
                reviews_count=p_data.get("reviews_count"),
                in_stock=p_data.get("in_stock", True),
                margin_pct=margin,
                roi_pct=roi,
                ai_score=ai_score,
            )
            db.add(prod)
            saved.append(prod)

    await db.commit()
    return saved


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "openclaw-api"}


@app.post("/products/search")
async def products_search(req: ProductSearchRequest):
    """
    Search WB, calculate unit econ, score products, persist to DB.
    """
    settings = UnitEconSettings(
        wb_commission_pct=req.wb_commission_pct or 15.0,
        logistics_rub=req.logistics_rub or 150.0,
    )
    raw_products = await search_and_parse(req.query, limit=req.limit)
    if not raw_products:
        return {"query": req.query, "products": [], "total": 0}

    # Enrich with unit econ
    enriched = []
    for p in raw_products:
        sale_price = p.get("price_sale_rub") or p.get("price_rub") or 0.0
        unit_cost = req.unit_cost_rub or (sale_price * 0.4)  # assume 40% cost ratio if not provided
        if sale_price > 0 and unit_cost > 0:
            ue = calculate_unit_econ(sale_price, unit_cost, settings=settings)
            p["unit_cost_rub"] = unit_cost
            p["gross_profit_rub"] = ue.gross_profit_rub
            p["margin_pct"] = ue.margin_pct
            p["roi_pct"] = ue.roi_pct
        p["ai_score"] = score_product(
            price_rub=sale_price,
            sales_30d=p.get("sales_30d"),
            rating=p.get("rating"),
            reviews_count=p.get("reviews_count"),
            competitors_count=p.get("competitors_count"),
            margin_pct=p.get("margin_pct"),
            roi_pct=p.get("roi_pct"),
        )
        enriched.append(p)

    enriched.sort(key=lambda x: x.get("ai_score", 0), reverse=True)

    # Persist to DB
    async with SessionLocal() as db:
        await _save_products(db, enriched, category_name=req.query, settings=settings)

    return {"query": req.query, "products": enriched, "total": len(enriched)}


@app.get("/products/top")
async def products_top(limit: int = Query(default=10, le=100)):
    """Get top scored products from DB."""
    async with SessionLocal() as db:
        result = await db.execute(
            select(Product)
            .where(Product.ai_score.isnot(None))
            .order_by(desc(Product.ai_score))
            .limit(limit)
        )
        products = result.scalars().all()
    return {
        "products": [
            {
                "id": p.id,
                "wb_sku": p.wb_sku,
                "name": p.name,
                "brand": p.brand,
                "price_sale_rub": p.price_sale_rub,
                "sales_30d": p.sales_30d,
                "rating": p.rating,
                "reviews_count": p.reviews_count,
                "margin_pct": p.margin_pct,
                "roi_pct": p.roi_pct,
                "ai_score": p.ai_score,
            }
            for p in products
        ]
    }


@app.post("/products/calc")
async def products_calc(req: CalcRequest):
    """Calculate unit economics for given parameters."""
    settings = UnitEconSettings(
        wb_commission_pct=req.wb_commission_pct,
        logistics_rub=req.logistics_rub,
        storage_rate=req.storage_rate,
        return_rate=req.return_rate,
    )
    result = calculate_unit_econ(
        sale_price_rub=req.sale_price_rub,
        unit_cost_rub=req.unit_cost_rub,
        monthly_fixed_costs_rub=req.monthly_fixed_costs_rub,
        settings=settings,
    )
    message = format_unit_econ_message(result, req.product_name)
    return {
        "result": {
            "sale_price_rub": result.sale_price_rub,
            "unit_cost_rub": result.unit_cost_rub,
            "wb_commission_rub": result.wb_commission_rub,
            "logistics_rub": result.logistics_rub,
            "storage_rub": result.storage_rub,
            "returns_loss_rub": result.returns_loss_rub,
            "gross_profit_rub": result.gross_profit_rub,
            "margin_pct": result.margin_pct,
            "roi_pct": result.roi_pct,
            "breakeven_units_per_month": result.breakeven_units_per_month,
        },
        "message": message,
    }


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    async with SessionLocal() as db:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "id": product.id,
        "wb_sku": product.wb_sku,
        "name": product.name,
        "brand": product.brand,
        "seller": product.seller,
        "price_rub": product.price_rub,
        "price_sale_rub": product.price_sale_rub,
        "sales_30d": product.sales_30d,
        "rating": product.rating,
        "reviews_count": product.reviews_count,
        "margin_pct": product.margin_pct,
        "roi_pct": product.roi_pct,
        "ai_score": product.ai_score,
        "ai_verdict": product.ai_verdict,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


@app.get("/categories")
async def list_categories():
    async with SessionLocal() as db:
        result = await db.execute(
            select(Category.id, Category.name, func.count(Product.id).label("product_count"))
            .outerjoin(Product, Product.category_id == Category.id)
            .group_by(Category.id, Category.name)
            .order_by(Category.name)
        )
        rows = result.all()
    return {"categories": [{"id": r.id, "name": r.name, "product_count": r.product_count} for r in rows]}


@app.post("/ai/recommend")
async def ai_recommend(req: AIRecommendRequest):
    if not req.products:
        # Fetch from DB
        async with SessionLocal() as db:
            result = await db.execute(
                select(Product).order_by(desc(Product.ai_score)).limit(20)
            )
            db_products = result.scalars().all()
            req.products = [
                {
                    "name": p.name,
                    "price_sale_rub": p.price_sale_rub or 0,
                    "margin_pct": p.margin_pct or 0,
                    "roi_pct": p.roi_pct or 0,
                    "sales_30d": p.sales_30d,
                    "rating": p.rating,
                    "reviews_count": p.reviews_count,
                }
                for p in db_products
            ]
    recommendation = await recommend_products(req.query, req.products, top_n=req.top_n)
    return {"recommendation": recommendation}


@app.post("/ai/analyse")
async def ai_analyse(req: AIAnalyseRequest):
    verdict = await analyse_product(req.product)
    return {"verdict": verdict}


@app.post("/ai/question")
async def ai_question(req: AIQuestionRequest):
    answer = await answer_question(req.question)
    return {"answer": answer}


@app.get("/dashboard/stats")
async def dashboard_stats():
    async with SessionLocal() as db:
        total_products = (await db.execute(select(func.count(Product.id)))).scalar()
        avg_margin = (await db.execute(
            select(func.avg(Product.margin_pct)).where(Product.margin_pct.isnot(None))
        )).scalar()
        avg_roi = (await db.execute(
            select(func.avg(Product.roi_pct)).where(Product.roi_pct.isnot(None))
        )).scalar()
        top_products = (await db.execute(
            select(Product).order_by(desc(Product.ai_score)).limit(5)
        )).scalars().all()
        category_stats = (await db.execute(
            select(Category.name, func.count(Product.id).label("count"))
            .outerjoin(Product, Product.category_id == Category.id)
            .group_by(Category.name)
            .order_by(desc("count"))
            .limit(10)
        )).all()

    return {
        "total_products": total_products or 0,
        "avg_margin_pct": round(float(avg_margin or 0), 1),
        "avg_roi_pct": round(float(avg_roi or 0), 1),
        "top_products": [
            {
                "name": p.name[:50],
                "price_sale_rub": p.price_sale_rub,
                "margin_pct": p.margin_pct,
                "roi_pct": p.roi_pct,
                "ai_score": p.ai_score,
            }
            for p in top_products
        ],
        "categories": [{"name": r.name, "count": r.count} for r in category_stats],
    }


@app.post("/users/upsert")
async def upsert_user(req: UserUpsertRequest):
    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramUser).where(TelegramUser.tg_id == req.tg_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = TelegramUser(
                tg_id=req.tg_id,
                username=req.username,
                full_name=req.full_name,
            )
            db.add(user)
        else:
            if req.username is not None:
                user.username = req.username
            if req.full_name is not None:
                user.full_name = req.full_name
        await db.commit()
    return {"status": "ok", "tg_id": req.tg_id}


@app.get("/users/{tg_id}/settings")
async def get_user_settings(tg_id: int):
    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramUser).where(TelegramUser.tg_id == tg_id)
        )
        user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "wb_commission_pct": user.wb_commission_pct,
        "logistics_rub": user.logistics_rub,
        "storage_rate": user.storage_rate,
        "return_rate": user.return_rate,
    }


@app.post("/users/{tg_id}/settings")
async def update_user_settings(tg_id: int, update: UserSettingsUpdate):
    async with SessionLocal() as db:
        result = await db.execute(
            select(TelegramUser).where(TelegramUser.tg_id == tg_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if update.wb_commission_pct is not None:
            user.wb_commission_pct = update.wb_commission_pct
        if update.logistics_rub is not None:
            user.logistics_rub = update.logistics_rub
        if update.storage_rate is not None:
            user.storage_rate = update.storage_rate
        if update.return_rate is not None:
            user.return_rate = update.return_rate
        await db.commit()
    return {"status": "ok"}
