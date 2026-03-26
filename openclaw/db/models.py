"""
SQLAlchemy ORM models for OpenClaw.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProductStatus(str, enum.Enum):
    active = "active"
    archived = "archived"
    out_of_stock = "out_of_stock"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    wb_subject_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    products: Mapped[List["Product"]] = relationship("Product", back_populates="category")
    children: Mapped[List["Category"]] = relationship("Category", back_populates="parent")
    parent: Mapped[Optional["Category"]] = relationship(
        "Category", back_populates="children", remote_side="Category.id"
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wb_sku: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    brand: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    seller: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.active
    )

    # Pricing
    price_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_sale_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Sales metrics
    sales_30d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revenue_30d_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reviews_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)

    # Competitor count
    competitors_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Unit economics (calculated)
    unit_cost_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_profit_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roi_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # AI scoring
    ai_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[Optional[Category]] = relationship("Category", back_populates="products")
    price_history: Mapped[List["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="product", cascade="all, delete-orphan"
    )
    supplier_offers: Mapped[List["SupplierOffer"]] = relationship(
        "SupplierOffer", back_populates="product", cascade="all, delete-orphan"
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price_rub: Mapped[float] = mapped_column(Float)
    sales_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    product: Mapped[Product] = relationship("Product", back_populates="price_history")


class SupplierOffer(Base):
    """Price from Alibaba / 1688 supplier for a given product."""

    __tablename__ = "supplier_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    supplier_name: Mapped[str] = mapped_column(String(300))
    supplier_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    price_cny: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_rub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_order_qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    product: Mapped[Product] = relationship("Product", back_populates="supplier_offers")


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # User-specific unit-econ settings
    wb_commission_pct: Mapped[float] = mapped_column(Float, default=15.0)
    logistics_rub: Mapped[float] = mapped_column(Float, default=150.0)
    storage_rate: Mapped[float] = mapped_column(Float, default=0.15)
    return_rate: Mapped[float] = mapped_column(Float, default=0.10)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    requests: Mapped[List["UserRequest"]] = relationship(
        "UserRequest", back_populates="user", cascade="all, delete-orphan"
    )


class UserRequest(Base):
    """Log of user queries for analytics."""

    __tablename__ = "user_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(Text)
    response_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[TelegramUser] = relationship("TelegramUser", back_populates="requests")


class ScraperTask(Base):
    """Tracks periodic scraping jobs."""

    __tablename__ = "scraper_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)
    target: Mapped[str] = mapped_column(String(500))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.pending, index=True
    )
    products_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
