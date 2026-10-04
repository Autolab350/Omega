"""Tick rules so a limit is something the venue will accept."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .types import AssetClass, Order

PENNY_PILOT = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "EEM"}


def option_tick(underlying: str, price: float) -> float:
    if underlying.upper() in PENNY_PILOT:
        return 0.01
    return 0.05 if price < 3.0 else 0.10


def tick_for(order: Order) -> float:
    if order.asset_class is AssetClass.OPTION and order.limit is not None:
        occ = order.occ
        return option_tick(occ["underlying"] if occ else order.symbol, order.limit)
    if order.asset_class is AssetClass.EQUITY:
        return 0.01
    return 0.0  # crypto / future: pass through


def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    q = Decimal(str(tick))
    return float((Decimal(str(price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)


def round_limit(order: Order) -> Order:
    if order.limit is None:
        return order
    return order.with_(limit=round_to_tick(order.limit, tick_for(order)))


__all__ = ["PENNY_PILOT", "option_tick", "tick_for", "round_to_tick", "round_limit"]
