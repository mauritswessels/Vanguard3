"""The Opus Learner: the AI Learner's picks, approved or turned down by Opus."""

import json
import unittest

import pandas as pd

from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import CLAUDE_KEYS, agent_key, make_agent
from models.opus_learner_agent import parse_review


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
