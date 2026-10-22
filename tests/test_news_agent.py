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

    def test_parse_decision_treats_a_weight_that_is_not_a_number_as_zero(self):
        # json.loads reads NaN and Infinity; such a weight must not survive
        # (saved as null, it would crash the next run).
        text = ('{"targets": {"A": {"weight": NaN}, "B": {"weight": Infinity},'
                ' "C": {"weight": 0.1}}}')
        d = news.parse_decision(text, ["A", "B", "C"], 0.4, 0.6)
        self.assertEqual(d["targets"]["A"]["weight"], 0.0)
        self.assertEqual(d["targets"]["B"]["weight"], 0.0)
        self.assertAlmostEqual(d["targets"]["C"]["weight"], 0.1)


class ProbabilityTest(unittest.TestCase):
    """Each target may state the chance its market beats SPY over the next
    5 trading days; a missing or odd one is dropped, never blocks a trade."""

    def test_probabilities_are_read_and_kept_between_0_and_1(self):
        given = {"A": 0.72, "B": 70, "C": -0.2, "D": 150, "E": "0.4",
                 "F": "likely", "G": None, "H": True, "I": "NaN", "J": [0.5]}
        text = json.dumps({"targets": {
            **{t: {"weight": 0.05, "probability": p} for t, p in given.items()},
            "K": {"weight": 0.05},
            "EVIL": {"weight": 1, "probability": 0.9}}})
        universe = list(given) + ["K"]
        d = news.parse_decision(text, universe, 0.04, 0.3)
        got = {t: v.get("probability") for t, v in d["targets"].items()}
        self.assertEqual(got, {"A": 0.72, "B": 0.7, "C": 0.0, "D": 1.0,
                               "E": 0.4, "F": None, "G": None, "H": None,
                               "I": None, "J": None, "K": None})
        self.assertNotIn("probability", d["targets"]["K"])   # none stated
        # The usual limits hold all the same.
        self.assertNotIn("EVIL", d["targets"])
        self.assertTrue(all(v["weight"] <= 0.04 for v in d["targets"].values()))
        self.assertAlmostEqual(sum(v["weight"] for v in d["targets"].values()),
                               0.3)

    def test_without_probabilities_the_reply_parses_as_before(self):
        text = '{"targets": {"A": {"weight": 0.1, "reason": "steady"}}}'
        d = news.parse_decision(text, ["A", "B"], 0.4, 0.6)
        self.assertEqual(d["targets"]["A"], {"weight": 0.1, "reason": "steady"})

    def test_a_bad_probability_never_blocks_a_trade(self):
        market = load_market_data("synthetic", pd.Timestamp("2024-01-01"),
                                  pd.Timestamp("2025-03-31"), seed=5)
        market.source = "test"

        def decide(brief, holdings, cash, model, max_w, max_total):
            text = json.dumps({"targets": {
                "SPY": {"weight": 0.1, "reason": "steady",
                        "probability": "very likely"},
                "GLD": {"weight": 0.1, "reason": "safe", "probability": 0.35},
                "QQQ": {"weight": 0.1, "reason": "growth"}}})
            return news.parse_decision(text, list(brief["markets"]),
                                       max_w, max_total)

        agent = make_agent("news")
        agent.build_brief, agent.decide = fake_brief, decide
        sim = Simulator(market, build_accounts(market, [agent]))
        sim.run(market.calendar[-3:])
        acc = sim.accounts[0]
        self.assertEqual({o["ticker"] for o in acc.broker.pending_to_list()},
                         {"SPY", "GLD", "QQQ"})
        stated = {s["ticker"]: s["details"]["probability"]
                  for s in acc.activity[-1]["signals"]}
        self.assertEqual(stated, {"SPY": None, "GLD": 0.35, "QQQ": None})

    def test_stated_probabilities_reach_the_report_card(self):
        """Decided on one evening, filled at the next open, scored once 5
        trading days have passed: in the trade log and the account's card."""
        import reporting
        full = load_market_data("synthetic", pd.Timestamp("2024-01-01"),
                                pd.Timestamp("2025-03-31"), seed=5)
        full.source = "test"
        cal = full.calendar
        evening = full.until(cal[-12])
        stated = {"AAPL": 0.8, "GLD": 0.3, "QQQ": 0.6}

        def decide(brief, holdings, cash, model, max_w, max_total, note=""):
            text = json.dumps({"targets": {
                t: {"weight": 0.1, "reason": "test", "probability": p}
                for t, p in stated.items()}})
            return news.parse_decision(text, list(brief["markets"]),
                                       max_w, max_total)

        agent = make_agent("news")
        agent.build_brief, agent.decide = fake_brief, decide
        sim = Simulator(evening, build_accounts(evening, [agent]))
        sim.run(evening.calendar[-2:])
        # The next runs: catching up decides nothing, the last day keeps all.
        later = Simulator.from_dict(json.loads(json.dumps(sim.to_dict())), full)
        later.accounts[0].agent.build_brief = fake_brief
        later.accounts[0].agent.decide = decide
        later.run(cal[-11:])
        p = reporting.dashboard_payload(later, "paper", cal[-13])
        (account,) = p["agents"]
        fills = {t["ticker"]: t for t in account["trades"]}
        self.assertEqual(set(fills), set(stated))
        for t, prob in stated.items():
            self.assertEqual(fills[t]["decision"]["details"]["probability"],
                             prob)
        cal_ = account["report_card"]["calibration"]
        self.assertEqual((cal_["stated"], cal_["scored"]), (3, 3))
        self.assertAlmostEqual(cal_["avg_probability"], 0.567, 3)
        self.assertEqual({c["ticker"]: c["probability"]
                          for c in account["report_card"]["recent"]}, stated)
        # The card Claude reads keeps its old fields.
        self.assertNotIn("calibration", later.accounts[0].agent.card)


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

    def test_reads_only_the_text_of_a_finished_reply(self):
        import claude_api
        reply = {"stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": '{"a": '}, {"type": "text", "text": "1}"}]}
        self.assertEqual(claude_api.reply_text(reply), '{"a": 1}')

    def test_says_when_a_reply_was_cut_off(self):
        import claude_api
        for stop, why in (("max_tokens", "it reached its length limit"),
                          ("model_context_window_exceeded",
                           "the question was too long for it")):
            reply = {"stop_reason": stop,
                     "content": [{"type": "text", "text": '{"targets": {'}]}
            with self.assertRaises(RuntimeError) as ctx:
                claude_api.reply_text(reply)
            self.assertEqual(str(ctx.exception),
                             f"Claude's reply was cut off ({why})")

    def test_says_when_claude_declined(self):
        import claude_api
        reply = {"stop_reason": "refusal", "content": [],
                 "stop_details": {"type": "refusal", "category": "cyber",
                                  "explanation": "..."}}
        with self.assertRaisesRegex(RuntimeError, r"^Claude declined: cyber$"):
            claude_api.reply_text(reply)
        # The details are optional: the category may be null, or missing.
        for details in ({"type": "refusal", "category": None}, None):
            reply = {"stop_reason": "refusal", "content": [],
                     "stop_details": details}
            with self.assertRaisesRegex(RuntimeError,
                                        r"^Claude declined to answer$"):
                claude_api.reply_text(reply)


class AskClaudeTest(unittest.TestCase):
    """The News Analyst's call: room to think, and a clear reason when the
    reply is not usable (the agent then sits out with that reason)."""

    def ask(self, reply):
        sent = {}

        def call_claude(body, key, **kwargs):
            sent.update(body, purpose=kwargs.get("purpose"))
            return reply

        brief = fake_brief({"SPY": "close 600.00 USD", "GLD": "close 300 USD"})
        with mock.patch.object(news, "call_claude", call_claude):
            out = news.ask_claude(brief, {}, 1.0, "claude-sonnet-5-5",
                                  0.15, 0.90, api_key="k")
        return out, sent

    def test_a_finished_reply_is_parsed_with_the_usual_limits(self):
        text = json.dumps({"market_view": "calm", "targets": {
            "SPY": {"weight": 0.5, "reason": "steady"},
            "XYZ": {"weight": 0.1, "reason": "not on the list"}}})
        out, sent = self.ask({"stop_reason": "end_turn", "model": "m",
                              "usage": {"output_tokens": 900},
                              "content": [{"type": "thinking", "thinking": ""},
                                          {"type": "text", "text": text}]})
        self.assertEqual(sent["max_tokens"], 8000)
        self.assertEqual(sent["purpose"], "News Analyst")      # archived
        self.assertEqual(out["targets"]["SPY"]["weight"], 0.15)  # clipped
        self.assertNotIn("XYZ", out["targets"])                 # ignored
        self.assertEqual(out["usage"], {"output_tokens": 900})

    def test_asks_for_the_chance_of_beating_spy(self):
        text = json.dumps({"market_view": "calm", "targets": {
            "GLD": {"weight": 0.1, "reason": "safe", "probability": 0.55}}})
        out, sent = self.ask({"stop_reason": "end_turn", "content": [
            {"type": "text", "text": text}]})
        self.assertIn('"probability": <number from 0 to 1>', sent["system"])
        self.assertIn("next 5 trading days", sent["system"])
        self.assertEqual(out["targets"]["GLD"]["probability"], 0.55)

    def test_a_cut_off_reply_is_not_traded(self):
        cut = {"stop_reason": "max_tokens", "content": [
            {"type": "text", "text": '{"market_view": "calm", "targets": {'
                                     '"SPY": {"weight": 0.1'}]}
        with self.assertRaisesRegex(RuntimeError, "reply was cut off"):
            self.ask(cut)

        # In the race, the agent keeps its targets and says why.
        market = load_market_data("synthetic", pd.Timestamp("2024-01-01"),
                                  pd.Timestamp("2024-12-31"), seed=5)
        market.source = "test"
        agent = make_agent("news")
        agent.build_brief = fake_brief
        sim = Simulator(market, build_accounts(market, [agent]))
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}), \
                mock.patch.object(news, "call_claude",
                                  lambda body, key, **kw: cut):
            sim.run(market.calendar[-2:])
        acc = sim.accounts[0]
        self.assertEqual(acc.broker.pending_to_list(), [])
        self.assertEqual(acc.agent.status, "No decision today: Claude's reply "
                         "was cut off (it reached its length limit)")

    def test_a_declined_reply_names_the_reason(self):
        with self.assertRaisesRegex(RuntimeError, "^Claude declined: bio$"):
            self.ask({"stop_reason": "refusal", "content": [],
                      "stop_details": {"category": "bio"}})


if __name__ == "__main__":
    unittest.main()
