"""News Analyst: decisions only on the newest session, limits enforced."""

import json
import unittest

import pandas as pd

import news
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent


def fake_brief(lines):
    return {"macro": ["08 Oct · Wire · Central bank holds rates"],
            "markets": {t: {"prices": p, "news": ["headline"], "results": None}
                        for t, p in lines.items()}, "errors": 0}


class NewsAgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2024-01-01"),
                                      pd.Timestamp("2025-03-31"), seed=5)
        cls.market.source = "test"          # let the agent act on test prices

    def sim(self, decide):
        agent = make_agent("news")
        agent.build_brief, agent.decide = fake_brief, decide
        return Simulator(self.market, build_accounts(self.market, [agent]))

    def test_decides_only_on_latest_session_and_buys_targets(self):
        calls = []

        def decide(brief, holdings, cash, model, max_w, max_total):
            calls.append(len(brief["markets"]))
            text = json.dumps({"market_view": "calm", "targets": {
                "SPY": {"weight": 0.12, "reason": "steady"},
                "GLD": {"weight": 0.9, "reason": "too big"}}})
            return news.parse_decision(text, list(brief["markets"]),
                                       max_w, max_total)

        sim = self.sim(decide)
        sim.run(self.market.calendar[-5:])
        acc = sim.accounts[0]
        self.assertEqual(len(calls), 1)
        self.assertEqual(acc.agent.targets["GLD"]["weight"], 0.15)
        tickers = {o["ticker"] for o in acc.broker.pending_to_list()}
        self.assertEqual(tickers, {"SPY", "GLD"})

    def test_no_key_means_no_orders(self):
        def decide(*a, **k):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        sim = self.sim(decide)
        sim.run(self.market.calendar[-2:])
        acc = sim.accounts[0]
        self.assertEqual(acc.broker.pending_to_list(), [])
        self.assertIn("API key", acc.agent.status)

    def test_parse_decision_caps_total_and_ignores_unknown(self):
        text = 'Sure: {"targets": {"A": {"weight": 0.5}, "B": {"weight": 0.5},' \
               ' "EVIL": {"weight": 1}}}'
        d = news.parse_decision(text, ["A", "B"], 0.4, 0.6)
        self.assertNotIn("EVIL", d["targets"])
        self.assertAlmostEqual(sum(v["weight"] for v in d["targets"].values()), 0.6)


if __name__ == "__main__":
    unittest.main()
