"""Books build orders. They never send. Freqtrade shape: entry / exit per class."""

from __future__ import annotations

from .types import AssetClass, OpenClose, Order, Position, Side


def occ_symbol(underlying: str, expiry: str, right: str, strike: float) -> str:
    y, m, d = (int(x) for x in expiry.split("-"))
    return f"{underlying.upper()}{y % 100:02d}{m:02d}{d:02d}{right.upper()}{int(round(strike * 1000)):08d}"


class CreditPut:
    """Cash-secured put: sell to open, buy to close."""

    name = "credit_put"

    def entry(self, *, underlying: str, strike: float, expiry: str, limit: float, qty: int = 1, venue: str = "paper") -> Order:
        return Order(AssetClass.OPTION, occ_symbol(underlying, expiry, "P", strike), Side.SELL, OpenClose.OPEN, qty, limit, venue, tag=self.name)

    def exit(self, position: Position, *, limit: float, qty: int | None = None, venue: str = "paper") -> Order:
        q = qty or int(abs(position.qty))
        return Order(AssetClass.OPTION, position.symbol, Side.BUY, OpenClose.CLOSE, q, limit, venue, tag=self.name)


class DebitCall:
    """Long call: buy to open, sell to close."""

    name = "debit_call"

    def entry(self, *, underlying: str, strike: float, expiry: str, limit: float, qty: int = 1, venue: str = "paper") -> Order:
        return Order(AssetClass.OPTION, occ_symbol(underlying, expiry, "C", strike), Side.BUY, OpenClose.OPEN, qty, limit, venue, tag=self.name)

    def exit(self, position: Position, *, limit: float, qty: int | None = None, venue: str = "paper") -> Order:
        q = qty or int(abs(position.qty))
        return Order(AssetClass.OPTION, position.symbol, Side.SELL, OpenClose.CLOSE, q, limit, venue, tag=self.name)


class Shares:
    """Plain equity / crypto / future line. Same Order shape."""

    name = "shares"

    def entry(self, *, symbol: str, side: str, qty: float, limit: float | None, asset_class: str = "equity", venue: str = "paper") -> Order:
        return Order(AssetClass(asset_class), symbol, Side(side), OpenClose.OPEN, qty, limit, venue, tag=self.name)


BOOKS: dict[str, type] = {"credit_put": CreditPut, "debit_call": DebitCall, "shares": Shares}


def get_book(name: str):
    try:
        return BOOKS[name]()
    except KeyError as e:
        raise KeyError(f"unknown book {name!r}; known: {sorted(BOOKS)}") from e


__all__ = ["CreditPut", "DebitCall", "Shares", "BOOKS", "get_book", "occ_symbol"]
