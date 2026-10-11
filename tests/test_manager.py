"""The Team Manager: owns a share of what the best agents own."""

import json
import unittest

import pandas as pd

from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent


class ManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2023-06-01"),
                                      pd.Timestamp("2025-06-30"), seed=6)
        cal = cls.market.calendar
        cls.days = cal[cal >= pd.Timestamp("2025-02-03")][:70]

    def lineup(self):
        return [make_agent("trend", learning=True),
                make_agent("trend", name="Trend Follower (fixed)"),
                make_agent("reversion", learning=True),
                make_agent("volatility", learning=True),
                make_agent("benchmark"),
                make_agent("manager", {"min_history": 30, "top_n": 2})]

    def test_backs_everyone_then_the_best(self):
        sim = Simulator(self.market, build_accounts(self.market,
                                                    self.lineup()))
        sim.run(self.days[:10])
        mgr = sim.accounts[-1].agent
        self.assertEqual(set(mgr.backing), {"Trend Follower", "Bargain Hunter",
                                            "Volatility Protected"})
        sim.run(self.days[10:])
        self.assertEqual(len(mgr.backing), 2)
        self.assertIn("best", mgr.why)
        pf = sim.accounts[-1].portfolio
        self.assertTrue(pf.positions)
        backed = {a.agent.name: a for a in sim.accounts}
        owned = set().union(*(backed[n].portfolio.positions
                              for n in mgr.backing))
        held_today = {t for t in pf.positions}
        # Mostly what the backed agents own (yesterday's holdings may lag).
        self.assertGreaterEqual(len(held_today & owned),
                                len(held_today) // 2)

    def test_state_round_trip(self):
        sim = Simulator(self.market, build_accounts(self.market,
                                                    self.lineup()))
        sim.run(self.days[:40])
        state = json.loads(json.dumps(sim.to_dict()))
        again = Simulator.from_dict(state, self.market)
        again.run(self.days[40:45])
        sim.run(self.days[40:45])
        a, b = sim.accounts[-1].portfolio, again.accounts[-1].portfolio
        self.assertEqual(a.positions.keys(), b.positions.keys())
        self.assertAlmostEqual(a.cash, b.cash, places=4)


if __name__ == "__main__":
    unittest.main()
