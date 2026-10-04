"""One Order for the whole kit. Side + open/close covers BTO / STO / BTC / STC."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"
    FUTURE = "future"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OpenClose(str, Enum):
    OPEN = "open"
    CLOSE = "close"


class OrderStatus(str, Enum):
    NEW = "new"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


_OCC = re.compile(r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def parse_occ(symbol: str) -> dict | None:
    m = _OCC.match(symbol.upper())
    if not m:
        return None
    u, yy, mm, dd, r, k = m.groups()
    return {"underlying": u, "expiry": f"20{yy}-{mm}-{dd}", "right": r, "strike": int(k) / 1000}


def multiplier(asset_class: AssetClass | str) -> int:
    return 100 if AssetClass(asset_class) is AssetClass.OPTION else 1


@dataclass(frozen=True)
class Order:
    asset_class: AssetClass
    symbol: str  # AAPL · QQQ261002C00756000 · BTC-USD · ESU6
    side: Side
    open_or_close: OpenClose
    qty: float
    limit: float | None
    venue: str = "paper"
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: OrderStatus = OrderStatus.NEW
    tag: str = ""  # book name, e.g. credit_put

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_class", AssetClass(self.asset_class))
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "open_or_close", OpenClose(self.open_or_close))
        object.__setattr__(self, "status", OrderStatus(self.status))
        object.__setattr__(self, "symbol", self.symbol.upper())

    @property
    def occ(self) -> dict | None:
        return parse_occ(self.symbol) if self.asset_class is AssetClass.OPTION else None

    @property
    def multiplier(self) -> int:
        return multiplier(self.asset_class)

    @property
    def notional(self) -> float | None:
        return None if self.limit is None else round(abs(self.limit) * self.multiplier * self.qty, 2)

    def with_(self, **changes) -> "Order":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("asset_class", "side", "open_or_close", "status"):
            d[k] = d[k].value if hasattr(d[k], "value") else d[k]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Order":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    open_or_close: OpenClose
    qty: float
    price: float
    ts: int = field(default_factory=lambda: int(time.time()))
    venue: str = "paper"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["side"], d["open_or_close"] = self.side.value, self.open_or_close.value
        return d


@dataclass
class Position:
    symbol: str
    qty: float = 0.0  # negative = short
    avg: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Account:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    reserved: float = 0.0  # cash held against short puts
    venue: str = "paper"

    @property
    def buying_power(self) -> float:
        return round(self.cash - self.reserved, 2)

    def to_dict(self) -> dict:
        return {
            "cash": round(self.cash, 2),
            "reserved": round(self.reserved, 2),
            "buying_power": self.buying_power,
            "venue": self.venue,
            "positions": {k: v.to_dict() for k, v in self.positions.items() if v.qty != 0},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        pos = {k: Position(**v) for k, v in (d.get("positions") or {}).items()}
        return cls(cash=float(d["cash"]), positions=pos, reserved=float(d.get("reserved", 0.0)), venue=d.get("venue", "paper"))


__all__ = [
    "AssetClass",
    "Side",
    "OpenClose",
    "OrderStatus",
    "Order",
    "Fill",
    "Position",
    "Account",
    "parse_occ",
    "multiplier",
]
