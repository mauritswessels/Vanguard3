"""The wider yardstick: an equal share of every watched market, bought once."""

import json
import unittest

import pandas as pd

import config
from data_manager import MarketData, load_market_data
from engine.simulator import Simulator, build_accounts
from learning import paper_lineup
from models import make_agent

#: A short watchlist (SPY plus shares in all three currencies).
WATCH = {t: config.WATCHLIST[t] for t in [
    "SPY", "QQQ", "GLD", "TLT", "AAPL", "MSFT", "JPM", "XOM",
    "NESN.SW", "NOVN.SW", "UBSG.SW", "SAP.DE", "MC.PA", "ASML.AS"]}


def synthetic(**changes):
    """Synthetic prices; ``changes`` maps a ticker to a function applied to
    its bars (to fake a holiday or a very dear share)."""
    end = pd.Timestamp("2026-06-30")
    market = load_market_data("synthetic", end - pd.Timedelta(days=200), end,
                              watchlist=WATCH, cache_dir=None, seed=5)
    if not changes:
        return market
    return MarketData(bars={t: changes.get(t, lambda b: b)(b)
                            for t, b in market.bars.items()},
                      fx=market.fx, currencies=market.currencies,
                      source=market.source)


def run(market, days):
    sim = Simulator(market, build_accounts(market,
                                           [make_agent("equal_weight")]))
    sim.run(days)
    return sim, sim.accounts[0]


class EqualWeightTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic()
        cls.days = cls.market.calendar[-60:]
        cls.sim, cls.acc = run(cls.market, cls.days)

    def equal_share(self):
        return config.INITIAL_CAPITAL_CHF * (1 - config.CASH_BUFFER_PCT) / len(WATCH)

    def test_buys_every_market_once_at_the_next_open(self):
        pf = self.acc.portfolio
        self.assertEqual(sorted(pf.positions), sorted(WATCH))
        self.assertEqual(len(pf.trades), len(WATCH))
        self.assertTrue(all(t.side == "BUY" and t.date == self.days[1]
                            for t in pf.trades))
        # It decides on its first evening only; after the fills, nothing.
        self.assertEqual([a["date"] for a in self.acc.activity],
                         [f"{d:%Y-%m-%d}" for d in self.days[:2]])

    def test_holdings_are_as_equal_as_whole_shares_allow(self):
        # Within half a share of an equal share, at the prices it decided on.
        share = self.equal_share()
        close = self.market.close_chf(self.days[0])
        for t, pos in self.acc.portfolio.positions.items():
            unit = float(close[t]) * 1.001
            self.assertLessEqual(abs(pos.quantity * unit - share),
                                 unit / 2 + 5, t)
        # Rounding to the nearest share keeps nearly all of it invested.
        self.assertGreaterEqual(self.acc.portfolio.cash, 0)
        self.assertLess(self.acc.portfolio.cash,
                        0.02 * config.INITIAL_CAPITAL_CHF)

    def test_pays_the_usual_costs(self):
        pf = self.acc.portfolio
        self.assertAlmostEqual(sum(t.commission_chf for t in pf.trades),
                               len(WATCH) * config.COMMISSION_PER_TRADE_CHF)
        self.assertTrue(all(t.slippage_chf > 0 for t in pf.trades))

    def test_a_share_dearer_than_twice_an_equal_share_is_left_out(self):
        dear = lambda b: b * 1000
        market = synthetic(**{"ASML.AS": dear})
        _, acc = run(market, self.days)
        self.assertNotIn("ASML.AS", acc.portfolio.positions)
        self.assertEqual(len(acc.portfolio.positions), len(WATCH) - 1)
        # It does not try again every evening.
        self.assertEqual(len(acc.activity), 2)
        note = {w["ticker"]: w["note"] for w in acc.agent.watch(
            self.days[-1], acc.portfolio)}
        self.assertIn("Left out", note["ASML.AS"])

    def test_a_market_closed_on_its_first_evening_is_bought_later(self):
        first = self.days[0]
        market = synthetic(**{"NESN.SW": lambda b: b.drop(first)})
        _, acc = run(market, self.days)
        pos = acc.portfolio.positions["NESN.SW"]
        self.assertEqual(pos.entry_date, self.days[2])
        value = pos.quantity * float(market.close_chf(self.days[2])["NESN.SW"])
        self.assertGreater(value, 0.8 * self.equal_share())
        self.assertEqual(len(acc.portfolio.positions), len(WATCH))

    def test_save_and_restore_changes_nothing(self):
        sim, _ = run(self.market, self.days[:10])
        again = Simulator.from_dict(json.loads(json.dumps(sim.to_dict())),
                                    self.market)
        again.run(self.days[10:])
        a, b = again.accounts[0].portfolio, self.acc.portfolio
        self.assertEqual({t: p.quantity for t, p in a.positions.items()},
                         {t: p.quantity for t, p in b.positions.items()})
        self.assertAlmostEqual(a.cash, b.cash)

    def test_is_a_yardstick_in_the_live_race_and_the_backtests(self):
        agent = make_agent("equal_weight")
        self.assertTrue(agent.benchmark)
        self.assertIn("Buy & Hold All Markets",
                      [a.name for a in paper_lineup(self.market)])
        self.assertIn("equal_weight", config.AGENT_LINEUP)


if __name__ == "__main__":
    unittest.main()
