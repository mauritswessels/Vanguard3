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

    def test_an_agent_that_joins_is_backed_at_once(self):
        sim = Simulator(self.market, build_accounts(self.market,
                                                    self.lineup()))
        sim.run(self.days[:5])
        mgr = sim.accounts[-1].agent
        self.assertEqual(len(mgr.backing), 3)
        sim.add_account(make_agent("monkey"), self.days[0])     # a yardstick
        sim.add_account(make_agent("learner"), self.days[0])
        sim.run(self.days[5:7])
        self.assertIn("AI Learner", mgr.backing)
        self.assertEqual(len(mgr.backing), 4)
        self.assertNotIn("Monkey", mgr.backing)

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
        # Mostly what the backed agents own.
        self.assertGreaterEqual(len(held_today & owned),
                                len(held_today) // 2)

    def test_follows_todays_decisions(self):
        """Its targets include what the agents ordered this evening, even
        when it is listed before them."""
        lineup = self.lineup()
        lineup.insert(0, lineup.pop())          # the Team Manager first
        sim = Simulator(self.market, build_accounts(self.market, lineup))
        mgr = sim.accounts[0].agent
        checked = 0
        for day in self.days[:30]:
            sim.step(day)
            for name in mgr.backing:
                acc = next(a for a in sim.accounts if a.agent.name == name)
                for o in acc.broker.pending:
                    if o.side == "BUY" and o.created == day:
                        self.assertIn(o.ticker, mgr._targets)
                        checked += 1
        self.assertGreater(checked, 0)

    def test_holdings_after_orders(self):
        from types import SimpleNamespace as NS
        from models.manager_agent import holdings_after_orders
        acc = NS(portfolio=NS(positions={"A": NS(quantity=10),
                                         "B": NS(quantity=4)}),
                 broker=NS(pending=[NS(ticker="A", side="SELL", quantity=10),
                                    NS(ticker="B", side="BUY", quantity=1),
                                    NS(ticker="C", side="BUY", quantity=3)]))
        self.assertEqual(holdings_after_orders(acc), {"B": 5, "C": 3})

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
