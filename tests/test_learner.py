"""The daily-learning AI agent: pre-training, shadow mode and persistence."""

import json
import unittest

import numpy as np
import pandas as pd

from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent


class LearnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2023-01-01"),
                                      pd.Timestamp("2025-03-31"), seed=3)
        cal = cls.market.calendar
        cls.days = cal[cal >= pd.Timestamp("2025-01-02")][:40]

    def run_sim(self, live_from):
        agent = make_agent("learner", {"live_from": live_from,
                                       "pretrain_years": 1,
                                       "pretrain_epochs": 1})
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.days)
        return sim

    def test_shadow_mode_learns_without_trading(self):
        sim = self.run_sim("2099-01-01")
        agent, pf = sim.accounts[0].agent, sim.accounts[0].portfolio
        self.assertEqual(pf.trades, [])
        self.assertEqual(agent.days_learned, len(self.days) - 1)
        self.assertGreater(agent.pretrain["updates"], 0)

    def test_trades_once_live_and_state_round_trips(self):
        sim = self.run_sim("2025-01-02")
        self.assertTrue(sim.accounts[0].portfolio.trades)
        state = json.loads(json.dumps(sim.to_dict()))
        again = Simulator.from_dict(state, self.market)
        a, b = sim.accounts[0].agent, again.accounts[0].agent
        np.testing.assert_allclose(a.w, b.w)
        self.assertEqual(a.days_learned, b.days_learned)
        self.assertEqual(a.memory.keys(), b.memory.keys())

    def test_same_inputs_same_decisions(self):
        w1 = self.run_sim("2025-01-02").accounts[0].agent.w
        w2 = self.run_sim("2025-01-02").accounts[0].agent.w
        np.testing.assert_array_equal(w1, w2)


if __name__ == "__main__":
    unittest.main()
