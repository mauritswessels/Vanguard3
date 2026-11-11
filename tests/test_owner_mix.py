"""The owner's mix: a watch-only line of fixed shares, scaled to 100,000 CHF."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import config
import owner_mix
from data_manager import MarketData, load_market_data
from learning import paper_lineup
from models import agent_key

MIX = {
    "name": "Test mix",
    "start": "2026-05-04",
    "holdings": {
        "ASML.AS": (0.75, "EUR", "ASML"),
        "AAPL": (3.0, "USD", "Apple"),
        "NESN.SW": (2.5, "CHF", "Nestle"),
    },
}


def synthetic(drop: str | None = None) -> MarketData:
    end = pd.Timestamp("2026-06-30")
    watch = {t: h[1] for t, h in MIX["holdings"].items() if t != drop}
    return load_market_data("synthetic", end - pd.Timedelta(days=120), end,
                            watchlist=watch, cache_dir=None, seed=3)


class OwnerMixTest(unittest.TestCase):

    def test_starts_at_capital_and_follows_the_shares_in_chf(self):
        market = synthetic()
        out = owner_mix.build(market, MIX)
        start = pd.Timestamp(out["start"])
        self.assertEqual(start, pd.Timestamp("2026-05-04"))
        self.assertEqual(out["equity"][0], [out["start"], 100_000.0])
        # Any later day: the same shares at that day's CHF prices, times
        # the same scale as on the start day.
        def worth(day):
            return sum(q * market.close_panel.at[day, t]
                       * market.fx_rate(t, day)
                       for t, (q, _, _) in MIX["holdings"].items())
        scale = 100_000 / worth(start)
        last = pd.Timestamp(out["last"])
        self.assertEqual(last, market.calendar[-1])
        self.assertAlmostEqual(out["equity"][-1][1], scale * worth(last),
                               places=1)
        self.assertEqual([d for d, _ in out["equity"]],
                         [d.strftime("%Y-%m-%d") for d in market.calendar
                          if d >= start])
        weights = [h["weight_start"] for h in out["holdings"]]
        self.assertAlmostEqual(sum(weights), 1.0, places=3)
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(out["missing"], [])

    def test_uses_only_prices_up_to_each_day(self):
        market = synthetic()
        full = owner_mix.build(market, MIX)
        cut = pd.Timestamp(full["equity"][20][0])
        part = owner_mix.build(market.until(cut), MIX)
        self.assertEqual(part["equity"], full["equity"][:21])

    def test_a_holding_without_prices_is_named_not_guessed(self):
        out = owner_mix.build(synthetic(drop="AAPL"), MIX)
        self.assertEqual(out["missing"], ["AAPL"])
        self.assertEqual(sorted(h["ticker"] for h in out["holdings"]),
                         ["ASML.AS", "NESN.SW"])
        self.assertEqual(out["equity"][0][1], 100_000.0)

    def test_nothing_before_the_start(self):
        market = synthetic().until(pd.Timestamp("2026-04-01"))
        self.assertIsNone(owner_mix.build(market, MIX))

    def test_main_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(owner_mix.config, "OWNER_MIX", MIX), \
                mock.patch.object(owner_mix, "load_market_data",
                                  lambda *a, **k: synthetic()):
            out = Path(tmp) / "mix.json"
            self.assertEqual(owner_mix.main(["--out", str(out)]), 0)
            data = json.loads(out.read_text())
        self.assertEqual(data["name"], "Test mix")
        self.assertIn("generated_utc", data)

    def test_is_not_an_account(self):
        # Watch only: none of its holdings joins the agents' markets, and
        # it never becomes a competitor.
        self.assertFalse({"IUSC.SW", "DFEU.AS", "TSM"} & set(config.WATCHLIST))
        keys = {agent_key(a) for a in paper_lineup(synthetic())}
        self.assertNotIn("owner_mix", keys)


if __name__ == "__main__":
    unittest.main()
