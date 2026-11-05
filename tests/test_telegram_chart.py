"""The race chart and caption for the Telegram morning message."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date
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


TODAY = date(2026, 10, 12)


class ChartTest(unittest.TestCase):
    def test_caption_ranks_racers_and_lists_yardsticks(self):
        text = chart.caption(payload(), today=TODAY)
        self.assertEqual(text.splitlines()[:2], [
            "<b>📊 Vanguard3 · Mon 12 Oct</b>",
            "Race day 3, results of the close on Fri 9 Oct"])
        self.assertIn("🥇 <b>Trend Follower</b>  +1.00%\n"
                      "🥈 <b>Bargain Hunter</b>  +0.20%\n"
                      "🥉 <b>AI Learner</b>  +0.00%", text)
        self.assertIn("<b>🔻 Last place</b>\n<b>News Analyst</b>  -0.50%",
                      text)
        self.assertIn("<b>📏 Yardsticks</b>\nSPY +0.50%\nMonkey +2.00%",
                      text)
        self.assertNotIn("(fixed)", text)
        self.assertNotIn("IBKR", text)          # nothing to say about it

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
        text = chart.caption(data, today=TODAY)
        self.assertIn(
            "🥇 <b>Bargain Hunter</b>  +0.20%\n"
            "      ✅ 1.10% ahead of SPY\n"
            "🥈 <b>News Analyst</b>  -0.50%\n"
            "      ✅ 0.60% ahead of SPY since 8 Oct\n"
            "🥉 <b>Trend Follower</b>  +1.00%\n"
            "      ✅ 0.40% ahead of SPY", text)
        self.assertIn("Monkey +2.00% (since 8 Oct)", text)
        # Not trading yet (no same-days figures): last.
        self.assertEqual(chart.ranked(data)[-1]["name"], "AI Learner")
        # The last place shown is the last one already trading.
        data["agents"].append(dict(data["agents"][2], name="News 2",
                                   same_days={"benchmark": {
                                       "from": "2026-10-07",
                                       "difference": -0.02}}))
        self.assertEqual(chart.podium(data)[-1][1]["name"], "News 2")
        self.assertEqual(chart.COLORS["equal_weight"], "#c9ccd1")

    def test_ibkr_result_in_tidy_lines(self):
        text = ("Done: 2 of 3 orders placed; not accepted: EWZ; currency: "
                "bought 1,200 USD; kept in cash: FXI (IBKR does not sell "
                "these to this account).\nWarning: the orders for V sent on "
                "8 Oct did not fill.")
        self.assertEqual(chart.ibkr_lines(text), [
            "⚠️ 2 of 3 orders placed", "❌ Not accepted: EWZ",
            "💱 Currency: bought 1,200 USD",
            "💵 Kept in cash: FXI (IBKR does not sell these to this "
            "account)",
            "⚠️ The orders for V sent on 8 Oct did not fill."])
        self.assertEqual(chart.ibkr_lines("Done: 3 of 3 orders placed."),
                         ["✅ 3 of 3 orders placed"])
        self.assertEqual(chart.ibkr_lines("Done: no orders needed."),
                         ["✅ No orders needed, it already matches"])
        self.assertEqual(chart.ibkr_lines("Morning run failed: no TWS"),
                         ["❌ Morning run failed: no TWS"])
        head = chart.caption(payload(), text, today=TODAY)
        self.assertIn("<b>🏦 IBKR this morning</b>\n⚠️ 2 of 3 orders "
                      "placed\n➕ 4 more in the next message", head)
        self.assertIn("❌ Not accepted: EWZ", chart.details(payload(), text))

    def test_fits_telegram_and_escapes_html(self):
        data = payload()
        for a in data["agents"]:
            a["name"] = a["name"].replace("Bargain", "Bargain <&>")
            a["positions"] = [{"ticker": f"T{i}", "value_chf": 9_000.0,
                               "pnl_pct": 0.01} for i in range(40)]
            a["trades"] = [{"date": "2026-10-09", "side": "BUY",
                            "ticker": f"T{i}", "quantity": 1,
                            "value_chf": 9_000.0, "pnl_chf": None,
                            "reason": "x" * 200} for i in range(40)]
            a["pending_orders"] = [{"side": "BUY", "ticker": f"T{i}",
                                    "reason": "y" * 200} for i in range(40)]
        head = chart.caption(data, "Done: 1 of 1 orders placed; kept in "
                             "cash: " + "Z, " * 300, today=TODAY)
        more = chart.details(data, "Warning: " + "w" * 900)
        self.assertLessEqual(len(chart.visible(head)), chart.CAPTION_LIMIT)
        self.assertLessEqual(len(chart.visible(more)), chart.TELEGRAM_LIMIT)
        self.assertIn("Bargain &lt;&amp;&gt; Hunter", more)
        self.assertNotIn("<&>", more)

    def test_labels_keep_apart(self):
        self.assertEqual(chart.spread([1.0, 5.0], 1.0), [1.0, 5.0])
        a, b, c = sorted(chart.spread([0.0, 0.1, 0.2], 1.0))
        self.assertAlmostEqual(b - a, 1.0)
        self.assertAlmostEqual(c - b, 1.0)

    def test_details_explain_the_top_three_and_the_last(self):
        text = chart.details(payload())
        self.assertTrue(text.startswith("<b>🔎 The details · close of "
                                        "Fri 9 Oct</b>"))
        self.assertIn("🥇 <b>Trend Follower</b>  +1.00%\n<i>Buys markets "
                      "in a steady rise", text)
        self.assertIn("💼 <b>Holds</b> 75% invested · 25% cash\n"
                      "▸ <b>MA</b> · 30% of the account · 📈 +2.1%\n"
                      "   <i>in a steady rise, bought 8 Oct</i>\n"
                      "▸ <b>V</b> · 20% of the account · 📉 -1.0%\n", text)
        self.assertIn("⏭️ <b>Next open</b>\n🔴 Sell <b>V</b>\n"
                      "   <i>Down-trend</i>", text)
        self.assertIn("🥉 <b>AI Learner</b>", text)
        self.assertIn("💼 <b>Holds</b> nothing yet, all cash\n\n"
                      "⏭️ <b>Next open</b> nothing planned", text)
        self.assertIn("🔻 <b>Last place: News Analyst</b>", text)
        self.assertNotIn("Monkey", text)
        self.assertNotIn("(fixed)", text)
        self.assertTrue(text.endswith("https://vanguard3.xyz/"))

    def test_only_big_trades_get_a_reason(self):
        data = payload()
        big = {"date": "2026-10-09", "session": "open", "side": "BUY",
               "ticker": "NESN.SW", "quantity": 80, "value_chf": 7_250.0,
               "pnl_chf": None, "reason": "Oversold, RSI 28.3"}
        sale = {"date": "2026-10-09", "session": "midday", "side": "SELL",
                "ticker": "ROG.SW", "quantity": 20, "value_chf": 6_000.0,
                "pnl_chf": -32.6, "reason": "Reverted to 20-day mean"}
        small = dict(big, ticker="ABB.SW", value_chf=900.0)
        old = dict(big, date="2026-10-08", ticker="UBSG.SW")
        for a in data["agents"]:
            if a["key"] == "reversion":
                a["trades"] = [old, small, big, sale]
        text = chart.details(data)
        self.assertIn("🔁 <b>Traded on 9 Oct</b>\n"
                      "🟢 Bought 80 <b>NESN.SW</b> · 7,250 CHF\n"
                      "   <i>fell sharply and looks cheap</i>\n"
                      "🔴 Sold 20 <b>ROG.SW</b> at midday · 6,000 CHF · "
                      "❌ -33 CHF on it\n"
                      "   <i>recovered to its usual price</i>\n"
                      "➕ 1 smaller trade (under 5% of the account)", text)
        self.assertNotIn("ABB.SW", text)
        self.assertNotIn("UBSG.SW", text)           # an earlier day

    def test_the_older_script_gets_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            results = tmp / "paper.json"
            results.write_text(json.dumps(payload()))
            argv = ["telegram_chart.py", str(tmp / "race.png"),
                    "--results", str(results), "--why", str(tmp / "why"),
                    "--trades", str(tmp / "trades")]
            out = io.StringIO()
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(chart, "draw"), \
                    contextlib.redirect_stdout(out):
                chart.main()
            self.assertTrue(out.getvalue().startswith("📊 Vanguard3 · "))
            self.assertNotIn("<b>", (tmp / "why").read_text())
            self.assertIn("vanguard3.xyz", (tmp / "trades").read_text())

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
