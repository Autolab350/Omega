import pytest

from omega import Account, CreditPut, DebitCall, Order, PaperExecutionClient, Shares, get_book, get_client, run_gates
from omega.types import AssetClass, OpenClose, Side


def test_paper_fill_books_credit_and_reserve():
    acct = Account(cash=80_000)
    o = CreditPut().entry(underlying="SPY", strike=700, expiry="2026-10-17", limit=2.10)
    r = run_gates(o, acct)
    assert r["decision"] == "ALLOW"
    fill = PaperExecutionClient().submit_order(Order.from_dict(r["order"]), acct)
    assert fill.price == 2.10 and fill.qty == 1
    assert acct.cash == 80_210.0
    assert acct.reserved == 70_000.0
    assert acct.buying_power == 10_210.0
    assert acct.positions[o.symbol].qty == -1 and acct.positions[o.symbol].avg == 2.10


def test_close_releases_reserve_and_flattens():
    acct = Account(cash=80_000)
    book = CreditPut()
    o = book.entry(underlying="SPY", strike=700, expiry="2026-10-17", limit=2.00)
    px = PaperExecutionClient()
    px.submit_order(o, acct)
    close = book.exit(acct.positions[o.symbol], limit=1.00)
    assert run_gates(close, acct)["decision"] == "ALLOW"
    px.submit_order(close, acct)
    assert acct.reserved == 0.0
    assert acct.cash == 80_100.0  # +200 credit, -100 to close
    assert o.symbol not in acct.to_dict()["positions"]


def test_debit_call_fill_and_average_on_add():
    acct = Account(cash=1_000)
    book = DebitCall()
    px = PaperExecutionClient()
    o1 = book.entry(underlying="QQQ", strike=756, expiry="2026-10-02", limit=0.42)
    o2 = book.entry(underlying="QQQ", strike=756, expiry="2026-10-02", limit=0.40)
    px.submit_order(o1, acct)
    px.submit_order(o2, acct)
    pos = acct.positions[o1.symbol]
    assert pos.qty == 2 and pos.avg == 0.41
    assert acct.cash == 1_000 - 42 - 40


def test_shares_and_crypto_use_same_order():
    acct = Account(cash=10_000)
    px = PaperExecutionClient()
    eq = Shares().entry(symbol="AAPL", side="buy", qty=10, limit=200.0)
    assert run_gates(eq, acct)["decision"] == "ALLOW"
    px.submit_order(eq, acct)
    assert acct.cash == 8_000.0 and acct.positions["AAPL"].qty == 10
    btc = Shares().entry(symbol="BTC-USD", side="buy", qty=0.01, limit=None, asset_class="crypto")
    assert run_gates(btc, acct)["decision"] == "ALLOW"  # crypto: fractional ok, limit optional
    px.submit_order(btc, acct, mark=84_850.0)
    assert acct.positions["BTC-USD"].qty == 0.01


def test_cancel_and_registries():
    px = PaperExecutionClient()
    assert px.cancel_order("nope") is False
    assert isinstance(get_client("paper"), PaperExecutionClient)
    assert isinstance(get_book("credit_put"), CreditPut)
    with pytest.raises(KeyError):
        get_client("alpaca")


def test_paper_rejects_wrong_venue():
    o = Order(AssetClass.EQUITY, "SPY", Side.BUY, OpenClose.OPEN, 1, 100.0, venue="alpaca")
    with pytest.raises(ValueError):
        PaperExecutionClient().submit_order(o, Account(cash=1_000))
