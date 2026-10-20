"""The dashboard file: everything the page needs, and no more."""

import unittest

import pandas as pd

import reporting
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent


class SlimTest(unittest.TestCase):

    def test_activity_keeps_what_the_feed_shows(self):
        day = {"date": "2026-10-19", "fills": [], "orders": [],
               "signals": [{"ticker": "SPY", "action": "BUY", "reason": "r",
                            "ordered": True, "score": 0.4, "check": "c",
                            "details": {"factors": [1, 2, 3]}}]}
        slim = reporting._slim_day(day)
        self.assertEqual(slim["signals"], [{"ticker": "SPY", "action": "BUY",
                                            "reason": "r", "ordered": True}])
        self.assertIn("details", day["signals"][0])          # untouched

    def test_old_trades_drop_their_details(self):
        rows = [{"date": "2026-01-05", "decision": {"reason": "r", "check": "c",
                                                    "details": {"headlines": ["h"]}}},
                {"date": "2026-10-19", "decision": {"reason": "r",
                                                    "details": {"headlines": ["h"]}}},
                {"date": "2026-01-05", "decision": None}]
        out = reporting._slim_trades(rows, pd.Timestamp("2026-10-19"))
        self.assertEqual(out[0]["decision"], {"reason": "r", "check": "c"})
        self.assertIn("details", out[1]["decision"])
        self.assertIsNone(out[2]["decision"])

    def test_round_trips_name_their_fills(self):
        rows = [{"id": 0, "side": "BUY"}, {"id": 1, "side": "SELL"},
                {"id": 2, "side": "SELL"}]
        trip = {"fills": [0, 1, 2], "entry": {"reason": "in"},
                "exit": {"reason": "out"}, "ticker": "SPY"}
        out = reporting._by_reference(trip, rows)
        self.assertEqual((out["entry_fill"], out["exit_fill"]), (0, 2))
        self.assertNotIn("entry", out)
        self.assertNotIn("exit", out)


class PayloadTest(unittest.TestCase):

    def test_paper_payload(self):
        market = load_market_data("synthetic", pd.Timestamp("2025-06-01"),
                                  pd.Timestamp("2026-06-30"), cache_dir=None,
                                  seed=3)
        sim = Simulator(market, build_accounts(market, [make_agent("benchmark")]))
        days = market.calendar[-80:]
        sim.run(days)
        p = reporting.dashboard_payload(sim, "paper", days[0])
        a = p["agents"][0]
        self.assertTrue(a["trips"])
        self.assertEqual(a["trips"][0]["entry_fill"], 0)
        self.assertNotIn("entry", a["trips"][0])
        self.assertLessEqual(len(a["activity"]), reporting.ACTIVITY_DAYS)
        self.assertEqual(a["events"], [])


if __name__ == "__main__":
    unittest.main()
