"""Shared safety rules: market weather, stop loss, similar-market check."""

import unittest

import pandas as pd

import config
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent
from models.base_agent import Action, Signal


class SafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2023-01-01"),
                                      pd.Timestamp("2025-06-30"), seed=4)
        cal = cls.market.calendar
        cls.days = cal[cal >= pd.Timestamp("2024-07-01")]

    def run_sim(self, params):
        agent = make_agent("trend", params)
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.days)
        return sim.accounts[0]

    def test_all_off_by_default_changes_nothing(self):
        off = self.run_sim({}).portfolio
        explicit = self.run_sim({"market_filter": 0, "stop_loss_pct": 0,
                                 "max_corr": 0}).portfolio
        self.assertEqual(len(off.trades), len(explicit.trades))
        self.assertAlmostEqual(off.cash, explicit.cash)

    def test_no_buys_in_a_storm(self):
        acc = self.run_sim({"market_filter": 200})
        agent = acc.agent
        bench = config.BENCHMARK_TICKER
        close = self.market.bars[bench]["Close"]
        stormy = close < close.rolling(200).mean()
        buys = [t for t in acc.portfolio.trades if t.side == "BUY"]
        self.assertTrue(buys)
        for t in buys:   # bought at the open after a fine-weather decision
            decided = self.market.calendar[
                self.market.calendar.get_loc(t.date) - 1]
            self.assertFalse(bool(stormy[decided]))
            self.assertTrue(agent.market_ok(decided))

    def test_stop_loss_sells_big_losers(self):
        acc = self.run_sim({"stop_loss_pct": 0.05})
        reasons = [s["reason"] for day in acc.activity
                   for s in day["signals"] if s["action"] == "SELL"]
        self.assertTrue(any(r.startswith("Stop loss") for r in reasons))

    def test_similar_market_is_skipped(self):
        a, b = self.market.tickers[:2]
        date = self.days[-1]
        rets = self.market.close_panel.loc[:date].tail(61).pct_change()
        corr = rets[a].corr(rets[b])
        below = make_agent("trend", {"max_corr": corr - 0.01})
        above = make_agent("trend", {"max_corr": corr + 0.01})
        off = make_agent("trend")
        for agent in (below, above, off):
            agent.prepare(self.market)
        self.assertTrue(below._too_similar(a, [b], date))
        self.assertFalse(above._too_similar(a, [b], date))
        self.assertFalse(off._too_similar(a, [b], date))

    def test_guard_keeps_sells_in_a_storm(self):
        agent = make_agent("trend", {"market_filter": 200})
        agent.prepare(self.market)
        agent._weather = {d: False for d in self.days}
        acc = build_accounts(self.market, [agent])[0]
        sigs = [Signal("A", Action.BUY, "x"), Signal("B", Action.SELL, "y")]
        kept = agent.guard(sigs, self.days[0], acc.portfolio)
        self.assertEqual([s.action for s in kept], [Action.SELL])


if __name__ == "__main__":
    unittest.main()
