"""ExecutionClient protocol and the paper venue. Nautilus names: submit_order / cancel_order."""

from __future__ import annotations

from typing import Protocol

from .types import Account, AssetClass, Fill, OpenClose, Order, OrderStatus, Position, Side


class ExecutionClient(Protocol):
    venue: str

    def submit_order(self, order: Order, account: Account) -> Fill: ...

    def cancel_order(self, order_id: str) -> bool: ...


class PaperExecutionClient:
    """Fills at the limit (or a supplied mark) and books cash, reserve, and position."""

    venue = "paper"

    def __init__(self) -> None:
        self.open_orders: dict[str, Order] = {}
        self.fills: list[Fill] = []

    def submit_order(self, order: Order, account: Account, *, mark: float | None = None) -> Fill:
        if order.venue != self.venue:
            raise ValueError(f"order venue {order.venue!r} is not {self.venue!r}")
        price = mark if mark is not None else order.limit
        if price is None:
            raise ValueError("paper fill needs a limit or a mark")
        fill = Fill(order.order_id, order.symbol, order.side, order.open_or_close, order.qty, float(price), venue=self.venue)
        self._apply(fill, order, account)
        self.fills.append(fill)
        self.open_orders.pop(order.order_id, None)
        return fill

    def cancel_order(self, order_id: str) -> bool:
        return self.open_orders.pop(order_id, None) is not None

    # --- bookkeeping ---------------------------------------------------------
    def _apply(self, fill: Fill, order: Order, account: Account) -> None:
        mult = order.multiplier
        cash_delta = fill.price * mult * fill.qty
        signed = fill.qty if fill.side is Side.BUY else -fill.qty
        pos = account.positions.setdefault(fill.symbol, Position(fill.symbol))
        new_qty = pos.qty + signed

        if fill.side is Side.BUY:
            account.cash -= cash_delta
        else:
            account.cash += cash_delta

        # short put reserve: hold strike x 100 per contract while short
        occ = order.occ
        if order.asset_class is AssetClass.OPTION and occ and occ["right"] == "P":
            reserve_per = occ["strike"] * mult
            if fill.open_or_close is OpenClose.OPEN and fill.side is Side.SELL:
                account.reserved += reserve_per * fill.qty
            elif fill.open_or_close is OpenClose.CLOSE and fill.side is Side.BUY:
                account.reserved = max(0.0, account.reserved - reserve_per * fill.qty)

        # average price: reset when crossing or opening, keep when adding same direction
        if pos.qty == 0 or (pos.qty > 0) != (new_qty > 0) and new_qty != 0:
            pos.avg = fill.price
        elif abs(new_qty) > abs(pos.qty):
            pos.avg = round((pos.avg * abs(pos.qty) + fill.price * fill.qty) / abs(new_qty), 4)
        pos.qty = new_qty
        if new_qty == 0:
            pos.avg = 0.0
        account.cash = round(account.cash, 2)
        account.reserved = round(account.reserved, 2)


CLIENTS: dict[str, type] = {"paper": PaperExecutionClient}


def get_client(venue: str = "paper") -> ExecutionClient:
    try:
        return CLIENTS[venue]()
    except KeyError as e:
        raise KeyError(f"no ExecutionClient for venue {venue!r}; known: {sorted(CLIENTS)}") from e


__all__ = ["ExecutionClient", "PaperExecutionClient", "CLIENTS", "get_client", "OrderStatus"]
