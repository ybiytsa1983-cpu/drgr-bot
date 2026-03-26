"""
Unit-economics calculator and product scoring.

Formula:
  gross_profit = sale_price - wb_commission - logistics - storage - returns_loss
  margin_pct   = gross_profit / sale_price * 100
  roi_pct      = gross_profit / unit_cost * 100
  ai_score     = weighted combination of margin, roi, demand, competition
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_WB_COMMISSION_PCT = float(os.getenv("DEFAULT_WB_COMMISSION_PCT", 15.0))
DEFAULT_LOGISTICS_RUB = float(os.getenv("DEFAULT_LOGISTICS_RUB", 150.0))
DEFAULT_STORAGE_RATE = float(os.getenv("DEFAULT_STORAGE_RATE", 0.15))
DEFAULT_RETURN_RATE = float(os.getenv("DEFAULT_RETURN_RATE", 0.10))


@dataclass
class UnitEconSettings:
    wb_commission_pct: float = DEFAULT_WB_COMMISSION_PCT
    logistics_rub: float = DEFAULT_LOGISTICS_RUB
    storage_rate: float = DEFAULT_STORAGE_RATE   # fraction of sale price
    return_rate: float = DEFAULT_RETURN_RATE      # fraction of sales


@dataclass
class UnitEconResult:
    sale_price_rub: float
    unit_cost_rub: float
    wb_commission_rub: float
    logistics_rub: float
    storage_rub: float
    returns_loss_rub: float
    gross_profit_rub: float
    margin_pct: float
    roi_pct: float
    breakeven_units_per_month: Optional[int]


def calculate_unit_econ(
    sale_price_rub: float,
    unit_cost_rub: float,
    monthly_fixed_costs_rub: float = 0.0,
    settings: Optional[UnitEconSettings] = None,
) -> UnitEconResult:
    """
    Calculate full unit economics for one unit sold on Wildberries.

    Parameters
    ----------
    sale_price_rub:
        Customer-facing sale price on WB.
    unit_cost_rub:
        Your total cost per unit (purchase price + delivery to WB warehouse).
    monthly_fixed_costs_rub:
        Optional monthly fixed costs (advertising, SaaS tools, etc.)
    settings:
        Platform fee / logistics overrides. Uses env defaults if None.
    """
    if settings is None:
        settings = UnitEconSettings()

    wb_commission_rub = sale_price_rub * settings.wb_commission_pct / 100
    storage_rub = sale_price_rub * settings.storage_rate
    returns_loss_rub = (
        sale_price_rub * settings.return_rate * settings.wb_commission_pct / 100
    )  # WB doesn't refund commission on returns

    total_variable_cost = (
        unit_cost_rub
        + wb_commission_rub
        + settings.logistics_rub
        + storage_rub
        + returns_loss_rub
    )
    gross_profit_rub = sale_price_rub - total_variable_cost

    margin_pct = (gross_profit_rub / sale_price_rub * 100) if sale_price_rub > 0 else 0.0
    roi_pct = (gross_profit_rub / unit_cost_rub * 100) if unit_cost_rub > 0 else 0.0

    breakeven_units: Optional[int] = None
    if gross_profit_rub > 0 and monthly_fixed_costs_rub > 0:
        breakeven_units = int(monthly_fixed_costs_rub / gross_profit_rub) + 1
    elif monthly_fixed_costs_rub == 0:
        breakeven_units = 1

    return UnitEconResult(
        sale_price_rub=sale_price_rub,
        unit_cost_rub=unit_cost_rub,
        wb_commission_rub=round(wb_commission_rub, 2),
        logistics_rub=round(settings.logistics_rub, 2),
        storage_rub=round(storage_rub, 2),
        returns_loss_rub=round(returns_loss_rub, 2),
        gross_profit_rub=round(gross_profit_rub, 2),
        margin_pct=round(margin_pct, 1),
        roi_pct=round(roi_pct, 1),
        breakeven_units_per_month=breakeven_units,
    )


def score_product(
    price_rub: float,
    sales_30d: Optional[int],
    rating: Optional[float],
    reviews_count: Optional[int],
    competitors_count: Optional[int],
    margin_pct: Optional[float],
    roi_pct: Optional[float],
) -> float:
    """
    Score a product from 0.0 to 10.0.

    Higher score = more promising for entry.

    Factors (weights):
    - margin_pct     30 %
    - roi_pct        25 %
    - demand (sales) 25 %
    - rating         10 %
    - competition    10 %  (inverse)
    """
    score = 0.0

    # --- Margin (0-3 pts) ---
    if margin_pct is not None:
        if margin_pct >= 30:
            score += 3.0
        elif margin_pct >= 20:
            score += 2.0
        elif margin_pct >= 10:
            score += 1.0

    # --- ROI (0-2.5 pts) ---
    if roi_pct is not None:
        if roi_pct >= 100:
            score += 2.5
        elif roi_pct >= 50:
            score += 1.5
        elif roi_pct >= 25:
            score += 0.75

    # --- Demand (0-2.5 pts) ---
    if sales_30d is not None:
        if sales_30d >= 500:
            score += 2.5
        elif sales_30d >= 100:
            score += 1.5
        elif sales_30d >= 30:
            score += 0.75

    # --- Rating (0-1 pt) ---
    if rating is not None:
        score += min(1.0, rating / 5.0)

    # --- Competition (0-1 pt inverse) ---
    if competitors_count is not None:
        if competitors_count < 50:
            score += 1.0
        elif competitors_count < 200:
            score += 0.5
        elif competitors_count < 500:
            score += 0.25

    return round(min(score, 10.0), 2)


def format_unit_econ_message(result: UnitEconResult, product_name: str = "") -> str:
    """Format UnitEconResult as a Telegram-friendly HTML string."""
    name_line = f"<b>📦 {product_name}</b>\n\n" if product_name else ""
    verdict = (
        "✅ <b>Прибыльный</b>" if result.margin_pct >= 20
        else ("⚠️ <b>Низкая маржа</b>" if result.margin_pct >= 5 else "❌ <b>Убыточный</b>")
    )
    lines = [
        f"{name_line}💰 <b>Юнит-экономика</b>\n",
        f"Цена продажи:     <code>{result.sale_price_rub:.0f} ₽</code>",
        f"Себестоимость:    <code>{result.unit_cost_rub:.0f} ₽</code>",
        f"Комиссия WB:      <code>- {result.wb_commission_rub:.0f} ₽</code>",
        f"Логистика:        <code>- {result.logistics_rub:.0f} ₽</code>",
        f"Хранение:         <code>- {result.storage_rub:.0f} ₽</code>",
        f"Возвраты:         <code>- {result.returns_loss_rub:.0f} ₽</code>",
        "",
        f"Прибыль с ед.:    <code>{result.gross_profit_rub:.0f} ₽</code>",
        f"Маржинальность:   <code>{result.margin_pct:.1f}%</code>",
        f"ROI:              <code>{result.roi_pct:.1f}%</code>",
    ]
    if result.breakeven_units_per_month:
        lines.append(f"Точка безубыточности: <code>{result.breakeven_units_per_month} шт/мес</code>")
    lines.append(f"\n{verdict}")
    return "\n".join(lines)