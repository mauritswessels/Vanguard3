"""The daily-learning AI agent: pre-training, shadow mode and persistence."""

import json
import unittest

import numpy as np
import pandas as pd

import config
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
        cls.all_days = cal[cal >= pd.Timestamp("2025-01-02")]

    def run_sim(self, live_from, days=None, **params):
        agent = make_agent("learner", {"live_from": live_from,
                                       "pretrain_years": 1,
                                       "pretrain_epochs": 1, **params})
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.days if days is None else days)
        return sim

    def holding_times(self, portfolio, days) -> list[int]:
        """Sessions from each buy fill to the sell fill that closed it."""
        index = {d: i for i, d in enumerate(days)}
        opened, held = {}, []
        for t in portfolio.trades:
            if t.side == "BUY":
                opened[t.ticker] = t.date
            else:
                held.append(index[t.date] - index[opened.pop(t.ticker)])
        return held

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

    def test_random_tries_are_learned_on_paper(self):
        def exploring(sim):
            return [t for t in sim.accounts[0].portfolio.trades
                    if t.reason.startswith("Exploring")]
        on_paper = self.run_sim("2025-01-02", epsilon=0.5)
        self.assertEqual(exploring(on_paper), [])
        self.assertEqual(on_paper.accounts[0].agent.days_learned,
                         len(self.days) - 1)
        # The setting is what keeps them out: switched off, they trade.
        traded = self.run_sim("2025-01-02", epsilon=0.5,
                              explore_on_paper=False)
        self.assertTrue(exploring(traded))

    def test_keeps_each_holding_the_minimum_time(self):
        n = config.LEARNER_PARAMS["min_hold"]
        sim = self.run_sim("2025-01-02", self.all_days)
        held = self.holding_times(sim.accounts[0].portfolio, self.all_days)
        self.assertTrue(held)
        # Decided at the close of session n at the earliest, filled at the
        # next open.
        self.assertGreaterEqual(min(held), n + 1)
        # Without the rule the same model sells sooner.
        quick = self.run_sim("2025-01-02", self.all_days, min_hold=0)
        self.assertLess(min(self.holding_times(quick.accounts[0].portfolio,
                                               self.all_days)), n + 1)

    def test_watch_note_explains_a_blocked_sell(self):
        sim = self.run_sim("2025-01-02")
        agent, pf = sim.accounts[0].agent, sim.accounts[0].portfolio
        day = self.days[-1]
        ticker = next(iter(pf.positions))
        age = agent.sessions_held(ticker, day, pf)
        self.assertEqual(agent.sessions_held(
            ticker, pf.positions[ticker].entry_date, pf), 0)
        agent.w[:, -1] = [9.0, 0.0, 0.0]    # make SELL score highest
        agent.params["min_hold"] = age + 3
        self.assertIn("3 more to go", agent.exit_check(ticker, day, pf))
        agent.params["min_hold"] = age
        self.assertEqual(agent.exit_check(ticker, day, pf),
                         "Model now favours SELL")

    def test_state_saved_before_the_trading_rules_still_restores(self):
        sim = self.run_sim("2025-01-02")
        state = json.loads(json.dumps(sim.to_dict()))
        for key in ("explore_on_paper", "min_hold"):
            del state["accounts"][0]["params"][key]
        again = Simulator.from_dict(state, self.market)
        agent = again.accounts[0].agent
        np.testing.assert_allclose(agent.w, sim.accounts[0].agent.w)
        self.assertEqual(agent.params["min_hold"],
                         config.LEARNER_PARAMS["min_hold"])
        self.assertTrue(agent.params["explore_on_paper"])
        again.run(self.all_days[len(self.days):])   # and keeps trading
        self.assertGreater(agent.days_learned,
                           sim.accounts[0].agent.days_learned)

    def test_same_inputs_same_decisions(self):
        w1 = self.run_sim("2025-01-02").accounts[0].agent.w
        w2 = self.run_sim("2025-01-02").accounts[0].agent.w
        np.testing.assert_array_equal(w1, w2)


if __name__ == "__main__":
    unittest.main()
