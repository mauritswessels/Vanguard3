"""The race chart and caption for the Telegram morning message."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import telegram_chart as chart


def payload():
    days = ["2026-10-07", "2026-10-08", "2026-10-09"]

    def agent(key, name, end, **extra):
        return {"key": key, "name": name,
                "equity": [[days[0], 100_000.0], [days[1], 100_000.0],
                           [days[2], end]],
                "stats": {"total_return": end / 100_000 - 1,
                          "final_equity_chf": end},
                "cash_chf": end / 4, "positions": [], "trades": [],
                "pending_orders": [], **extra}
    return {"start": days[0], "last": days[-1], "agents": [
        agent("trend", "Trend Follower", 101_000.0,
              positions=[{"ticker": "MA", "value_chf": 30_300.0,
                          "pnl_pct": 0.021},
                         {"ticker": "V", "value_chf": 20_200.0,
                          "pnl_pct": -0.01}],
              trades=[{"date": "2026-10-08", "side": "BUY", "ticker": "MA",
                       "reason": "Up-trend, ADX 27.1"}],
              pending_orders=[{"side": "SELL", "ticker": "V",
                               "reason": "Down-trend"}]),
        agent("trend", "Trend Follower (fixed)", 103_000.0),
        agent("news", "News Analyst", 99_500.0),
        agent("reversion", "Bargain Hunter", 100_200.0),
        agent("learner", "AI Learner", 100_000.0),
        agent("benchmark", "Buy & Hold SPY", 100_500.0, benchmark=True),
        agent("monkey", "Monkey", 102_000.0, benchmark=True),
    ]}


class ChartTest(unittest.TestCase):
    def test_caption_ranks_racers_and_lists_yardsticks(self):
        lines = chart.caption(payload()).splitlines()
        self.assertEqual(lines[0], "The race, day 3 (close of 2026-10-09)")
        self.assertEqual(lines[1:4], ["1. Trend Follower +1.00%",
                                      "2. Bargain Hunter +0.20%",
                                      "3. AI Learner +0.00%"])
        self.assertEqual(lines[4:], ["Yardstick Buy & Hold SPY +0.50%",
                                     "Yardstick Monkey +2.00%"])

    def test_ranks_on_the_lead_over_spy_over_the_same_days(self):
        """A late joiner that skipped a fall must not lead just for that."""
        data = payload()
        lead = {"Trend Follower": ("2026-10-07", 0.004),
                "Bargain Hunter": ("2026-10-07", 0.011),
                "News Analyst": ("2026-10-08", 0.006)}
        for a in data["agents"]:
            a["joined"] = lead.get(a["name"], ("2026-10-07",))[0]
            a["same_days"] = {"benchmark": None if a["name"] not in lead
                              else {"from": lead[a["name"]][0],
                                    "difference": lead[a["name"]][1]}}
        data["agents"][-1]["joined"] = "2026-10-08"         # the Monkey
        lines = chart.caption(data).splitlines()
        self.assertEqual(lines[1:4], [
            "1. Bargain Hunter +0.20%, 1.10% ahead of SPY since 7 Oct",
            "2. News Analyst -0.50%, 0.60% ahead of SPY since 8 Oct",
            "3. Trend Follower +1.00%, 0.40% ahead of SPY since 7 Oct"])
        self.assertEqual(lines[4:], ["Yardstick Buy & Hold SPY +0.50%",
                                     "Yardstick Monkey +2.00% since 8 Oct"])
        self.assertIn("1. Bargain Hunter +0.20%, 1.10% ahead",
                      chart.why(data))
        # Not trading yet (no same-days figures): last.
        self.assertEqual(chart.ranked(data)[-1]["name"], "AI Learner")
        self.assertEqual(chart.COLORS["equal_weight"], "#c9ccd1")

    def test_labels_keep_apart(self):
        self.assertEqual(chart.spread([1.0, 5.0], 1.0), [1.0, 5.0])
        a, b, c = sorted(chart.spread([0.0, 0.1, 0.2], 1.0))
        self.assertAlmostEqual(b - a, 1.0)
        self.assertAlmostEqual(c - b, 1.0)

    def test_why_explains_the_top_three(self):
        text = chart.why(payload())
        self.assertTrue(text.startswith("Why the top 3 hold what they hold "
                                        "(close of 9 Oct)"))
        self.assertIn("1. Trend Follower +1.00%\nBuys markets in a steady "
                      "rise", text)
        self.assertIn("- MA 30% of the account (+2.1%), bought 8 Oct: in a "
                      "steady rise", text)
        self.assertIn("- V 20% of the account (-1.0%)\n", text)
        self.assertIn("- Cash: 25%", text)
        self.assertIn("- Next open: sells V (Down-trend)", text)
        self.assertIn("3. AI Learner", text)
        self.assertIn("- Holds nothing yet\n- Cash: 25%\n"
                      "- Next open: no trades planned", text)
        self.assertNotIn("Monkey", text)
        self.assertNotIn("(fixed)", text)
        self.assertLess(len(text), 4096)         # one Telegram message

    def test_trade_alert_lists_every_trade_and_waiting_order(self):
        data = payload()
        buy = {"date": "2026-10-09", "session": "open", "side": "BUY",
               "ticker": "NESN.SW", "quantity": 20, "value_chf": 1_812.4,
               "pnl_chf": None, "reason": "Oversold, RSI 28.3"}
        sell = {"date": "2026-10-09", "session": "midday", "side": "SELL",
                "ticker": "V", "quantity": 5, "value_chf": 1_400.0,
                "pnl_chf": -32.6, "reason": "Weak guidance."}
        old = dict(buy, date="2026-10-08", ticker="ABB.SW")
        for a in data["agents"]:
            if a["key"] == "reversion":
                a["trades"] = [old, buy]
            if a["key"] == "news":
                a["trades"] = [sell]
        text = chart.trades(data)
        self.assertTrue(text.startswith("Trades on 9 Oct\n"))
        self.assertIn("Bargain Hunter\n- Bought 20 NESN.SW for 1,812 CHF: "
                      "fell sharply and looks cheap", text)
        self.assertNotIn("ABB.SW", text)            # an earlier day
        self.assertIn("News Analyst\n- Sold 5 V for 1,400 CHF at midday "
                      "(-33 CHF on it): Weak guidance", text)
        self.assertIn("Orders for the next open\n\nTrend Follower\n"
                      "- Sell", text)

    def test_trade_alert_with_nothing_to_say(self):
        data = payload()
        for a in data["agents"]:
            a["pending_orders"] = []
        self.assertEqual(chart.trades(data),
                         "Trades on 9 Oct\n\nNo account traded.\n\n"
                         "Orders for the next open\n\nNo orders waiting.")

    def test_trade_alert_folds_twins_and_fits_one_message(self):
        data = payload()
        orders = [{"side": "BUY", "ticker": f"T{i}", "quantity": 1,
                   "reason": "Up-trend, ADX 30.0 " + "x" * 90}
                  for i in range(60)]
        for a in data["agents"]:
            a["pending_orders"] = list(orders)
        text = chart.trades(data)
        self.assertIn("Trend Follower (fixed): the same as Trend Follower",
                      text)
        self.assertIn("more", text)
        self.assertLessEqual(len(text), chart.TELEGRAM_LIMIT)

    def test_plain_words(self):
        self.assertEqual(chart.plain("Oversold, RSI 28.3"),
                         "fell sharply and looks cheap")
        self.assertEqual(chart.plain("Team target 5.1% (holds 0.0%)"),
                         "copying its agents (5.1% of the account)")
        self.assertEqual(chart.plain(
            "Model score favours SELL; biggest factor: 5-day momentum "
            "(against)"),
            "its model turned against it, mostly because of the 5-day "
            "momentum")
        self.assertEqual(chart.plain("Opus approved: Strong results."),
                         "Strong results")
        self.assertEqual(len(chart.plain("x" * 300)), 120)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"),
                         "needs matplotlib")
    def test_draws_a_png(self):
        # The server only has requirements-ibkr.txt and matplotlib: no pandas.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("sys.modules", {"pandas": None}):
            path = Path(tmp) / "race.png"
            chart.draw(payload(), path)
            self.assertEqual(path.read_bytes()[:4], b"\x89PNG")


if __name__ == "__main__":
    unittest.main()
