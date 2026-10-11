"""The IBKR bridge: planning and order flow, with a fake TWS (no network)."""

import unittest
from types import SimpleNamespace as NS

import ibkr_bridge as bridge


def payload():
    """A tiny dashboard file: one agent holding AAPL, buying NESN.SW."""
    return {
        "last": "2026-10-09",
        "currencies": {"AAPL": "USD", "NESN.SW": "CHF", "SAP.DE": "EUR",
                       "MSFT": "USD"},
        "prices": {"AAPL": [["2026-10-09", 200.0]],
                   "NESN.SW": [["2026-10-09", 80.0]],
                   "SAP.DE": [["2026-10-09", 190.0]],
                   "MSFT": [["2026-10-09", 500.0]]},
        "fx": {"USD": [["2026-10-09", 0.8]], "EUR": [["2026-10-09", 0.93]]},
        "agents": [{
            "id": "trend", "name": "Trend Follower",
            "stats": {"final_equity_chf": 100_000.0},
            # 50 AAPL x 200 USD x 0.8 = 8'000 CHF = 8% of the account
            "positions": [{"ticker": "AAPL", "quantity": 50}],
            # 125 NESN x 80 CHF = 10'000 CHF = 10%
            "pending_orders": [{"ticker": "NESN.SW", "side": "BUY",
                                "quantity": 125}],
        }],
    }


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeTrade:
    def __init__(self, order, status="PreSubmitted"):
        self.order = order
        self.orderStatus = NS(status=status, filled=0, avgFillPrice=0.0)

    def isDone(self):
        return self.orderStatus.status in ("Cancelled", "Filled", "Inactive")


class FakeIB:
    """Just enough of ``ib_async.IB`` for the bridge."""

    def __init__(self, account="DU123", net_liq=1_000_000.0, base="USD",
                 positions=(), open_orders=(), unknown=()):
        self.account, self.net_liq, self.base = account, net_liq, base
        self._positions = list(positions)
        self._open = list(open_orders)
        self.unknown = set(unknown)
        self.placed, self.cancelled = [], []
        self.errorEvent = FakeEvent()
        self.next_id = 1

    def managedAccounts(self):
        return [self.account]

    def accountSummary(self, account):
        return [NS(tag="BuyingPower", value="9", currency=self.base),
                NS(tag="NetLiquidation", value=str(self.net_liq),
                   currency=self.base)]

    def positions(self, account):
        return self._positions

    def reqAllOpenOrders(self):
        return self._open

    def cancelOrder(self, order):
        self.cancelled.append(order)
        for t in self._open:
            if t.order is order:
                t.orderStatus.status = "Cancelled"

    def qualifyContracts(self, contract):
        return [None] if contract.symbol in self.unknown else [contract]

    def placeOrder(self, contract, order):
        order.orderId = self.next_id
        self.next_id += 1
        self.placed.append((contract, order))
        trade = FakeTrade(order)
        if contract.symbol == "SAP":           # pretend IBKR refuses it
            trade.orderStatus.status = "Inactive"
            for h in self.errorEvent.handlers:
                h(order.orderId, 201, "No trading permission", contract)
        return trade

    def sleep(self, secs):
        pass


api = NS(Stock=lambda symbol, exchange, currency, primaryExchange="":
         NS(symbol=symbol, exchange=exchange, currency=currency,
            primaryExchange=primaryExchange),
         MarketOrder=lambda action, qty, **kw: NS(action=action,
                                                  totalQuantity=qty, **kw))

PARAMS = {"agent": "trend", "min_trade_pct": 0.005, "order_ref": "Vanguard3"}


def position(symbol, currency, qty):
    return NS(contract=NS(symbol=symbol, currency=currency, secType="STK"),
              position=qty)


class BridgeTest(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(bridge.ib_symbol("NESN.SW"), ("NESN", "CHF", "EBS"))
        self.assertEqual(bridge.ib_symbol("ASML.AS"), ("ASML", "EUR", "AEB"))
        self.assertEqual(bridge.ib_symbol("BRK-B"), ("BRK B", "USD", ""))
        self.assertEqual(bridge.universe_index()[("MC", "EUR")], "MC.PA")

    def test_weights_include_pending_orders(self):
        _, w = bridge.agent_weights(payload(), "trend")
        self.assertAlmostEqual(w["AAPL"], 0.08)
        self.assertAlmostEqual(w["NESN.SW"], 0.10)
        self.assertEqual(bridge.agent_weights(payload(), "nobody"), (None, {}))

    def test_plan_scales_to_the_account_and_its_currency(self):
        _, w = bridge.agent_weights(payload(), "trend")
        # 1'000'000 USD account: 8% = 80'000 USD = 400 AAPL at 200 USD;
        # 10% = 100'000 USD = 80'000 CHF = 1000 NESN at 80 CHF.
        plan = bridge.plan_orders(w, {}, 1_000_000, "USD", payload(), 0.005)
        got = {o["ticker"]: (o["side"], o["quantity"]) for o in plan}
        self.assertEqual(got, {"AAPL": ("BUY", 400), "NESN.SW": ("BUY", 1000)})
        chf = bridge.plan_orders(w, {}, 100_000, "CHF", payload(), 0.005)
        self.assertEqual({o["ticker"]: o["quantity"] for o in chf},
                         {"AAPL": 50, "NESN.SW": 125})

    def test_plan_sells_exits_first_and_skips_small_changes(self):
        _, w = bridge.agent_weights(payload(), "trend")
        held = {"AAPL": 398, "MSFT": 1}            # AAPL off by 2 shares
        plan = bridge.plan_orders(w, held, 1_000_000, "USD", payload(), 0.005)
        self.assertEqual([(o["ticker"], o["side"]) for o in plan],
                         [("MSFT", "SELL"), ("NESN.SW", "BUY")])

    def test_dry_run_sends_nothing(self):
        ib = FakeIB()
        out = bridge.run(ib, api, payload(), PARAMS, send=False,
                         say=lambda *_: None)
        self.assertEqual(out["status"], "dry run")
        self.assertEqual(ib.placed, [])

    def test_send_places_orders_and_reports_refusals(self):
        _, w = bridge.agent_weights(payload(), "trend")
        p = payload()
        p["agents"][0]["pending_orders"].append(
            {"ticker": "SAP.DE", "side": "BUY", "quantity": 50})
        old = FakeTrade(NS(orderRef="Vanguard3", orderId=99))
        manual = FakeTrade(NS(orderRef="", orderId=98))
        ib = FakeIB(positions=[position("AAPL", "USD", 400),
                               position("XYZ", "USD", 7)],
                    open_orders=[old, manual])
        out = bridge.run(ib, api, p, PARAMS, send=True, say=lambda *_: None)
        self.assertEqual(ib.cancelled, [old.order])      # only its own
        sent = {c.symbol: (o.action, o.totalQuantity, o.tif, o.orderRef)
                for c, o in ib.placed}
        self.assertEqual(sent["NESN"], ("BUY", 1000, "DAY", "Vanguard3"))
        self.assertNotIn("AAPL", sent)                   # already right
        self.assertNotIn("XYZ", sent)                    # not on watchlist
        sap = next(s for s in out["sent"] if s["ticker"] == "SAP.DE")
        self.assertIn("No trading permission", sap["note"])

    def test_unknown_market_is_skipped(self):
        ib = FakeIB(unknown={"NESN"})
        out = bridge.run(ib, api, payload(), PARAMS, send=True,
                         say=lambda *_: None)
        self.assertEqual([c.symbol for c, _ in ib.placed], ["AAPL"])
        self.assertIn({"ticker": "NESN.SW", "status": "unknown market"},
                      [{k: s[k] for k in ("ticker", "status")}
                       for s in out["sent"]])

    def test_refuses_live_accounts(self):
        with self.assertRaises(SystemExit):
            bridge.run(FakeIB(account="U123"), api, payload(), PARAMS,
                       send=True, say=lambda *_: None)

    def test_missing_agent_does_nothing(self):
        ib = FakeIB()
        out = bridge.run(ib, api, payload(), {**PARAMS, "agent": "manager"},
                         send=True, say=lambda *_: None)
        self.assertEqual(out["status"], "no agent")
        self.assertEqual(ib.placed, [])


if __name__ == "__main__":
    unittest.main()
