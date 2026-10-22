"""The daily-learning AI agent: pre-training, shadow mode and persistence."""

import json
import unittest

import numpy as np
import pandas as pd

import config
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent
from models.base_agent import Action
from models.learner_agent import BUY, DIM, HOLD, N_FEAT


def eager(**params):
    """An AI Learner whose model wants to buy every market it does not hold
    and keep every one it does, and never changes its mind (no learning
    steps, no random tries)."""
    agent = make_agent("learner", {"live_from": "2025-01-02", "lr": 0.0,
                                   "epsilon": 0.0, **params})
    w = np.zeros((3, DIM))
    w[BUY, -2:] = [-1.0, 1.0]       # holding flag, bias: 2 when not held
    w[HOLD, -1] = 0.5
    agent.w = w
    return agent


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

    def eager_evening(self):
        """One live evening of ``eager``: its signals and the orders placed.
        It wants to buy every market, so the cap leaves most of them out."""
        agent = eager()
        agent.w[BUY, :N_FEAT] = 0.001 * np.arange(1, N_FEAT + 1)
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        acc, day = sim.accounts[0], self.days[0]
        signals = agent.calculate_signals(day, acc.portfolio)
        orders = agent.execute_trade(signals, day, acc.portfolio, acc.broker)
        return agent, signals, orders

    def test_a_buy_the_cap_leaves_out_is_learned_as_a_hold(self):
        agent, signals, orders = self.eager_evening()
        bought = {o.ticker for o in orders}
        left_out = [s for s in signals if s.ticker not in bought]
        self.assertEqual(len(bought), agent.params["max_positions"])
        self.assertTrue(left_out)
        for s in left_out:
            m = agent.memory[s.ticker]
            self.assertIs(s.action, Action.BUY)
            self.assertEqual((m["a"], m["pos"], m["prev"]), (HOLD, 0, 0))
            self.assertEqual(agent.shadow[s.ticker], 0)
            self.assertEqual(agent.last_decisions[s.ticker]["action"], "HOLD")
        # The journal still explains the buy the model wanted.
        s = left_out[0]
        want = agent._contributions(np.array(agent.memory[s.ticker]["phi"]),
                                    BUY)[:3]
        self.assertEqual(
            [f["effect"] for f in agent.decision_details(s, self.days[0])
             ["factors"]],
            [round(c, 4) for _, c in want])

    def test_a_placed_buy_is_learned_as_bought(self):
        agent, signals, orders = self.eager_evening()
        self.assertTrue(orders)
        for o in orders:
            m = agent.memory[o.ticker]
            self.assertEqual(o.side, "BUY")
            self.assertEqual((m["a"], m["pos"], m["prev"]), (BUY, 1, 0))
            self.assertEqual(agent.shadow[o.ticker], 1)
            self.assertEqual(agent.last_decisions[o.ticker]["action"], "BUY")

    def test_buys_learned_as_holds_survive_a_restart(self):
        agent = eager()
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.days[:1])
        placed = {o["ticker"] for o in sim.accounts[0].broker.pending_to_list()}
        again = Simulator.from_dict(json.loads(json.dumps(sim.to_dict())),
                                    self.market)
        b = again.accounts[0].agent
        self.assertEqual(b.memory, agent.memory)
        self.assertEqual(b.shadow, agent.shadow)
        self.assertTrue(placed)
        self.assertEqual({t for t, m in b.memory.items() if m["a"] == BUY},
                         placed)
        self.assertGreater(len(b.memory), len(placed))
        self.assertTrue(all(m["a"] == HOLD for t, m in b.memory.items()
                            if t not in placed))

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
