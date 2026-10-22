"""Dividends and share splits in live paper trading."""

import unittest

import pandas as pd

import config
from data_manager import corporate_actions, load_market_data
from engine import journal
from engine.portfolio import Portfolio
from engine.simulator import Simulator, build_accounts
from engine.broker import Order
from models import make_agent

D = [pd.Timestamp(x) for x in ("2026-10-05", "2026-10-06", "2026-10-07",
                               "2026-10-08", "2026-10-09")]


class PortfolioTest(unittest.TestCase):

    def test_a_dividend_is_paid_after_foreign_tax(self):
        pf = Portfolio("t", 100_000)
        pf.buy(D[0], "KO", "USD", 100, 60.0, 0.8)
        cash = pf.cash
        event = pf.receive_dividend(D[1], "KO", 0.5, 0.8, tax=0.15)
        paid = 100 * 0.5 * 0.8 * (1 - 2e-4) * 0.85
        self.assertAlmostEqual(pf.cash - cash, paid)
        self.assertAlmostEqual(event["chf"], paid)
        self.assertAlmostEqual(pf.performance()["dividends_chf"], paid)
        self.assertIsNone(pf.receive_dividend(D[1], "PEP", 1.0, 0.8))
        again = Portfolio.from_dict(pf.to_dict())
        self.assertEqual(again.events, pf.events)

    def test_a_split_keeps_the_cost(self):
        pf = Portfolio("t", 100_000)
        pf.buy(D[0], "NVDA", "USD", 10, 800.0, 0.8)
        cost = pf.positions["NVDA"].cost_basis_chf
        pf.split(D[1], "NVDA", 4.0, 160.0)
        self.assertEqual(pf.quantity("NVDA"), 40)
        self.assertAlmostEqual(pf.positions["NVDA"].cost_basis_chf, cost)

    def test_a_reverse_split_pays_out_the_fraction(self):
        pf = Portfolio("t", 100_000)
        pf.buy(D[0], "X", "USD", 15, 10.0, 1.0)
        cost, cash = pf.positions["X"].cost_basis_chf, pf.cash
        event = pf.split(D[1], "X", 0.1, 100.0)
        self.assertEqual(pf.quantity("X"), 1)
        self.assertAlmostEqual(pf.cash - cash, 50.0)       # half a new share
        self.assertAlmostEqual(pf.positions["X"].cost_basis_chf, cost / 1.5)
        self.assertEqual((event["shares_before"], event["shares"]), (15, 1))


class YahooTest(unittest.TestCase):

    def test_reads_dividends_and_splits(self):
        idx = pd.DatetimeIndex(["2026-10-05 00:00", "2026-10-06 00:00",
                                "2026-10-07 00:00"]).tz_localize("America/New_York")
        raw = pd.DataFrame({"Close": [1.0, 2.0, 3.0],
                            "Dividends": [0.0, 0.25, 0.0],
                            "Stock Splits": [0.0, 0.0, 4.0]}, index=idx)
        out = corporate_actions(raw)
        self.assertEqual(list(out.index), [D[1], D[2]])
        self.assertEqual(out.loc[D[1], "dividend"], 0.25)
        self.assertEqual(out.loc[D[2], "split"], 4.0)


class SimulatorTest(unittest.TestCase):
    """A buy-and-hold account holding SPY, on synthetic prices."""

    def setUp(self):
        self.market = load_market_data(
            "synthetic", pd.Timestamp("2025-06-01"), pd.Timestamp("2026-06-30"),
            cache_dir=None, seed=3)
        self.cal = self.market.calendar
        self.sim = Simulator(self.market, build_accounts(
            self.market, [make_agent("benchmark")]))
        self.sim.run(self.cal[-30:-20])
        self.acc = self.sim.accounts[0]
        self.qty = self.acc.portfolio.quantity("SPY")
        self.assertGreater(self.qty, 0)

    def dividend(self, day, amount=1.5):
        self.market.actions["SPY"] = pd.DataFrame(
            {"dividend": [amount], "split": [0.0]}, index=[day])

    def test_paper_trading_pays_dividends(self):
        day = self.cal[-19]
        self.dividend(day)
        self.sim.corporate_actions = True
        cash = self.acc.portfolio.cash
        self.sim.step(day)
        paid = (self.qty * 1.5 * self.market.fx_rate("SPY", day)
                * (1 - 2e-4) * (1 - config.DIVIDEND_TAX["USD"]))
        self.assertAlmostEqual(self.acc.portfolio.cash - cash, paid, places=6)
        entry = self.acc.activity[-1]
        self.assertEqual(entry["date"], day.strftime("%Y-%m-%d"))
        self.assertEqual(entry["corporate"][0]["kind"], "dividend")
        # Paid once: the next session pays nothing more.
        cash = self.acc.portfolio.cash
        self.sim.step(self.cal[-18])
        self.assertAlmostEqual(self.acc.portfolio.cash, cash)

    def test_the_dividend_goes_to_the_shares_held_at_the_last_close(self):
        # The midday check trades on the day itself: a share bought on the
        # day it goes ex-dividend earns nothing, a share sold that day does.
        day = self.cal[-19]
        self.dividend(day)
        self.sim.corporate_actions = True
        pf = self.acc.portfolio
        fx = self.market.fx_rate("SPY", day)
        per_share = 1.5 * fx * (1 - 2e-4) * (1 - config.DIVIDEND_TAX["USD"])
        pf.sell(day, "SPY", self.qty, 400.0, fx)          # all of it, midday
        pf.buy(day, "SPY", "USD", 5, 400.0, fx)           # and 5 back
        cash = pf.cash
        self.acc.agent.calculate_signals = lambda *a: []  # no new orders
        self.sim.step(day)
        self.assertAlmostEqual(pf.cash - cash, self.qty * per_share, places=6)
        event = next(e for e in pf.events if e["kind"] == "dividend")
        self.assertEqual(event["shares"], self.qty)

    def test_a_backtest_pays_none(self):
        """Backtest prices already include dividends."""
        day = self.cal[-19]
        self.dividend(day)
        cash = self.acc.portfolio.cash
        self.sim.step(day)
        self.assertAlmostEqual(self.acc.portfolio.cash, cash)

    def test_splits_are_applied_before_the_new_sessions(self):
        day = self.cal[-18]
        self.market.actions["SPY"] = pd.DataFrame(
            {"dividend": [0.0], "split": [4.0]}, index=[day])
        self.acc.broker.submit(Order("SPY", "SELL", 3, self.cal[-20]))
        done = self.sim.apply_splits()
        self.assertEqual(done, [{"ticker": "SPY", "ratio": 4.0,
                                 "date": day.strftime("%Y-%m-%d")}])
        self.assertEqual(self.acc.portfolio.quantity("SPY"), 4 * self.qty)
        self.assertEqual(self.acc.broker.pending[0].quantity, 12)
        self.sim.corporate_actions = True
        self.sim.run(self.cal[-19:-17])
        split_days = [e["date"] for e in self.acc.activity
                      if any(c["kind"] == "split" for c in e.get("corporate", []))]
        self.assertEqual(split_days, [day.strftime("%Y-%m-%d")])
        # Not applied twice by the next run.
        self.assertEqual(self.sim.apply_splits(), [])

    def test_volatility_stops_follow_a_split(self):
        agent = make_agent("volatility")
        agent.stops = {"NVDA": 400.0}
        agent.on_split("NVDA", 4.0)
        self.assertEqual(agent.stops, {"NVDA": 100.0})

    def test_the_learners_remember_the_close_in_post_split_shares(self):
        # Else a 4-for-1 split is learned as a 75% loss overnight.
        for key in ("learner", "learner_opus"):
            agent = make_agent(key)
            agent.memory = {"NVDA": {"close": 800.0}, "SPY": {"close": 500.0}}
            agent.on_split("NVDA", 4.0)
            self.assertEqual(agent.memory["NVDA"]["close"], 200.0)
            self.assertEqual(agent.memory["SPY"]["close"], 500.0)
            agent.on_split("AAPL", 2.0)           # not in memory: no change


class JournalTest(unittest.TestCase):

    def test_a_position_through_a_split_is_one_trip(self):
        pf = Portfolio("t", 100_000)
        pf.buy(D[0], "NVDA", "USD", 10, 800.0, 0.8, "breakout", decided=D[0])
        pf.split(D[1], "NVDA", 4.0, 160.0)
        pf.sell(D[2], "NVDA", 20, 205.0, 0.8, "trim", decided=D[1])
        prices = pd.Series({"NVDA": 205.0 * 0.8})
        for d in D[:3]:
            pf.mark_to_market(d, prices)
        rows = journal.fills(pf, [])
        trips = journal.round_trips(
            rows, pf.equity_curve, pf.positions, prices, 100_000, D[2],
            [e for e in pf.events if e["kind"] == "split"])
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual((trip["status"], trip["quantity"]), ("open", 40))
        self.assertAlmostEqual(trip["entry_price"], 800.0 * (1 + 5e-4) / 4)
        gain = pf.cash + 20 * prices["NVDA"] - 100_000
        self.assertAlmostEqual(trip["pnl_chf"], gain, places=6)


if __name__ == "__main__":
    unittest.main()
