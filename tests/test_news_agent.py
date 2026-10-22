"""News Analyst: decisions only on the newest session, limits enforced."""

import json
import unittest
from unittest import mock

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

    def test_report_card_grades_trades_against_spy_and_feeds_memory(self):
        from types import SimpleNamespace as NS
        agent = make_agent("news")
        agent.prepare(self.market)
        cal, panel = self.market.calendar, self.market.close_panel
        d0, d5, last = cal[-30], cal[-25], cal[-1]
        t = "AAPL"
        buy = NS(date=d0, ticker=t, side="BUY",
                 market_price=float(panel.at[d0, t]))
        sell = NS(date=d0, ticker=t, side="SELL",
                  market_price=float(panel.at[d0, t]))
        fresh = NS(date=cal[-2], ticker=t, side="BUY",
                   market_price=float(panel.at[cal[-2], t]))
        card = agent.report_card([buy, sell, fresh], last)
        # Both measured from the open of the fill day (engine.grading).
        opens = self.market.open_panel
        move = panel.at[d5, t] / opens.at[d0, t] - 1
        spy = panel.at[d5, "SPY"] / opens.at[d0, "SPY"] - 1
        self.assertAlmostEqual(card["calls"][0]["edge_5"], move - spy, 4)
        self.assertAlmostEqual(card["calls"][1]["edge_5"], spy - move, 4)
        self.assertNotIn("edge_5", card["calls"][2])     # too early to grade
        self.assertEqual(card["graded_5"], 2)
        self.assertEqual(card["graded_20"], 2)
        self.assertEqual(card["hit_rate_5"], 0.5)
        # The same fields as before the shared grader: Claude reads these.
        self.assertEqual(list(card), ["calls", "graded_5", "hit_rate_5",
                                      "avg_edge_5", "graded_20", "hit_rate_20",
                                      "avg_edge_20"])
        self.assertEqual(set(card["calls"][0]),
                         {"date", "ticker", "side", "edge_5", "edge_20"})

        agent.card = card
        seen = {}

        def decide(brief, holdings, cash, model, max_w, max_total, note=""):
            seen["note"] = note
            return news.parse_decision('{"targets": {}}', [], max_w, max_total)

        agent.build_brief, agent.decide = fake_brief, decide
        agent.consult({t: "x"}, {}, 1.0)
        self.assertIn("YOUR TRACK RECORD", seen["note"])
        self.assertIn(f"bought {t}", seen["note"])

    def test_report_card_skips_a_market_without_prices_today(self):
        from types import SimpleNamespace as NS
        agent = make_agent("news")
        agent.prepare(self.market)
        cal = self.market.calendar
        gone = NS(date=cal[-30], ticker="GONE.SW", side="BUY",
                  market_price=10.0)
        card = agent.report_card([gone], cal[-1])
        self.assertEqual(card["graded_5"], 0)

    def test_a_reply_in_the_wrong_shape_is_not_sell_everything(self):
        for text in ('{"market_view": "calm"}', '{"targets": ["A"]}',
                     '{"targets": {"a": {"weight": 0.2}}}'):
            with self.assertRaises(ValueError, msg=text):
                news.parse_decision(text, ["A", "B"], 0.4, 0.6)
        empty = news.parse_decision('{"targets": {}}', ["A", "B"], 0.4, 0.6)
        self.assertEqual(empty["targets"]["A"]["weight"], 0.0)

    def test_parse_decision_caps_total_and_ignores_unknown(self):
        text = 'Sure: {"targets": {"A": {"weight": 0.5}, "B": {"weight": 0.5},' \
               ' "EVIL": {"weight": 1}}}'
        d = news.parse_decision(text, ["A", "B"], 0.4, 0.6)
        self.assertNotIn("EVIL", d["targets"])
        self.assertAlmostEqual(sum(v["weight"] for v in d["targets"].values()), 0.6)


class OpusTwinTest(unittest.TestCase):
    def test_same_rules_stronger_model(self):
        from models import agent_key, make_agent
        base, opus = make_agent("news"), make_agent("news_opus")
        self.assertEqual(agent_key(opus), "news_opus")
        self.assertEqual(opus.name, "News Analyst (Opus)")
        self.assertNotEqual(opus.params["model"], base.params["model"])
        self.assertIn("opus", opus.params["model"])
        for k in ("max_weight", "max_total", "min_weight"):
            self.assertEqual(opus.params[k], base.params[k])
        self.assertEqual(opus.summary()["kind"], "news")

    def test_in_the_live_lineup(self):
        from learning import paper_lineup
        from types import SimpleNamespace
        names = [a.name for a in paper_lineup(SimpleNamespace(bars={}))]
        self.assertIn("News Analyst (Opus)", names)


class SharedBriefTest(unittest.TestCase):
    """Both News Analysts read the same news: it is downloaded once."""

    def setUp(self):
        news._last_brief = None
        self.addCleanup(setattr, news, "_last_brief", None)

    def test_the_second_analyst_reuses_the_download(self):
        calls = []

        def fake_headlines(query, limit=6, days=2):
            calls.append(query)
            return [f"20 Oct · Feed · {query}"]

        lines = {"SPY": "close 600.00 USD", "GLD": "close 300.00 USD"}
        with mock.patch.object(news, "headlines", fake_headlines), \
                mock.patch.object(news.time, "sleep", lambda s: None), \
                mock.patch.object(news.finnhub_feed, "api_key", lambda: None):
            first = news.build_brief(lines)
            n = len(calls)
            second = news.build_brief(lines)
            self.assertEqual(len(calls), n)              # nothing downloaded
            self.assertEqual(first, second)
            second["macro"].clear()                      # a copy each
            self.assertTrue(news.build_brief(lines)["macro"])
            news.build_brief({**lines, "SPY": "close 610.00 USD"})
            self.assertGreater(len(calls), n)            # new prices: new news

    def test_an_empty_download_is_tried_again(self):
        def failing(query, limit=6, days=2):
            raise OSError("feed down")

        lines = {"SPY": "close 600.00 USD"}
        with mock.patch.object(news, "headlines", failing), \
                mock.patch.object(news.time, "sleep", lambda s: None), \
                mock.patch.object(news.finnhub_feed, "api_key", lambda: None):
            news.build_brief(lines)
        self.assertIsNone(news._last_brief)


class ClaudeApiTest(unittest.TestCase):
    """How a refusal from Claude reads, and the retry when it is busy."""

    def answer(self, *replies):
        import io
        import urllib.error
        from unittest import mock

        import claude_api
        calls = []

        def urlopen(req, timeout):
            calls.append(req)
            r = replies[len(calls) - 1]
            if isinstance(r, int):
                body = io.BytesIO(json.dumps({"error": {
                    "message": "Your credit balance is too low" if r == 400
                    else "Overloaded"}}).encode())
                raise urllib.error.HTTPError(req.full_url, r, "Bad", {}, body)
            return io.BytesIO(json.dumps(r).encode())

        with mock.patch.object(claude_api.urllib.request, "urlopen", urlopen), \
                mock.patch.object(claude_api.time, "sleep", lambda s: None):
            try:
                return claude_api.call_claude({"model": "m"}, "key"), calls
            except RuntimeError as exc:
                return exc, calls

    def test_says_why_it_refused(self):
        out, calls = self.answer(400)
        self.assertEqual(str(out), "Claude refused (400): Your credit "
                                   "balance is too low")
        self.assertEqual(len(calls), 1)

    def test_tries_once_more_when_busy(self):
        out, calls = self.answer(529, {"content": []})
        self.assertEqual(out, {"content": []})
        self.assertEqual(len(calls), 2)
        out, calls = self.answer(529, 529)
        self.assertIn("(529): Overloaded", str(out))


if __name__ == "__main__":
    unittest.main()
