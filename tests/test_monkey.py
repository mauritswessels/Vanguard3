"""The Monkey: random picks under the same rules as everyone else."""

import json
import unittest

import pandas as pd

from data_manager import load_market_data
from engine.broker import Order
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

    def test_a_buy_waiting_for_its_market_takes_a_slot(self):
        # A holiday on one market: its buy waits, and the dice must not
        # fill that slot a second time.
        sim = self.run_sim(self.days[:20])
        acc = sim.accounts[0]
        pf, agent, day = acc.portfolio, acc.agent, self.days[20]
        free = 10 - len(pf.positions)
        pool = [t for t in agent.indicators if not pf.has_position(t)]
        acc.broker.pending = [
            Order(t, "BUY", 1, self.days[19]) for t in pool[:free]]
        signals = agent.calculate_signals(day, pf)
        orders = agent.execute_trade(signals, day, pf, acc.broker)
        sells = sum(o.side == "SELL" for o in orders)
        self.assertLessEqual(sum(o.side == "BUY" for o in orders), sells)
        self.assertTrue(all(o.ticker not in pool[:free] for o in orders))

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
