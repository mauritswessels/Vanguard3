"""The IBKR bridge: planning and order flow, with a fake TWS (no network)."""

import contextlib
import importlib.util
import io
import json
import ssl
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

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
        gross = sum(abs(p.position) for p in self._positions) * 100.0
        return [NS(tag="BuyingPower", value="9", currency=self.base),
                NS(tag="NetLiquidation", value=str(self.net_liq),
                   currency=self.base),
                NS(tag="GrossPositionValue", value=str(gross),
                   currency=self.base)]

    def reqPositions(self):
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


def position(symbol, currency, qty, account="DU123"):
    return NS(contract=NS(symbol=symbol, currency=currency, secType="STK"),
              position=qty, account=account)


def setUpModule():
    """Each test's logs (earlier runs, refused funds) go to a temporary
    folder, never to the real ibkr_logs/."""
    global LOGS
    LOGS = Path(tempfile.mkdtemp())
    PARAMS.update(log_dir=LOGS, blocked_file=LOGS / "blocked.json")


def tearDownModule():
    import shutil
    shutil.rmtree(LOGS, ignore_errors=True)


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
        said = []
        out = bridge.run(ib, api, p, PARAMS, send=True, say=said.append)
        self.assertEqual(ib.cancelled, [old.order])      # only its own
        sent = {c.symbol: (o.action, o.totalQuantity, o.tif, o.orderRef)
                for c, o in ib.placed}
        self.assertEqual(sent["NESN"], ("BUY", 1000, "DAY", "Vanguard3"))
        self.assertNotIn("AAPL", sent)                   # already right
        self.assertNotIn("XYZ", sent)                    # not on watchlist
        sap = next(s for s in out["sent"] if s["ticker"] == "SAP.DE")
        self.assertIn("No trading permission", sap["note"])
        self.assertEqual(said[-1], "Done: 1 of 2 orders placed; "
                                   "not accepted: SAP.DE.")

    def test_nothing_to_do(self):
        ib = FakeIB(positions=[position("AAPL", "USD", 400),
                               position("NESN", "CHF", 1000)])
        said = []
        bridge.run(ib, api, payload(), PARAMS, send=True, say=said.append)
        self.assertEqual(ib.placed, [])
        self.assertEqual(said[-1], "Done: no orders needed.")

    def test_unknown_market_is_skipped(self):
        ib = FakeIB(unknown={"NESN"})
        said = []
        out = bridge.run(ib, api, payload(), PARAMS, send=True,
                         say=said.append)
        self.assertEqual([c.symbol for c, _ in ib.placed], ["AAPL"])
        self.assertEqual(said[-1], "Done: 1 of 2 orders placed; "
                                   "not accepted: NESN.SW.")
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


class SafetyTest(unittest.TestCase):
    """Checks that stop the bridge from sending wrong orders."""

    def params(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        return {**PARAMS, "log_dir": tmp, "blocked_file": tmp / "blocked.json"}

    def test_only_the_newest_waiting_order_counts(self):
        p = payload()
        order = {"ticker": "NESN.SW", "side": "BUY", "quantity": 125}
        p["agents"][0]["pending_orders"] = [order, dict(order), dict(order)]
        _, w = bridge.agent_weights(p, "trend")
        self.assertAlmostEqual(w["NESN.SW"], 0.10)

    def test_targets_above_the_account_send_nothing(self):
        p = payload()
        p["agents"][0]["stats"]["final_equity_chf"] = 10_000.0   # wrong
        ib, said = FakeIB(), []
        with self.assertRaises(SystemExit) as ctx:
            bridge.run(ib, api, p, self.params(), send=True, say=said.append)
        self.assertEqual(ctx.exception.code, bridge.REFUSED)
        self.assertEqual(ib.placed, [])
        self.assertIn("add up to 180% of its account", said[-1])

    def test_an_empty_position_list_sends_nothing(self):
        """Just after a restart IB Gateway may list no positions yet while
        the account holds some: buying everything again must not happen."""
        ib, said = FakeIB(), []
        ib.accountSummary = lambda account: [
            NS(tag="NetLiquidation", value="1000000", currency="USD"),
            NS(tag="GrossPositionValue", value="600000", currency="USD")]
        with self.assertRaises(SystemExit) as ctx:
            bridge.run(ib, api, payload(), self.params(), send=True,
                       say=said.append)
        self.assertEqual(ctx.exception.code, bridge.REFUSED)
        self.assertEqual(ib.placed, [])
        self.assertIn("listed none", said[-1])

    def test_positions_of_other_accounts_are_ignored(self):
        ib = FakeIB(positions=[position("AAPL", "USD", 400),
                               position("NESN", "CHF", 1000, "DU999")])
        out = bridge.run(ib, api, payload(), self.params(), send=False,
                         say=lambda *_: None)
        self.assertEqual([(o["ticker"], o["quantity"]) for o in out["plan"]],
                         [("NESN.SW", 1000)])

    def test_a_fund_ibkr_does_not_sell_here_stays_in_cash(self):
        params = self.params()
        p = payload()
        p["agents"][0]["pending_orders"].append(
            {"ticker": "SAP.DE", "side": "BUY", "quantity": 50})
        ib = FakeIB(positions=[position("AAPL", "USD", 400),
                               position("NESN", "CHF", 1000)])
        refusal = ("Order rejected: no KID (key information document) "
                   "is available for this product")
        ib.placeOrder = self.refusing(ib, refusal)
        said = []
        out = bridge.run(ib, api, p, params, send=True, say=said.append)
        self.assertEqual(out["kept_in_cash"], ["SAP.DE"])
        self.assertIn("kept in cash: SAP.DE", said[-1])
        self.assertIn("SAP.DE", json.loads(params["blocked_file"].read_text()))
        # The next morning it is not sent again.
        ib2 = FakeIB(positions=[position("AAPL", "USD", 400),
                                position("NESN", "CHF", 1000)])
        said = []
        out = bridge.run(ib2, api, p, params, send=True, say=said.append)
        self.assertEqual(ib2.placed, [])
        self.assertEqual(said[-1], "Done: no orders needed; kept in cash: "
                                   "SAP.DE (IBKR does not sell these to "
                                   "this account).")

    @staticmethod
    def refusing(ib, message):
        def place(contract, order):
            order.orderId = 7
            ib.placed.append((contract, order))
            trade = FakeTrade(order, status="Inactive")
            for h in ib.errorEvent.handlers:
                h(order.orderId, 201, message, contract)
            return trade
        return place

    def test_says_when_yesterdays_orders_did_not_fill(self):
        params = self.params()
        (params["log_dir"] / "2026-10-12.json").write_text(json.dumps([{
            "status": "sent",
            "sent": [{"ticker": "NESN.SW", "side": "BUY", "quantity": 1000,
                      "note": "waiting for the market to open"},
                     {"ticker": "AAPL", "side": "BUY", "quantity": 400,
                      "note": "waiting for the market to open"}]}]))
        ib, said = FakeIB(positions=[position("AAPL", "USD", 400)]), []
        out = bridge.run(ib, api, payload(), params, send=True,
                         say=said.append, today=date(2026, 10, 13))
        self.assertEqual(out["not_filled"], ["NESN.SW"])
        self.assertIn("Warning: the orders for NESN.SW sent on 2026-10-12 "
                      "did not fill", "\n".join(said))

    def test_old_results_are_flagged(self):
        p = payload()                                  # Fri 9 Oct
        self.assertIsNone(bridge.stale_warning(p, date(2026, 10, 12)))  # Mon
        self.assertIsNone(bridge.stale_warning(p, date(2026, 10, 10)))
        warning = bridge.stale_warning(p, date(2026, 10, 13))            # Tue
        self.assertTrue(warning.startswith("Warning: the newest results are "
                                           "from Fri 09 Oct, not Mon 12 Oct"))

    def test_a_warning_from_ibkr_is_not_a_refusal(self):
        trade = FakeTrade(NS(orderId=1), status="ValidationError")
        self.assertEqual(bridge.status_text(trade, ["will not be placed at "
                                                    "the exchange until "
                                                    "09:30 (code 399)"]),
                         "waiting for the market to open")


class ConnectHelpTest(unittest.TestCase):
    def test_says_what_to_check_for_each_app(self):
        tws = bridge.not_reachable(7497, ConnectionRefusedError("refused"))
        self.assertIn("Could not reach TWS on port 7497 (refused)", tws)
        self.assertIn("Enable ActiveX", tws.splitlines()[-1])
        gateway = bridge.not_reachable(4002, TimeoutError())
        self.assertIn("IB Gateway on port 4002 (TimeoutError)", gateway)
        self.assertIn("docker logs", gateway.splitlines()[-1])


class SilenceTest(unittest.TestCase):
    def test_says_it_is_probably_logged_out(self):
        gateway = bridge.not_answering(4002, 60)
        self.assertEqual(len(gateway.splitlines()), 1)
        self.assertIn("IB Gateway stopped answering for 60 seconds", gateway)
        self.assertIn("logged out", gateway)
        self.assertIn("still logged in", bridge.not_answering(7497, 60))

    @unittest.skipUnless(hasattr(bridge.signal, "SIGALRM"), "needs alarms")
    def test_time_limit_stops_a_stuck_run(self):
        import time
        with self.assertRaises(TimeoutError):
            with bridge.time_limit(1):
                time.sleep(5)
        with bridge.time_limit(1):        # a quick block is left alone
            pass
        time.sleep(1.2)                   # and the alarm was switched off

    def test_a_silent_app_ends_the_run(self):
        """The real ``main``: connected, then the app never answers."""
        ib = FakeIB()
        ib.connect = lambda *a, **kw: None
        ib.disconnect = mock.Mock()

        def silent():
            raise TimeoutError
        ib.reqAllOpenOrders = silent
        fake_api = NS(IB=lambda: ib, Stock=api.Stock,
                      MarketOrder=api.MarketOrder)
        with mock.patch.dict("sys.modules", {"ib_async": fake_api}), \
                mock.patch.object(bridge, "load_results",
                                  lambda _: {**payload(), "last": str(
                                      bridge.date.today())}), \
                mock.patch("sys.argv", ["ibkr_bridge.py", "--send",
                                        "--agent", "trend", "--port", "4002"]):
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(io.StringIO()):
                bridge.main()
        self.assertIn("IB Gateway stopped answering", str(ctx.exception))
        self.assertEqual(ib.RequestTimeout, 60)
        ib.disconnect.assert_called_once()


class DownloadTest(unittest.TestCase):
    def failure(self, error):
        """What the bridge says when the download fails with ``error``."""
        def urlopen(*args, **kwargs):
            raise error
        with mock.patch.object(bridge.urllib.request, "urlopen", urlopen):
            with self.assertRaises(SystemExit) as ctx:
                bridge.load_results("https://example.com/paper.json")
        return str(ctx.exception)

    def test_certificate_problem_is_explained(self):
        text = self.failure(urllib.error.URLError(ssl.SSLCertVerificationError(
            1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")))
        self.assertIn("security certificate", text)
        self.assertIn("pip install -r requirements-ibkr.txt", text)

    def test_other_problems_name_the_cause(self):
        text = self.failure(urllib.error.URLError(
            OSError("nodename nor servname provided")))
        self.assertIn("(nodename nor servname provided)", text)
        self.assertIn("internet connection", text)
        text = self.failure(urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None))
        self.assertIn("(HTTP Error 404: Not Found)", text)
        self.assertIn("read timed out", self.failure(
            TimeoutError("read timed out")))

    def test_local_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            path.write_text(json.dumps(payload()))
            self.assertEqual(bridge.load_results(str(path))["last"],
                             "2026-10-09")

    @unittest.skipUnless(importlib.util.find_spec("certifi"), "needs certifi")
    def test_brings_its_own_certificates(self):
        # Like Python from python.org on a Mac: no certificates of its own.
        def bare():
            return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with mock.patch.object(bridge.ssl, "create_default_context", bare):
            stats = bridge.https_context().cert_store_stats()
        self.assertGreater(stats["x509_ca"], 0)


if __name__ == "__main__":
    unittest.main()
