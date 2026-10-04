# omega

Order engine for the QS desk. Shape borrowed from NautilusTrader: a book builds an
`Order`, the `GateChain` risk-checks it, an `ExecutionClient` sends it. One client per
venue. Paper is the only client in phase A and it works end to end.

- `types.py`    one `Order` for equity / option / crypto / future; `Fill`, `Position`, `Account`
- `risk.py`     `GateChain`: fail-closed `ALLOW | DENY | MODIFY` with stable codes and evidence
- `round_price.py` option tick rules (penny names vs nickel/dime)
- `books.py`    `CreditPut`, `DebitCall` (Freqtrade-shaped: build the entry order, never send)
- `execution.py` `ExecutionClient` protocol + `PaperExecutionClient`

Books never import a broker SDK. Library only; the operator door is `python -m qs`.

```python
from omega import Account, CreditPut, PaperExecutionClient, run_gates
acct = Account(cash=50_000)
order = CreditPut().entry(underlying="SPY", strike=700, expiry="2026-10-17", limit=2.10)
verdict = run_gates(order, acct, market={"spot": {"SPY": 769.6}})
if verdict["decision"] == "ALLOW":
    fill = PaperExecutionClient().submit_order(verdict["order"], acct)
```

Gate codes in phase A: `SYS_001` data present, `KILL_001` halt flag, `SIZE_001` qty
bounds, `LIMIT_001` limit required, `CASH_001` buying power, `BOOK_001` strategy compat.
