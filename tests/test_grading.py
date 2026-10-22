"""Report cards: every fill graded against SPY, never before its time."""

import unittest

import numpy as np
import pandas as pd

import reporting
from data_manager import MarketData, load_market_data
from engine import grading
from engine.simulator import Simulator, build_accounts
from models import make_agent


def tiny_market(days: int = 40, spy_holiday: int | None = None) -> MarketData:
    """Two CHF markets with known prices: AAA climbs 1 a day from 100 (open
    to close +0.5), SPY climbs 0.1 a day from 50 (open to close +0.05).
    ``spy_holiday`` drops SPY's bar on that day, as on a US holiday."""
    cal = pd.bdate_range("2026-01-05", periods=days)
    step = np.arange(days, dtype=float)

    def bars(open_, gap):
        return pd.DataFrame({"Open": open_, "High": open_ + gap,
                             "Low": open_, "Close": open_ + gap,
                             "Volume": 1.0}, index=cal)

    spy = bars(50 + 0.1 * step, 0.05)
    if spy_holiday is not None:
        spy = spy.drop(cal[spy_holiday])
    return MarketData(bars={"AAA": bars(100 + step, 0.5), "SPY": spy}, fx={},
                      currencies={"AAA": "CHF", "SPY": "CHF"}, source="test")


def fill(m: MarketData, i: int, side: str = "BUY", ticker: str = "AAA",
         midday: bool = False) -> dict:
    day = m.calendar[i]
    return {"date": day.strftime("%Y-%m-%d"), "ticker": ticker, "side": side,
            "decided": day if midday else m.calendar[i - 1], "id": i}


class GradeTest(unittest.TestCase):

    def test_buy_and_sell_are_graded_from_the_open_against_spy(self):
        m = tiny_market()
        o, c = m.open_panel, m.close_panel
        d0, d5, d20 = m.calendar[3], m.calendar[8], m.calendar[23]
        buy, sell = grading.grade_fills([fill(m, 3), fill(m, 3, "SELL")], m,
                                        m.calendar[-1])
        for h, later in ((5, d5), (20, d20)):
            edge = (c.at[later, "AAA"] / o.at[d0, "AAA"]
                    - c.at[later, "SPY"] / o.at[d0, "SPY"])
            self.assertAlmostEqual(buy[f"edge_{h}"], edge, 4)
            self.assertAlmostEqual(sell[f"edge_{h}"], -edge, 4)
        self.assertGreater(buy["edge_5"], 0)          # AAA beat SPY
        self.assertEqual((buy["decided"], buy["fill"]),
                         (m.calendar[2].strftime("%Y-%m-%d"), 3))
        self.assertNotIn("pending", buy)

    def test_a_midday_trade_is_graded_from_that_days_close(self):
        m = tiny_market()
        c = m.close_panel
        d0, d5 = m.calendar[3], m.calendar[8]
        (call,) = grading.grade_fills([fill(m, 3, midday=True)], m,
                                      m.calendar[-1])
        edge = (c.at[d5, "AAA"] / c.at[d0, "AAA"]
                - c.at[d5, "SPY"] / c.at[d0, "SPY"])
        self.assertAlmostEqual(call["edge_5"], edge, 4)

    def test_spy_closed_that_day_counts_from_its_last_close(self):
        m = tiny_market(spy_holiday=3)
        o, c = m.open_panel, m.close_panel
        d0, d5 = m.calendar[3], m.calendar[8]
        (call,) = grading.grade_fills([fill(m, 3)], m, m.calendar[-1])
        edge = (c.at[d5, "AAA"] / o.at[d0, "AAA"]
                - c.at[d5, "SPY"] / c.at[m.calendar[2], "SPY"])
        self.assertAlmostEqual(call["edge_5"], edge, 4)

    def test_a_call_is_never_graded_before_its_window_has_passed(self):
        m = tiny_market()
        cal, f = m.calendar, [fill(m, 3)]
        self.assertEqual(grading.grade_fills(f, m, cal[2]), [])   # not yet made
        for k in range(3, 3 + 25):
            (call,) = grading.grade_fills(f, m, cal[k])
            self.assertEqual("edge_5" in call, k >= 3 + 5, k)
            self.assertEqual("edge_20" in call, k >= 3 + 20, k)
            self.assertEqual(call.get("pending", False), k < 3 + 5, k)

    def test_later_prices_never_change_a_grade(self):
        """Grading as of a day gives the same answer whether or not the
        data runs on past that day."""
        m = load_market_data("synthetic", pd.Timestamp("2025-01-01"),
                             pd.Timestamp("2025-06-30"), cache_dir=None, seed=4)
        cal = m.calendar
        fills = [fill(m, i, side, t) for i, side, t in
                 ((10, "BUY", "AAPL"), (30, "SELL", "AAPL"), (60, "BUY", "GLD"),
                  (80, "BUY", "NESN.SW"), (95, "SELL", "GLD"))]
        for k in (40, 65, 85, 100):
            self.assertEqual(grading.grade_fills(fills, m, cal[k]),
                             grading.grade_fills(fills, m.until(cal[k]), cal[k]))

    def test_spy_itself_and_missing_markets_are_not_graded(self):
        m = tiny_market()
        calls = grading.grade_fills(
            [fill(m, 3, ticker="SPY"), fill(m, 3, ticker="GONE.SW")], m,
            m.calendar[-1])
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertNotIn("edge_5", call)
            self.assertNotIn("pending", call)


class CardTest(unittest.TestCase):

    def test_card_counts_rates_and_recent_calls(self):
        calls = [{"date": f"2026-01-{i + 1:02d}", "ticker": "AAA",
                  "side": "BUY" if i % 2 else "SELL", "decided": None,
                  "edge_5": e, "edge_20": e / 2}
                 for i, e in enumerate([0.02, -0.01, 0.03, 0.04] * 6)]
        calls.append({"date": "2026-02-01", "ticker": "AAA", "side": "BUY",
                      "decided": None, "pending": True})
        card = grading.report_card(calls)
        self.assertEqual((card["calls"], card["pending"]), (25, 1))
        self.assertEqual(card["graded_5"], 24)
        self.assertEqual(card["hit_rate_5"], 0.75)
        self.assertEqual(card["avg_edge_5"], 0.02)
        self.assertEqual(card["median_edge_5"], 0.025)
        self.assertEqual(card["avg_edge_20"], 0.01)
        self.assertEqual(card["by_side"]["buy"]["hit_rate_5"], 0.5)
        self.assertEqual(card["by_side"]["sell"]["hit_rate_5"], 1.0)
        self.assertEqual(len(card["recent"]), grading.RECENT_CALLS)
        self.assertEqual(card["recent"][-1]["date"], "2026-01-24")
        empty = grading.report_card([])
        self.assertEqual((empty["graded_5"], empty["hit_rate_5"]), (0, None))

    def test_summary_ranks_accounts_and_pools_calls(self):
        a = [{"side": "BUY", "edge_5": 0.01}, {"side": "BUY", "edge_5": -0.03}]
        b = [{"side": "SELL", "edge_5": 0.02}]
        s = grading.summary([("a", "A", a), ("b", "B", b), ("c", "C", [])],
                            pd.Timestamp("2026-10-19"))
        self.assertEqual([r["id"] for r in s["accounts"]], ["b", "a", "c"])
        self.assertEqual(s["accounts"][1]["hit_rate_5"], 0.5)
        self.assertEqual(s["pooled"]["graded_5"], 3)
        self.assertEqual((s["as_of"], s["horizons"]), ("2026-10-19", [5, 20]))


def call(p, side, edge=None):
    c = {"date": "2026-01-05", "ticker": "AAA", "side": side,
         "decided": None, "probability": p}
    if p is None:
        del c["probability"]
    if edge is None:
        c["pending"] = True
    else:
        c["edge_5"] = edge
    return c


class CalibrationTest(unittest.TestCase):
    """Stated chances of beating SPY against what happened (5 days)."""

    def test_brier_score_buckets_and_base_rate(self):
        calls = [call(0.9, "BUY", 0.02),      # beat SPY: came true
                 call(0.7, "BUY", -0.01),     # lagged
                 call(0.65, "BUY", 0.03),
                 call(0.2, "SELL", 0.01),     # a right sell: it lagged SPY
                 call(0.3, "SELL", -0.02),    # a wrong sell: it beat SPY
                 call(0.5, "BUY", 0.0),       # level is not beating
                 call(1.0, "BUY", 0.05),
                 call(0.8, "BUY"),            # stated, not scored yet
                 call(None, "BUY", 0.04)]     # no probability: left out
        c = grading.calibration(calls)
        self.assertEqual((c["horizon"], c["stated"], c["scored"]), (5, 8, 7))
        squares = [0.1 ** 2, 0.7 ** 2, 0.35 ** 2, 0.2 ** 2, 0.7 ** 2,
                   0.5 ** 2, 0.0]
        self.assertAlmostEqual(c["brier"], sum(squares) / 7, 4)
        self.assertAlmostEqual(c["avg_probability"], 4.25 / 7, 3)
        self.assertAlmostEqual(c["base_rate"], 4 / 7, 3)
        self.assertAlmostEqual(c["base_rate_brier"], 12 / 49, 4)
        self.assertAlmostEqual(c["skill"], 1 - (sum(squares) / 7) / (12 / 49), 3)
        table = [(b["from"], b["to"], b["count"], b["avg_probability"],
                  b["came_true"]) for b in c["buckets"]]
        expected = [(0.0, 0.4, 2, 0.25, 0.5), (0.4, 0.6, 1, 0.5, 0.0),
                    (0.6, 0.8, 2, 0.675, 0.5), (0.8, 1.0, 2, 0.95, 1.0)]
        for row, want in zip(table, expected):
            self.assertEqual(row[:3], want[:3])
            self.assertAlmostEqual(row[3], want[3], 3)
            self.assertAlmostEqual(row[4], want[4], 3)
        self.assertEqual(len(table), 4)

    def test_no_probabilities_no_table(self):
        self.assertIsNone(grading.calibration([call(None, "BUY", 0.02)]))
        self.assertIsNone(grading.report_card([])["calibration"])
        pending = grading.calibration([call(0.6, "BUY")])
        self.assertEqual((pending["stated"], pending["scored"]), (1, 0))
        self.assertIsNone(pending["brier"])
        self.assertEqual([b["count"] for b in pending["buckets"]], [0] * 4)
        # Every call came true: no base-rate spread to compare with.
        sure = grading.calibration([call(0.9, "BUY", 0.01)])
        self.assertEqual((sure["base_rate_brier"], sure["skill"]), (0.0, None))

    def test_nothing_is_scored_before_its_window_has_passed(self):
        m = tiny_market()
        f = fill(m, 3)
        f["decision"] = {"details": {"probability": 0.7}}
        unstated = fill(m, 4)
        unstated["decision"] = {"details": {"probability": None}}
        for k in range(4, 3 + 12):
            calls = grading.grade_fills([f, unstated], m, m.calendar[k])
            self.assertEqual(calls[0]["probability"], 0.7)
            self.assertNotIn("probability", calls[-1])
            c = grading.report_card(calls)["calibration"]
            self.assertEqual(c["stated"], 1)
            self.assertEqual(c["scored"], int(k >= 3 + 5), k)
        self.assertEqual(c["brier"], round(0.3 ** 2, 4))   # AAA beat SPY

    def test_later_prices_never_change_the_table(self):
        m = load_market_data("synthetic", pd.Timestamp("2025-01-01"),
                             pd.Timestamp("2025-06-30"), cache_dir=None, seed=4)
        cal = m.calendar
        fills = []
        for i, side, t, p in ((10, "BUY", "AAPL", 0.7), (30, "SELL", "AAPL", 0.4),
                              (60, "BUY", "GLD", 0.55), (80, "BUY", "NESN.SW", 0.9),
                              (95, "SELL", "GLD", 0.2)):
            f = fill(m, i, side, t)
            f["decision"] = {"details": {"probability": p}}
            fills.append(f)
        for k in (40, 65, 85, 100):
            now = grading.grade_fills(fills, m.until(cal[k]), cal[k])
            self.assertEqual(grading.calibration(grading.grade_fills(
                fills, m, cal[k])), grading.calibration(now))


class PayloadCardTest(unittest.TestCase):

    def test_every_account_has_a_report_card(self):
        market = load_market_data("synthetic", pd.Timestamp("2025-06-01"),
                                  pd.Timestamp("2026-06-30"), cache_dir=None,
                                  seed=3)
        sim = Simulator(market, build_accounts(
            market, [make_agent("trend"), make_agent("benchmark")]))
        days = market.calendar[-120:]
        sim.run(days)
        p = reporting.dashboard_payload(sim, "paper", days[0])
        trend, bench = p["agents"]
        self.assertGreater(trend["report_card"]["graded_5"], 0)
        self.assertEqual(trend["report_card"]["calls"], len(trend["trades"]))
        last = market.calendar.get_loc(sim.last_date)
        for call in trend["report_card"]["recent"]:
            # Graded only once 5 sessions after the fill day were known.
            self.assertLessEqual(
                market.calendar.get_loc(pd.Timestamp(call["date"])) + 5, last)
            self.assertEqual(trend["trades"][call["fill"]]["date"], call["date"])
        self.assertEqual(bench["report_card"]["graded_5"], 0)   # only SPY
        self.assertIsNone(trend["report_card"]["calibration"])  # states none
        self.assertEqual({r["id"] for r in p["report_cards"]["accounts"]},
                         {"trend", "benchmark"})


if __name__ == "__main__":
    unittest.main()
