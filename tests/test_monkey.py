"""The Monkey: random picks under the same rules as everyone else."""

import json
import unittest

import pandas as pd

from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent


class MonkeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2024-01-01"),
                                      pd.Timestamp("2025-03-31"), seed=5)
        cal = cls.market.calendar
        cls.days = cal[cal >= pd.Timestamp("2025-01-02")][:50]

    def run_sim(self, days):
        sim = Simulator(self.market, build_accounts(self.market,
                                                    [make_agent("monkey")]))
        sim.run(days)
        return sim

    def test_fills_its_slots_and_trades(self):
        sim = self.run_sim(self.days)
        pf = sim.accounts[0].portfolio
        self.assertTrue(pf.positions)
        self.assertLessEqual(len(pf.positions), 10)
        self.assertTrue(any(t.side == "SELL" for t in pf.trades))

    def test_replay_after_restore_matches_a_straight_run(self):
        straight = self.run_sim(self.days).accounts[0].portfolio
        half = self.run_sim(self.days[:25])
        state = json.loads(json.dumps(half.to_dict()))
        again = Simulator.from_dict(state, self.market)
        again.run(self.days[25:])
        resumed = again.accounts[0].portfolio
        self.assertEqual(sorted(straight.positions), sorted(resumed.positions))
        self.assertAlmostEqual(straight.cash, resumed.cash, places=6)


if __name__ == "__main__":
    unittest.main()
