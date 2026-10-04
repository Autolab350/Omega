"""GateChain: fail-closed pre-trade controls on the order path.

Every gate returns a Verdict with a stable code and evidence. The chain stops on the
first DENY. MODIFY patches the order and continues. Deterministic only; nothing here
reads prose or calls a model. `check` audits the steps; `go` re-runs the chain right
before submit (defense in depth, same as a brokerage write path).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .round_price import round_limit
from .types import Account, AssetClass, OpenClose, Order, Side

ALLOW, DENY, MODIFY = "ALLOW", "DENY", "MODIFY"


@dataclass
class Verdict:
    decision: str  # ALLOW | DENY | MODIFY
    code: str
    reason: str
    order_patch: dict | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def allow(code: str, reason: str = "ok", **ev) -> Verdict:
    return Verdict(ALLOW, code, reason, evidence=ev)


def deny(code: str, reason: str, **ev) -> Verdict:
    return Verdict(DENY, code, reason, evidence=ev)


def modify(code: str, reason: str, patch: dict, **ev) -> Verdict:
    return Verdict(MODIFY, code, reason, order_patch=patch, evidence=ev)


class Gate(Protocol):
    code: str

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict: ...


# --- phase A gates -----------------------------------------------------------


class DataPresent:
    """SYS_001 — fail closed when the order or market context is incomplete."""

    code = "SYS_001"

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        missing = []
        if not order.symbol:
            missing.append("symbol")
        if order.qty is None:
            missing.append("qty")
        if account is None or account.cash is None:
            missing.append("account.cash")
        if order.asset_class is AssetClass.OPTION and order.occ is None:
            missing.append("occ")
        if market.get("require_spot") and order.occ:
            if order.occ["underlying"] not in (market.get("spot") or {}):
                missing.append(f"spot[{order.occ['underlying']}]")
        if missing:
            return deny(self.code, f"missing {', '.join(missing)}", missing=missing)
        return allow(self.code)


class HaltFlag:
    """KILL_001 — any halt signal blocks every send."""

    code = "KILL_001"

    def __init__(self, halt_file: str | Path | None = None) -> None:
        self.halt_file = Path(halt_file) if halt_file else None

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        if market.get("halt"):
            return deny(self.code, "halt flag set in market context", source="market")
        if os.environ.get("QS_HALT"):
            return deny(self.code, "QS_HALT set in environment", source="env")
        hf = self.halt_file or (Path(market["halt_file"]) if market.get("halt_file") else None)
        if hf and hf.exists():
            return deny(self.code, f"halt file present: {hf}", source="file")
        return allow(self.code)


class QtyBounds:
    """SIZE_001 — whole, positive, under the fat-finger cap."""

    code = "SIZE_001"

    def __init__(self, max_qty: float = 10) -> None:
        self.max_qty = max_qty

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        cap = market.get("max_qty", self.max_qty)
        q = order.qty
        if q <= 0:
            return deny(self.code, "qty must be > 0", qty=q)
        if order.asset_class in (AssetClass.OPTION, AssetClass.EQUITY, AssetClass.FUTURE) and q != int(q):
            return deny(self.code, "qty must be whole for this asset class", qty=q)
        if q > cap:
            return deny(self.code, f"qty {q} exceeds cap {cap}", qty=q, cap=cap)
        return allow(self.code, qty=q, cap=cap)


class LimitRequired:
    """LIMIT_001 — no market orders on options or equity; round to venue tick."""

    code = "LIMIT_001"

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        if order.asset_class in (AssetClass.OPTION, AssetClass.EQUITY):
            if order.limit is None or order.limit <= 0:
                return deny(self.code, "limit price required", limit=order.limit)
            rounded = round_limit(order).limit
            if rounded != order.limit:
                return modify(self.code, "limit rounded to tick", {"limit": rounded}, was=order.limit, now=rounded)
        return allow(self.code, limit=order.limit)


class BuyingPower:
    """CASH_001 — cash-secured: short put reserves strike x 100 x qty; debit pays premium."""

    code = "CASH_001"

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        need = 0.0
        if order.open_or_close is OpenClose.OPEN:
            occ = order.occ
            if order.side is Side.SELL and occ and occ["right"] == "P":
                need = occ["strike"] * order.multiplier * order.qty
            elif order.side is Side.BUY and order.limit is not None:
                need = order.limit * order.multiplier * order.qty
        bp = account.buying_power
        if need > bp + 1e-9:
            return deny(self.code, f"need {need:.2f} > buying power {bp:.2f}", need=round(need, 2), buying_power=bp)
        return allow(self.code, need=round(need, 2), buying_power=bp)


class StrategyCompat:
    """BOOK_001 — defined-risk books only; closes need a position to close."""

    code = "BOOK_001"

    def evaluate(self, order: Order, account: Account, market: dict) -> Verdict:
        occ = order.occ
        if order.open_or_close is OpenClose.OPEN and order.side is Side.SELL and occ and occ["right"] == "C":
            held = account.positions.get(occ["underlying"])
            if not held or held.qty < 100 * order.qty:
                return deny(self.code, "short call needs 100 shares per contract (no naked calls)", underlying=occ["underlying"])
        if order.open_or_close is OpenClose.CLOSE:
            pos = account.positions.get(order.symbol)
            if not pos or pos.qty == 0:
                return deny(self.code, "nothing to close", symbol=order.symbol)
            if (pos.qty > 0 and order.side is Side.BUY) or (pos.qty < 0 and order.side is Side.SELL):
                return deny(self.code, "close side must offset position", pos_qty=pos.qty, side=order.side.value)
            if order.qty > abs(pos.qty):
                return deny(self.code, "close qty exceeds position", pos_qty=pos.qty, qty=order.qty)
        return allow(self.code)


# --- chain -------------------------------------------------------------------


def default_chain(*, max_qty: float = 10, halt_file: str | Path | None = None) -> list[Gate]:
    return [DataPresent(), HaltFlag(halt_file), QtyBounds(max_qty), LimitRequired(), BuyingPower(), StrategyCompat()]


class GateChain:
    def __init__(self, gates: list[Gate] | None = None) -> None:
        self.gates: list[Gate] = list(gates or default_chain())

    def run(self, order: Order, account: Account, market: dict | None = None) -> dict:
        market = dict(market or {})
        steps: list[Verdict] = []
        current = order
        for g in self.gates:
            v = g.evaluate(current, account, market)
            steps.append(v)
            if v.decision == DENY:
                return {"decision": DENY, "code": v.code, "reason": v.reason, "steps": [s.to_dict() for s in steps], "order": current.with_(status="rejected").to_dict()}
            if v.decision == MODIFY and v.order_patch:
                current = current.with_(**v.order_patch)
        final = MODIFY if any(s.decision == MODIFY for s in steps) else ALLOW
        return {"decision": final, "code": None, "reason": "all gates passed", "steps": [s.to_dict() for s in steps], "order": current.to_dict()}


def run_gates(order: Order, account: Account, market: dict | None = None, chain: GateChain | list[Gate] | None = None) -> dict:
    gc = chain if isinstance(chain, GateChain) else GateChain(chain)
    return gc.run(order, account, market)


__all__ = [
    "ALLOW",
    "DENY",
    "MODIFY",
    "Verdict",
    "Gate",
    "GateChain",
    "run_gates",
    "default_chain",
    "DataPresent",
    "HaltFlag",
    "QtyBounds",
    "LimitRequired",
    "BuyingPower",
    "StrategyCompat",
]
