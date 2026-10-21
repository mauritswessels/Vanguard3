"""The Opus Learner: the AI Learner's picks, approved or turned down by Opus."""

import json
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import CLAUDE_KEYS, agent_key, make_agent
from models.learner_agent import BUY, DIM, HOLD, SELL
from models.opus_learner_agent import parse_review


def verdicts(approve):
    """A stand-in reviewer: ``approve(i, ticker)`` decides each pick."""
    def ask(brief, model, effort):
        tickers = [line.split(":")[0] for line in brief.splitlines()
                   if "model wants to" in line]
        return {"view": "", "decisions": {
            t: {"approve": approve(i, t), "reason": "test"}
            for i, t in enumerate(tickers)}, "usage": {}}
    return ask


def eager(market):
    """An Opus Learner whose model wants to buy every market it does not
    hold and sell every one it does, and never changes its mind (no
    learning steps, no random tries, no minimum holding time)."""
    agent = make_agent("learner_opus", {
        "live_from": "2025-01-02", "lr": 0.0, "epsilon": 0.0, "min_hold": 0,
        "max_review": 1000})
    w = np.zeros((3, DIM))
    w[BUY, -2:] = [-1.0, 1.0]       # holding flag, bias: 2 when not held
    w[SELL, -2:] = [1.0, 1.0]       # 2 when held
    agent.w = w
    agent.news = lambda t, n: []
    return agent


class OpusLearnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2023-01-01"),
                                      pd.Timestamp("2025-03-31"), seed=3)
        cls.market.source = "test"          # let the agent act on test prices

    def sim(self, ask):
        agent = make_agent("learner_opus", {"live_from": "2025-01-02",
                                            "pretrain_years": 1,
                                            "pretrain_epochs": 1})
        agent.ask, agent.news = ask, lambda t, n: [f"headline on {t}"]
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.market.calendar[-5:])
        return sim.accounts[0]

    def test_reviews_once_and_places_only_approved_picks(self):
        calls = []

        def ask(brief, model, effort):
            calls.append(brief)
            tickers = [line.split(":")[0] for line in brief.splitlines()
                       if "model wants to" in line]
            # Approve only the first pick.
            return {"view": "mixed", "decisions": {
                t: {"approve": i == 0, "reason": "ok" if i == 0 else "no"}
                for i, t in enumerate(tickers)}, "usage": {
                    "input_tokens": 3000, "output_tokens": 1000}}

        acc = self.sim(ask)
        agent = acc.agent
        self.assertEqual(len(calls), 1)            # newest session only
        self.assertIn("headline on", calls[0])
        picks = agent.review["picks"]
        self.assertTrue(picks)
        self.assertLessEqual(sum(p["action"] == "BUY" for p in picks),
                             agent.params["max_review"])
        orders = {o["ticker"] for o in acc.broker.pending_to_list()}
        approved = {p["ticker"] for p in picks if p["approve"]}
        self.assertTrue(orders <= approved)
        self.assertEqual(agent.decided,
                         self.market.calendar[-1].strftime("%Y-%m-%d"))
        self.assertEqual(agent.summary()["kind"], "learner_review")
        self.assertGreater(agent.summary()["est_cost_usd"], 0)

    def test_no_key_means_no_orders(self):
        def ask(*a, **k):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        acc = self.sim(ask)
        self.assertEqual(acc.broker.pending_to_list(), [])
        self.assertIn("API key", acc.agent.status)
        self.assertGreater(acc.agent.days_learned, 0)   # still learns
        # Nothing was traded, so only random tries are learned as trades.
        agent = acc.agent
        for t, m in agent.memory.items():
            if m["pos"] != m["prev"]:
                self.assertTrue(agent.last_decisions[t]["explored"], t)

    def test_turned_down_picks_are_learned_as_holds(self):
        cal = self.market.calendar
        # Evening one: every buy approved, so the account holds something.
        first = self.market.until(cal[-3])
        sim = Simulator(first, build_accounts(first, [eager(first)]))
        sim.accounts[0].agent.ask = verdicts(lambda i, t: True)
        sim.run([cal[-3]])
        # Evenings two (catching up, no review) and three: all turned down.
        sim = Simulator.from_dict(json.loads(json.dumps(sim.to_dict())),
                                  self.market)
        acc = sim.accounts[0]
        acc.agent.ask = verdicts(lambda i, t: False)
        acc.agent.news = lambda t, n: []
        sim.run(cal[-2:])
        agent, held = acc.agent, set(acc.portfolio.positions)
        self.assertTrue(held)
        picks = agent.review["picks"]
        self.assertEqual({p["ticker"] for p in picks if p["action"] == "SELL"},
                         held)
        self.assertTrue(any(p["action"] == "BUY" for p in picks))
        for p in picks:
            m = agent.memory[p["ticker"]]
            self.assertEqual(m["a"], HOLD)
            self.assertEqual(m["prev"], int(p["ticker"] in held))
            self.assertEqual(m["pos"], m["prev"])
            self.assertEqual(agent.shadow[p["ticker"]], m["prev"])
            self.assertEqual(agent.last_decisions[p["ticker"]]["action"],
                             "HOLD")
        self.assertEqual(acc.broker.pending_to_list(), [])

    def test_approved_picks_are_learned_as_made(self):
        agent = eager(self.market)
        agent.ask = verdicts(lambda i, t: i % 2 == 0)
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.market.calendar[-1:])
        picks = agent.review["picks"]
        self.assertGreater(len(picks), 2)
        for p in picks:
            m = agent.memory[p["ticker"]]
            self.assertEqual(p["action"], "BUY")
            self.assertEqual((m["a"], m["pos"]),
                             (BUY, 1) if p["approve"] else (HOLD, 0))
            self.assertEqual(agent.shadow[p["ticker"]], m["pos"])

    def test_state_round_trips(self):
        acc = self.sim(lambda b, m, e: {"view": "", "decisions": {}})
        sim = Simulator(self.market, [acc])
        sim.last_date = self.market.calendar[-1]
        again = Simulator.from_dict(json.loads(json.dumps(sim.to_dict())),
                                    self.market)
        b = again.accounts[0].agent
        self.assertEqual(agent_key(b), "learner_opus")
        self.assertEqual(b.review, acc.agent.review)
        self.assertEqual(b.decided, acc.agent.decided)
        self.assertIsNotNone(b.w)
        # Picks left out are restored as the holds they were learned as.
        self.assertEqual(b.memory, acc.agent.memory)
        self.assertEqual(b.shadow, acc.agent.shadow)
        self.assertTrue(b.review["picks"])
        for p in b.review["picks"]:
            self.assertEqual(b.memory[p["ticker"]]["a"], HOLD)

    def test_a_declined_or_cut_off_review_places_nothing(self):
        import models.opus_learner_agent as ol
        for reply, why in (
                ({"stop_reason": "refusal", "content": [],
                  "stop_details": {"category": "cyber"}},
                 "No review today: Claude declined: cyber"),
                ({"stop_reason": "max_tokens", "content": [
                    {"type": "text", "text": '{"view": "fine", "decisions": {'}]},
                 "No review today: Claude's reply was cut off (it reached "
                 "its length limit)")):
            def ask(brief, model, effort, reply=reply):
                with mock.patch.object(ol, "call_claude",
                                       lambda body, key, **kw: reply):
                    return ol.ask_opus(brief, model, effort, api_key="k")

            acc = self.sim(ask)
            self.assertEqual(acc.broker.pending_to_list(), [])
            self.assertEqual(acc.agent.status, why)

    def test_parse_review_defaults_to_not_approved(self):
        r = parse_review('Sure: {"view": "v", "decisions": {'
                         '"AAPL": {"approve": true, "reason": "fine"},'
                         '"MSFT": {"approve": "yes"}}}')
        self.assertTrue(r["decisions"]["AAPL"]["approve"])
        self.assertFalse(r["decisions"]["MSFT"]["approve"])

    def test_in_the_lineup_and_watched(self):
        from types import SimpleNamespace
        from learning import paper_lineup
        names = [a.name for a in paper_lineup(SimpleNamespace(bars={}))]
        self.assertIn("Opus Learner", names)
        self.assertIn("learner_opus", CLAUDE_KEYS)
        opus = make_agent("learner_opus")
        self.assertIn("opus", opus.params["model"])
        self.assertEqual(opus.params["max_positions"],
                         make_agent("learner").params["max_positions"])


if __name__ == "__main__":
    unittest.main()
