import pytest

from omega import ALLOW, DENY, MODIFY, Account, CreditPut, DebitCall, GateChain, Order, Position, run_gates
from omega.types import AssetClass, OpenClose, Side


def csp(strike=700, limit=2.10, qty=1, underlying="SPY"):
    return CreditPut().entry(underlying=underlying, strike=strike, expiry="2026-10-17", limit=limit, qty=qty)


def test_csp_reserves_strike_times_100():
    o = csp()
    assert o.symbol == "SPY261017P00700000"
    assert o.side is Side.SELL and o.open_or_close is OpenClose.OPEN
    assert o.occ["strike"] == 700.0


def test_deny_when_csp_reserve_exceeds_cash():
    r = run_gates(csp(strike=700), Account(cash=50_000))
    assert r["decision"] == DENY and r["code"] == "CASH_001"
    assert r["steps"][-1]["evidence"]["need"] == 70_000.0
    assert r["order"]["status"] == "rejected"


def test_allow_when_cash_covers_reserve():
    r = run_gates(csp(strike=700), Account(cash=80_000))
    assert r["decision"] == ALLOW
    assert [s["code"] for s in r["steps"]] == ["SYS_001", "KILL_001", "SIZE_001", "LIMIT_001", "CASH_001", "BOOK_001"]


def test_deny_when_halt_flag_set(monkeypatch, tmp_path):
    acct = Account(cash=100_000)
    assert run_gates(csp(), acct, {"halt": True})["code"] == "KILL_001"
    monkeypatch.setenv("QS_HALT", "1")
    assert run_gates(csp(), acct)["code"] == "KILL_001"
    monkeypatch.delenv("QS_HALT")
    hf = tmp_path / "HALT"
    hf.write_text("stop")
    assert run_gates(csp(), acct, {"halt_file": str(hf)})["code"] == "KILL_001"


def test_deny_oversize_and_fractional_option_qty():
    acct = Account(cash=1_000_000)
    assert run_gates(csp(qty=11), acct)["code"] == "SIZE_001"
    assert run_gates(csp(qty=0), acct)["code"] == "SIZE_001"
    assert run_gates(csp(qty=1.5), acct)["code"] == "SIZE_001"


def test_deny_missing_limit_and_modify_rounds_tick():
    acct = Account(cash=1_000_000)
    assert run_gates(csp(limit=None), acct)["code"] == "LIMIT_001"
    r = run_gates(DebitCall().entry(underlying="TSLA", strike=375, expiry="2026-10-02", limit=0.57), acct)
    assert r["decision"] == MODIFY
    assert r["order"]["limit"] == 0.55  # nickel tick under $3 for non-penny names
    assert run_gates(csp(limit=2.123), acct)["order"]["limit"] == 2.12  # SPY penny


def test_debit_call_pays_premium_from_cash():
    o = DebitCall().entry(underlying="QQQ", strike=756, expiry="2026-10-02", limit=0.42, qty=4)
    assert run_gates(o, Account(cash=100))["code"] == "CASH_001"
    assert run_gates(o, Account(cash=200))["decision"] == ALLOW


def test_book_compat_denies_naked_call_and_bad_close():
    acct = Account(cash=1_000_000)
    naked = Order(AssetClass.OPTION, "SPY261017C00800000", Side.SELL, OpenClose.OPEN, 1, 1.00)
    assert run_gates(naked, acct)["code"] == "BOOK_001"
    acct.positions["SPY"] = Position("SPY", 100, 760)
    assert run_gates(naked, acct)["decision"] == ALLOW  # covered
    close_nothing = Order(AssetClass.OPTION, "SPY261017P00700000", Side.BUY, OpenClose.CLOSE, 1, 1.00)
    assert run_gates(close_nothing, acct)["code"] == "BOOK_001"


def test_sys_gate_requires_spot_when_asked():
    r = run_gates(csp(), Account(cash=1_000_000), {"require_spot": True, "spot": {}})
    assert r["code"] == "SYS_001"
    assert run_gates(csp(), Account(cash=1_000_000), {"require_spot": True, "spot": {"SPY": 769.6}})["decision"] == ALLOW


def test_chain_is_fail_closed_first_deny_stops():
    r = GateChain().run(csp(qty=0, limit=None), Account(cash=0))
    assert r["code"] == "SIZE_001" and len(r["steps"]) == 3
