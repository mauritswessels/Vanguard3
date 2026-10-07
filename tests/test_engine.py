"""Engine correctness tests. Run with ``python -m unittest discover tests``.

All tests use synthetic data, so they run offline and deterministically.
"""

import math
import unittest

import numpy as np
import pandas as pd

import config
from data_manager import SyntheticProvider, clean_bars, load_market_data
from engine import metrics
from engine.broker import Order, SimulatedBroker
from engine.portfolio import CostModel, InsufficientFundsError, Portfolio
from main import build_accounts, run_simulation
from models import ReversionAgent, TrendAgent, VolatilityAgent
from models import indicators as ind

D1 = pd.Timestamp("2025-01-06")
D2 = pd.Timestamp("2025-01-07")


def synthetic_market(days=730, seed=1):
    end = pd.Timestamp("2026-06-30")
    return load_market_data("synthetic", end - pd.Timedelta(days=days), end,
                            cache_dir=None, seed=seed)


class PortfolioAccountingTest(unittest.TestCase):

    def test_buy_charges_slippage_fx_and_commission(self):
        pf = Portfolio("t", 100_000)
        pf.buy(D1, "AAPL", "USD", 10, 200.0, 0.9)
        unit = 200.0 * (1 + 5e-4) * 0.9 * (1 + 2e-4)
        self.assertAlmostEqual(pf.cash, 100_000 - 10 * unit - 2.0, places=9)
        self.assertEqual(pf.quantity("AAPL"), 10)
        self.assertAlmostEqual(pf.positions["AAPL"].cost_basis_chf,
                               10 * unit + 2.0, places=9)

    def test_chf_asset_has_no_fx_spread(self):
        pf = Portfolio("t", 10_000)
        pf.buy(D1, "NESN.SW", "CHF", 10, 100.0, 1.0)
        self.assertAlmostEqual(pf.cash, 10_000 - 10 * 100.0 * 1.0005 - 2.0)

    def test_round_trip_at_flat_price_loses_exactly_costs(self):
        pf = Portfolio("t", 50_000)
        buy = pf.buy(D1, "SPY", "USD", 20, 500.0, 0.85)
        sell = pf.sell(D2, "SPY", 20, 500.0, 0.85)
        total_costs = sum(t.commission_chf + t.slippage_chf + t.fx_cost_chf
                          for t in (buy, sell))
        self.assertAlmostEqual(sell.realized_pnl_chf, -total_costs, places=6)
        self.assertAlmostEqual(pf.cash, 50_000 - total_costs, places=6)
        self.assertFalse(pf.positions)

    def test_partial_sell_keeps_average_cost(self):
        pf = Portfolio("t", 50_000)
        pf.buy(D1, "GLD", "USD", 10, 100.0, 1.0)
        avg = pf.positions["GLD"].avg_cost_chf
        pf.sell(D2, "GLD", 4, 100.0, 1.0)
        self.assertEqual(pf.quantity("GLD"), 6)
        self.assertAlmostEqual(pf.positions["GLD"].avg_cost_chf, avg)

    def test_rejects_overdraft_short_and_bad_input(self):
        pf = Portfolio("t", 1_000)
        with self.assertRaises(InsufficientFundsError):
            pf.buy(D1, "SPY", "USD", 10, 500.0, 1.0)
        with self.assertRaises(ValueError):
            pf.sell(D1, "SPY", 1, 500.0, 1.0)
        for qty, px in [(0, 10.0), (-1, 10.0), (1.5, 10.0), (1, float("nan"))]:
            with self.assertRaises(ValueError):
                pf.buy(D1, "SPY", "USD", qty, px, 1.0)
        self.assertEqual(pf.cash, 1_000)

    def test_max_affordable_qty_is_tight(self):
        pf = Portfolio("t", 10_000)
        qty = pf.max_affordable_qty(97.0, 0.88, "USD")
        pf.buy(D1, "X", "USD", qty, 97.0, 0.88)
        self.assertGreaterEqual(pf.cash, 0)
        self.assertLess(pf.cash,
                        CostModel().buy_price_chf(97.0, 0.88, "USD"))


class MetricsTest(unittest.TestCase):

    def test_max_drawdown(self):
        eq = pd.Series([100, 120, 90, 130, 65])
        self.assertAlmostEqual(metrics.max_drawdown(eq), 65 / 130 - 1)

    def test_sharpe_matches_formula(self):
        rets = pd.Series([0.01, -0.005, 0.002, 0.007, -0.001])
        rf = config.RISK_FREE_RATE / 252
        ex = rets - rf
        expected = ex.mean() / ex.std(ddof=1) * math.sqrt(252)
        self.assertAlmostEqual(metrics.sharpe_ratio(rets), expected)

    def test_flat_curve_has_undefined_sharpe(self):
        flat = pd.Series([0.0] * 10)
        self.assertTrue(math.isnan(metrics.sharpe_ratio(flat)))
        self.assertTrue(math.isnan(metrics.sortino_ratio(flat)))


class IndicatorTest(unittest.TestCase):

    def setUp(self):
        end = pd.Timestamp("2025-12-31")
        self.bars = clean_bars(SyntheticProvider(3).fetch(
            "TEST", end - pd.Timedelta(days=600), end))

    def test_indicators_are_causal(self):
        """Values at bar t must not change when future bars are removed."""
        cut = len(self.bars) // 2
        for agent in (TrendAgent(), ReversionAgent(), VolatilityAgent()):
            full = agent.compute_indicators(self.bars)
            part = agent.compute_indicators(self.bars.iloc[:cut])
            pd.testing.assert_frame_equal(full.iloc[:cut], part,
                                          check_exact=False, rtol=1e-10)

    def test_indicator_ranges(self):
        b = self.bars
        r = ind.rsi(b["Close"]).dropna()
        a = ind.adx(b["High"], b["Low"], b["Close"]).dropna()
        self.assertTrue(((r >= 0) & (r <= 100)).all())
        self.assertTrue(((a["adx"] >= 0) & (a["adx"] <= 100)).all())
        self.assertTrue((ind.atr(b["High"], b["Low"], b["Close"]).dropna()
                         > 0).all())
        bb = ind.bollinger_bands(b["Close"]).dropna()
        self.assertTrue((bb["bb_lower"] <= bb["bb_upper"]).all())

    def test_rsi_extremes(self):
        up = pd.Series(np.arange(1.0, 40.0))
        self.assertEqual(ind.rsi(up).iloc[-1], 100.0)
        flat = pd.Series(np.full(40, 5.0))
        self.assertEqual(ind.rsi(flat).iloc[-1], 50.0)

    def test_donchian_excludes_current_bar(self):
        dc = ind.donchian(self.bars["High"], self.bars["Low"], 20)
        i = 50
        self.assertEqual(dc["dc_upper"].iloc[i],
                         self.bars["High"].iloc[i - 20:i].max())


class BrokerTest(unittest.TestCase):

    def test_orders_fill_at_next_open_not_same_day(self):
        market = synthetic_market(days=60)
        d0, d1 = market.calendar[-3], market.calendar[-2]
        pf = Portfolio("t", 100_000)
        broker = SimulatedBroker(pf, market)
        broker.submit(Order("SPY", "BUY", 5, d0))
        self.assertEqual(broker.process(d0), [])          # same day: no fill
        fills = broker.process(d1)
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].date, d1)
        self.assertEqual(fills[0].market_price,
                         market.open_panel.at[d1, "SPY"])

    def test_buy_is_scaled_down_to_available_cash(self):
        market = synthetic_market(days=60)
        d0, d1 = market.calendar[-3], market.calendar[-2]
        pf = Portfolio("t", 1_000)
        broker = SimulatedBroker(pf, market)
        broker.submit(Order("SPY", "BUY", 1_000_000, d0))
        fills = broker.process(d1)
        self.assertTrue(len(fills) <= 1)
        self.assertGreaterEqual(pf.cash, 0)


class BacktestIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic_market(days=800, seed=11)
        cls.start = cls.market.calendar[-1] - pd.Timedelta(days=365)
        cls.accounts = run_simulation(cls.market, cls.start,
                                      build_accounts(cls.market))

    def test_every_agent_trades(self):
        for acc in self.accounts:
            self.assertGreater(len(acc.portfolio.trades), 0, acc.agent.name)

    def test_cash_ledger_reconciles(self):
        for acc in self.accounts:
            pf = acc.portfolio
            flows = sum(t.cash_flow_chf for t in pf.trades)
            self.assertAlmostEqual(pf.initial_cash + flows, pf.cash, places=4)
            self.assertGreaterEqual(pf.cash, -1e-6)

    def test_equity_equals_cash_plus_positions(self):
        last = self.market.calendar[-1]
        prices = self.market.close_chf(last)
        for acc in self.accounts:
            pf = acc.portfolio
            self.assertAlmostEqual(pf.equity_curve.iloc[-1],
                                   pf.cash + pf.market_value(prices),
                                   places=4)

    def test_positions_match_trade_log(self):
        for acc in self.accounts:
            log = acc.portfolio.trade_log()
            signed = np.where(log["side"] == "BUY", 1, -1) * log["quantity"]
            net = signed.groupby(log["ticker"]).sum()
            held = {t: p.quantity for t, p in acc.portfolio.positions.items()}
            self.assertEqual({t: int(q) for t, q in net.items() if q}, held)

    def test_no_trades_before_start(self):
        for acc in self.accounts:
            first = min(t.date for t in acc.portfolio.trades)
            self.assertGreater(first, self.start)

    def test_metrics_are_finite(self):
        for acc in self.accounts:
            stats = acc.portfolio.performance()
            for key in ("final_equity_chf", "total_return", "max_drawdown"):
                self.assertTrue(math.isfinite(stats[key]), key)


if __name__ == "__main__":
    unittest.main()
