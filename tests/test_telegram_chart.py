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
                "stats": {"total_return": end / 100_000 - 1}, **extra}
    return {"start": days[0], "last": days[-1], "agents": [
        agent("trend", "Trend Follower", 101_000.0),
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

    def test_labels_keep_apart(self):
        self.assertEqual(chart.spread([1.0, 5.0], 1.0), [1.0, 5.0])
        a, b, c = sorted(chart.spread([0.0, 0.1, 0.2], 1.0))
        self.assertAlmostEqual(b - a, 1.0)
        self.assertAlmostEqual(c - b, 1.0)

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
