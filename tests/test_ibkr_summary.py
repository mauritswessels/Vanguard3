"""The paper account's summary for the website: values, tracking, orders,
and that nothing personal ever goes into the public file (no network)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import ibkr_bridge as bridge
import ibkr_summary as summary
from tests.test_ibkr_bridge import FakeIB, api, position

ACCOUNT = "DU7654321"
NOW = datetime(2026, 10, 13, 6, 31, tzinfo=timezone.utc)


def payload(last="2026-10-12", equity=100_000.0):
    """Results of one close: the Team Manager holds 50 AAPL (8'000 CHF)
    and buys 125 NESN at the next open."""
    return {
        "last": last,
        "currencies": {"AAPL": "USD", "NESN.SW": "CHF", "SAP.DE": "EUR",
                       "SPY": "USD"},
        "prices": {"AAPL": [[last, 200.0]], "NESN.SW": [[last, 80.0]],
                   "SAP.DE": [[last, 190.0]], "SPY": [[last, 600.0]]},
        "fx": {"USD": [[last, 0.8]], "EUR": [[last, 0.93]]},
        "stand_ins": {"SPY": {"symbol": "CSPX", "exchange": "LSEETF",
                              "currency": "USD", "price": 750.0,
                              "date": last}},
        "agents": [{
            "id": "manager", "name": "Team Manager",
            "stats": {"final_equity_chf": equity},
            "cash_chf": equity - 8_000.0,
            "positions": [{"ticker": "AAPL", "quantity": 50,
                           "value_chf": 8_000.0}],
            "pending_orders": [{"ticker": "NESN.SW", "side": "BUY",
                                "quantity": 125}],
        }],
    }


def run_log(**extra):
    """A morning run's log, as ``ibkr_bridge.run`` writes it."""
    run = {"status": "sent", "account": ACCOUNT, "base": "USD",
           "net_liq": 1_000_000.0, "gross": 100_000.0, "positions": 2,
           "held": {"AAPL": 400, "SPY": 0}, "agent": "manager",
           "results_of": "2026-10-12",
           "plan": [{"ticker": "NESN.SW", "side": "BUY", "quantity": 1000,
                     "now": 0, "target": 1000, "value": 100_000.0}],
           "sent": [{"ticker": "NESN.SW", "side": "BUY", "quantity": 1000,
                     "now": 0, "target": 1000, "value": 100_000.0,
                     "status": "PreSubmitted",
                     "note": "waiting for the market to open"}],
           "kept_in_cash": [], "no_price": [], "currency": []}
    run.update(extra)
    return run


def add(old, run, day, results=None, since=None, before=None, **kw):
    return summary.update(old, run, results or payload(), day, since,
                          before or {}, now=NOW, **kw)


class ValueTest(unittest.TestCase):
    def test_both_accounts_at_the_same_close(self):
        out = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        latest = out["latest"]
        self.assertEqual((latest["date"], latest["results_of"]),
                         ("2026-10-13", "2026-10-12"))
        self.assertTrue(latest["same_close"])
        # 1'000'000 USD at 0.8 CHF; 100'000 USD in positions.
        self.assertEqual(latest["real"], {
            "value": 1_000_000.0, "currency": "USD", "value_chf": 800_000.0,
            "cash": 900_000.0, "cash_chf": 720_000.0, "invested": 0.1,
            "positions": 2, "watchlist_positions": 2})
        self.assertEqual(latest["sim"], {"value_chf": 100_000.0,
                                         "cash_chf": 92_000.0,
                                         "invested": 0.08, "positions": 1})
        self.assertEqual(out["agent_name"], "Team Manager")
        self.assertEqual(out["account_currency"], "USD")
        self.assertIn("Team Manager", out["about"])

    def test_weights_side_by_side(self):
        out = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        # 400 AAPL x 200 USD x 0.8 = 64'000 CHF of 800'000 = 8%.
        aapl, = out["latest"]["weights"]
        self.assertEqual(aapl, {"ticker": "AAPL", "holds_as": None,
                                "sim": 0.08, "real": 0.08,
                                "difference": 0.0})
        self.assertEqual(out["latest"]["tracking"]["holdings_gap"], 0.0)

    def test_a_us_fund_is_valued_as_what_ibkr_holds(self):
        run = run_log(held={"AAPL": 400, "SPY": 100})
        out = add(summary.empty("manager"), run, date(2026, 10, 13))
        spy = next(w for w in out["latest"]["weights"]
                   if w["ticker"] == "SPY")
        # 100 CSPX x 750 USD x 0.8 = 60'000 CHF = 7.5%, none in the sim.
        self.assertEqual((spy["holds_as"], spy["real"], spy["sim"]),
                         ("CSPX", 0.075, 0.0))
        self.assertEqual(out["latest"]["tracking"]["holdings_gap"], 0.0375)

    def test_returns_follow_the_simulation_day_by_day(self):
        first = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        self.assertEqual(first["since"], "2026-10-13")
        row = first["history"][0]
        self.assertEqual((row["return"], row["return_total"]), (None, 0.0))
        # Next close: the account gains 2% in francs, the simulation 1%.
        second = add(first, run_log(net_liq=1_020_000.0,
                                    results_of="2026-10-13"),
                     date(2026, 10, 14),
                     results=payload("2026-10-13", 101_000.0))
        row = second["history"][-1]
        self.assertEqual((row["return"], row["sim_return"]), (0.02, 0.01))
        self.assertEqual(row["difference"], 0.01)
        third = add(second, run_log(net_liq=1_020_000.0,
                                    results_of="2026-10-14"),
                    date(2026, 10, 15),
                    results=payload("2026-10-14", 101_000.0))
        track = third["latest"]["tracking"]
        self.assertEqual((track["return_total"], track["sim_return_total"]),
                         (0.02, 0.01))
        self.assertEqual(track["since"], "2026-10-13")
        self.assertEqual(len(third["history"]), 3)

    def test_old_results_are_not_compared(self):
        """When the evening run failed, the account is a close ahead of
        the results: no return that day, and the next one spans both."""
        first = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        stale = add(first, run_log(net_liq=1_010_000.0), date(2026, 10, 14))
        row = stale["history"][-1]
        self.assertFalse(row["same_close"])
        self.assertIsNone(row["return"])
        self.assertIsNone(row["return_total"])
        later = add(stale, run_log(net_liq=1_030_000.0,
                                   results_of="2026-10-14"),
                    date(2026, 10, 15),
                    results=payload("2026-10-14", 102_000.0))
        row = later["history"][-1]
        self.assertEqual((row["return"], row["sim_return"]), (0.03, 0.02))

    def test_another_run_the_same_morning_replaces_the_first(self):
        first = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        again = add(first, run_log(net_liq=900_000.0), date(2026, 10, 13))
        self.assertEqual(len(again["history"]), 1)
        self.assertEqual(again["history"][0]["value"], 900_000.0)
        self.assertEqual(again["history"][0]["return_total"], 0.0)

    def test_history_is_rolling_and_totals_carry_on(self):
        out = summary.empty("manager")
        value = 1_000_000.0
        for day in range(13, 17):              # Tue 13 to Fri 16 Oct
            out = add(out, run_log(net_liq=value,
                                   results_of=f"2026-10-{day - 1}"),
                      date(2026, 10, day),
                      results=payload(f"2026-10-{day - 1}"), keep_days=2)
            value *= 1.01
        self.assertEqual([r["date"] for r in out["history"]],
                         ["2026-10-15", "2026-10-16"])
        self.assertAlmostEqual(out["history"][-1]["return_total"],
                               1.01 ** 3 - 1, places=5)
        self.assertEqual(out["since"], "2026-10-13")

    def test_tracking_error_needs_a_few_days(self):
        rows = [{"difference": d} for d in (0.01, -0.01, 0.01, -0.01)]
        self.assertIsNone(summary.tracking_error(rows))
        rows.append({"difference": 0.0})
        self.assertAlmostEqual(summary.tracking_error(rows),
                               0.01 * 252 ** 0.5, places=6)


class OrderTest(unittest.TestCase):
    def test_this_mornings_orders(self):
        run = run_log(
            sent=[{"ticker": "NESN.SW", "side": "BUY", "quantity": 1000,
                   "value": 100_000.0, "status": "PreSubmitted",
                   "note": "waiting for the market to open"},
                  {"ticker": "SAP.DE", "side": "BUY", "quantity": 50,
                   "value": 11_000.0, "status": "Inactive",
                   "note": "not accepted: No trading permission (code 201)"},
                  {"ticker": "SPY", "side": "BUY", "quantity": 3,
                   "value": 2_250.0, "status": "unknown market",
                   "note": "not accepted: unknown market"}],
            plan=[{}, {}, {}], kept_in_cash=["SAP.DE"], no_price=["IWM"],
            currency=[{"currency": "USD", "side": "BUY", "amount": 15_150,
                       "value": 15_150.0, "note": "filled at 0.80"}])
        orders = add(summary.empty("manager"), run,
                     date(2026, 10, 13))["latest"]["orders"]
        self.assertEqual((orders["planned"], orders["sent"],
                          orders["refused"]), (3, 1, 2))
        self.assertEqual([(o["ticker"], o["outcome"], o["note"])
                          for o in orders["orders"]],
                         [("NESN.SW", "sent", "waiting for the market to "
                                              "open"),
                          ("SAP.DE", "refused", "IBKR did not accept the "
                                                "order (code 201)"),
                          ("SPY", "refused", "IBKR does not know this "
                                             "market")])
        self.assertEqual(orders["orders"][2]["holds_as"], "CSPX")
        self.assertEqual(orders["currency"],
                         [{"currency": "USD", "side": "BUY",
                           "amount": 15_150, "value": 15_150.0,
                           "outcome": "sent"}])
        kept = {k["ticker"]: k["reason"] for k in orders["kept_in_cash"]}
        self.assertIn("key information document", kept["SAP.DE"])
        self.assertIn("No price", kept["IWM"])

    def test_fills_are_judged_from_the_next_mornings_holdings(self):
        buy = {"ticker": "X", "side": "BUY", "now": 10, "target": 30}
        sell = {"ticker": "X", "side": "SELL", "now": 30, "target": 0}
        self.assertEqual(summary.fill_outcome(buy, {"X": 30}), "filled")
        self.assertEqual(summary.fill_outcome(buy, {"X": 20}),
                         "partly filled")
        self.assertEqual(summary.fill_outcome(buy, {"X": 10}), "not filled")
        self.assertEqual(summary.fill_outcome(sell, {}), "filled")
        self.assertEqual(summary.fill_outcome(sell, {"X": 30}), "not filled")
        self.assertEqual(summary.fill_outcome(sell, {"X": 40}), "not filled")

    def test_yesterdays_row_learns_what_filled(self):
        first = add(summary.empty("manager"), run_log(), date(2026, 10, 13))
        self.assertIsNone(first["history"][0]["filled"])
        before = {"NESN.SW": {"side": "BUY", "quantity": 1000, "now": 0,
                              "target": 1000},
                  "AAPL": {"side": "BUY", "quantity": 100, "now": 400,
                           "target": 500}}
        second = add(first, run_log(held={"AAPL": 400, "NESN.SW": 1000},
                                    results_of="2026-10-13"),
                     date(2026, 10, 14), results=payload("2026-10-13"),
                     since="2026-10-13", before=before)
        self.assertEqual({k: second["history"][0][k] for k in
                          ("filled", "partly_filled", "not_filled")},
                         {"filled": 1, "partly_filled": 0, "not_filled": 1})
        previous = second["latest"]["previous_orders"]
        self.assertEqual(previous["date"], "2026-10-13")
        self.assertEqual([(o["ticker"], o["outcome"])
                          for o in previous["orders"]],
                         [("AAPL", "not filled"), ("NESN.SW", "filled")])
        self.assertIsNone(second["history"][1]["filled"])


class BridgeLogTest(unittest.TestCase):
    """The bridge's real run feeds the summary."""

    def test_from_a_real_run(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        params = {"agent": "manager", "min_trade_pct": 0.005,
                  "order_ref": "Vanguard3", "log_dir": tmp,
                  "blocked_file": tmp / "blocked.json"}
        ib = FakeIB(account=ACCOUNT,
                    positions=[position("AAPL", "USD", 400, ACCOUNT),
                               position("XYZ", "USD", 7, ACCOUNT)])
        result = bridge.run(ib, api, payload(), params, send=True,
                            say=lambda *_: None, today=date(2026, 10, 13))
        self.assertEqual(result["held"], {"AAPL": 400})
        self.assertEqual(result["positions"], 2)
        self.assertEqual(result["gross"], 40_700.0)
        out = add(summary.empty("manager"), result, date(2026, 10, 13))
        self.assertEqual(out["latest"]["real"]["positions"], 2)
        self.assertEqual(out["latest"]["orders"]["sent"], 1)


class PrivacyTest(unittest.TestCase):
    """The file is public: no account ID, login, password or token."""

    SECRETS = {"TWS_USERID": "paperuser77",
               "TELEGRAM_TOKEN": "123456:ABC-def_secretToken",
               "TELEGRAM_CHAT_ID": "987654321",
               "NTFY_TOPIC": "vanguard3-0a1b2c3d4e5f",
               "HEALTHCHECK_URL": "https://hc-ping.com/1111-2222-3333",
               "ANTHROPIC_API_KEY": "sk-ant-test-0123456789"}
    PASSWORD = " hunter2 is my secret "

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "server").mkdir()
        (self.root / "server" / ".env").write_text(
            f"TWS_USERID={self.SECRETS['TWS_USERID']}\n")
        (self.root / "server" / "ib_password.txt").write_text(self.PASSWORD)
        (self.root / "ibkr_morning.env").write_text(
            'BRIDGE_ARGS="--port 4002"\n'
            + "".join(f"{k}={v}\n" for k, v in self.SECRETS.items()
                      if k.startswith(("TELEGRAM", "NTFY", "HEALTH"))))
        self.enterContext(mock.patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": self.SECRETS["ANTHROPIC_API_KEY"]}))
        self.out = self.root / "ibkr_logs" / "public" / "ibkr.json"

    def private(self):
        return summary.private_values(ACCOUNT, self.root)

    def test_knows_every_secret(self):
        found = self.private()
        for value in [ACCOUNT, self.PASSWORD.strip(), *self.SECRETS.values()]:
            self.assertIn(value, found)
        self.assertNotIn("--port 4002", found)

    def test_the_file_never_shows_the_account_or_a_secret(self):
        """Even when IBKR's messages name the account, as they can."""
        leak = f"for account {ACCOUNT} by {self.SECRETS['TWS_USERID']}"
        run = run_log(
            sent=[{"ticker": "NESN.SW", "side": "BUY", "quantity": 1000,
                   "value": 100_000.0, "status": "Inactive",
                   "note": f"not accepted: Order rejected {leak} (code 201)"},
                  {"ticker": "AAPL", "side": "SELL", "quantity": 1,
                   "value": 160.0, "status": "Submitted",
                   "note": f"sent {leak}"}],
            currency=[{"currency": "USD", "side": "BUY", "amount": 10,
                       "value": 8.0, "note": f"not accepted: {leak}"}])
        first = add(summary.empty("manager"), run, date(2026, 10, 13))
        summary.write(first, self.out, self.private())
        text = self.out.read_text()
        for value in [ACCOUNT, self.PASSWORD.strip(), *self.SECRETS.values()]:
            self.assertNotIn(value, text)
        self.assertIsNone(summary.ACCOUNT_ID.search(text))
        self.assertIn("code 201", text)          # the useful part stays
        self.assertNotIn("account", json.dumps(
            json.loads(text)["latest"]["orders"]))

    def test_refuses_to_write_anything_personal(self):
        for leak in (ACCOUNT, self.SECRETS["TELEGRAM_TOKEN"],
                     self.PASSWORD.strip(), "U1234567"):
            with self.subTest(leak=leak):
                results = payload()
                results["agents"][0]["name"] = f"Copy of {leak}"
                out = add(summary.empty("manager"), run_log(),
                          date(2026, 10, 13), results=results)
                with self.assertRaises(summary.PrivateDataError) as ctx:
                    summary.write(out, self.out, self.private())
                self.assertFalse(self.out.exists())
                self.assertNotIn(leak, str(ctx.exception))

    def test_short_values_do_not_block_the_file(self):
        (self.root / "ibkr_morning.env").write_text("TELEGRAM_CHAT_ID=42\n")
        self.assertNotIn("42", summary.private_values(None, self.root))


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "ibkr.json"

    def test_where_it_is_published(self):
        env = self.root / "ibkr_morning.env"
        self.assertIsNone(summary.published_url(self.root))
        env.write_text("PUBLISH_REPO=git@github.com:me/vanguard3-ibkr-data"
                       ".git\nPUBLISH_BRANCH=ibkr-data\n")
        self.assertEqual(summary.published_url(self.root),
                         "https://raw.githubusercontent.com/me/"
                         "vanguard3-ibkr-data/ibkr-data/ibkr.json")

    def test_a_new_server_carries_on_the_published_history(self):
        (self.root / "ibkr_morning.env").write_text(
            "PUBLISH_REPO=git@github.com:me/data.git\n")
        published = add(summary.empty("manager"), run_log(),
                        date(2026, 10, 13))
        body = io.BytesIO(json.dumps(published).encode())
        with mock.patch.object(summary.urllib.request, "urlopen",
                               return_value=body) as urlopen, \
                contextlib.redirect_stdout(io.StringIO()):
            found = summary.load_summary(self.path, "manager", self.root)
        self.assertEqual(urlopen.call_args.args[0],
                         "https://raw.githubusercontent.com/me/data/"
                         "ibkr-data/ibkr.json")
        self.assertEqual(found["history"], published["history"])

    def test_starts_fresh_without_one(self):
        self.assertEqual(summary.load_summary(self.path, "manager",
                                              self.root),
                         summary.empty("manager"))
        self.path.write_text(json.dumps({"schema": 1, "agent": "trend",
                                         "history": [{}]}))
        self.assertEqual(summary.load_summary(self.path, "manager",
                                              self.root)["history"], [])


class MainTest(unittest.TestCase):
    def setUp(self):
        self.logs = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out = self.logs / "public" / "ibkr.json"
        self.today = date.today()
        self.run = run_log(results_of="2026-10-12")
        (self.logs / f"{self.today:%Y-%m-%d}.json").write_text(json.dumps(
            [self.run, {**self.run, "status": "dry run", "net_liq": 1.0}]))
        self.enterContext(mock.patch.object(bridge, "LOG_DIR", self.logs))

    def main(self, results):
        with mock.patch.object(bridge, "load_results",
                               lambda _: results), \
                mock.patch.object(summary, "ROOT", self.logs), \
                mock.patch("sys.argv", ["ibkr_summary.py", "--out",
                                        str(self.out)]), \
                contextlib.redirect_stdout(io.StringIO()) as said:
            summary.main()
        return said.getvalue()

    def test_writes_the_file(self):
        said = self.main(payload())
        out = json.loads(self.out.read_text())
        self.assertEqual(out["latest"]["real"]["value"], 1_000_000.0)
        self.assertIn("Summary for the website saved", said)
        self.assertNotIn(ACCOUNT, self.out.read_text())

    def test_results_that_changed_since_the_run(self):
        with self.assertRaises(SystemExit) as ctx:
            self.main(payload(last="2026-10-13"))
        self.assertIn("not of 2026-10-12", str(ctx.exception))
        self.assertFalse(self.out.exists())

    def test_no_run_today(self):
        (self.logs / f"{self.today:%Y-%m-%d}.json").unlink()
        with self.assertRaises(SystemExit) as ctx:
            self.main(payload())
        self.assertIn("nothing new", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
