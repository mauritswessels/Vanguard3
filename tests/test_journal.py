"""Trade journal: fills keep their decision, positions add up to the account."""

import unittest

import pandas as pd

from engine import journal
from engine.portfolio import Portfolio

D = [pd.Timestamp(x) for x in ("2026-10-05", "2026-10-06", "2026-10-07",
                               "2026-10-08", "2026-10-09")]


class JournalTest(unittest.TestCase):
    def setUp(self):
        pf = Portfolio("Test", 100_000)
        # Two buys (a partial fill, then the rest), one full sell; then a
        # second position that is still open.
        pf.buy(D[1], "SPY", "USD", 10, 500.0, 0.9, "breakout", decided=D[0])
        pf.buy(D[2], "SPY", "USD", 5, 510.0, 0.9, "breakout", decided=D[1])
        pf.sell(D[3], "SPY", 15, 520.0, 0.9, "stop hit", decided=D[2])
        pf.buy(D[4], "GLD", "USD", 20, 200.0, 0.9, "news", decided=D[4])
        for d in D:
            pf.mark_to_market(d, pd.Series({"SPY": 520 * 0.9, "GLD": 205 * 0.9}))
        self.pf = pf
        self.activity = [
            {"date": "2026-10-05", "signals": [{"ticker": "SPY", "action": "BUY", "reason": "breakout",
                                                "ordered": True, "check": "close above channel", "stop": 480.0}]},
            {"date": "2026-10-07", "signals": [{"ticker": "SPY", "action": "SELL", "reason": "stop hit", "ordered": True}]},
            {"date": "2026-10-09", "time": "midday", "signals": [{"ticker": "GLD", "action": "BUY", "reason": "news",
                                                                  "ordered": True, "details": {"target_weight": 0.04}}]},
        ]

    def test_round_trips_add_up(self):
        rows = journal.fills(self.pf, self.activity)
        self.assertEqual([r["session"] for r in rows], ["open", "open", "open", "midday"])
        self.assertEqual(rows[0]["decision"]["check"], "close above channel")
        self.assertEqual(rows[3]["decision"]["details"]["target_weight"], 0.04)
        self.assertIsNone(rows[1]["decision"])         # no signal recorded that day

        prices = pd.Series({"SPY": 520 * 0.9, "GLD": 205 * 0.9})
        trips = journal.round_trips(rows, self.pf.equity_curve, self.pf.positions,
                                    prices, 100_000, D[4])
        spy, gld = trips
        self.assertEqual((spy["status"], spy["quantity"], len(spy["fills"])), ("closed", 15, 3))
        self.assertAlmostEqual(spy["pnl_chf"], self.pf.trades[2].realized_pnl_chf)
        self.assertEqual(spy["holding_days"], 2)
        self.assertEqual(gld["status"], "open")
        # Realised + unrealised = the account's gain.
        gain = self.pf.cash + sum(p.quantity * prices[t] for t, p in self.pf.positions.items()) - 100_000
        self.assertAlmostEqual(spy["pnl_chf"] + gld["pnl_chf"], gain, places=6)

    def test_saved_trades_keep_decided(self):
        again = Portfolio.from_dict(self.pf.to_dict())
        self.assertEqual(again.trades[0].decided, D[0])


if __name__ == "__main__":
    unittest.main()
