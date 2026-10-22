"""Midday news check: opening fills, live trades, closed markets wait,
delayed markets trade at the close."""

import json
import unittest

import pandas as pd

import config
import news
from data_manager import load_market_data
from engine import journal
from engine.simulator import Simulator, build_accounts
from midday_news import midday_check
from models import make_agent
from tests.test_news_agent import fake_brief


def decider(targets, notes):
    def decide(brief, holdings, cash, model, max_w, max_total, note=""):
        notes.append(note)
        text = json.dumps({"market_view": "calm", "targets": {
            t: {"weight": w, "reason": "test"} for t, w in targets.items()}})
        return news.parse_decision(text, list(brief["markets"]),
                                   max_w, max_total)
    return decide


class MiddayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        full = load_market_data("synthetic", pd.Timestamp("2024-06-01"),
                                pd.Timestamp("2025-03-31"), seed=5)
        cls.evening, cls.today = full.calendar[-2], full.calendar[-1]
        cls.full = full
        cls.before = load_market_data("synthetic", pd.Timestamp("2024-06-01"),
                                      cls.evening, seed=5)
        for m in (cls.full, cls.before):
            m.source = "test"

    def evening_sim(self, notes, targets=None):
        agent = make_agent("news")
        agent.build_brief = fake_brief
        agent.decide = decider(targets or {"SPY": 0.12}, notes)
        sim = Simulator(self.before, build_accounts(self.before, [agent]))
        sim.run(self.before.calendar[-3:])
        return sim

    def quotes(self):
        """SPY and QQQ real-time (Finnhub), NOVN.SW open but about 15
        minutes delayed (Yahoo), NESN.SW closed right now."""
        close = self.before.close_panel.loc[self.evening]
        q = lambda t, live, realtime=False: {
            "open": float(close[t]) * 1.01, "last": float(close[t]) * 1.02,
            "time": "", "live": live, "realtime": realtime}
        return {"SPY": q("SPY", True, True), "QQQ": q("QQQ", True, True),
                "NOVN.SW": q("NOVN.SW", True),
                "NESN.SW": q("NESN.SW", False)}

    def now(self):
        return pd.Timestamp(self.today).tz_localize("UTC") + pd.Timedelta(hours=15)

    def restored(self, sim, targets, notes):
        """The evening run's simulator: the saved state with today's bars."""
        state = json.loads(json.dumps(sim.to_dict()))
        later = Simulator.from_dict(state, self.full)
        later.accounts[0].agent.build_brief = fake_brief
        later.accounts[0].agent.decide = decider(targets, notes)
        return later

    def test_fills_open_orders_then_trades_live_markets_only(self):
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        self.assertEqual([o["ticker"] for o in acc.broker.pending_to_list()],
                         ["SPY"])
        acc.agent.decide = decider(
            {"SPY": 0.12, "QQQ": 0.10, "NESN.SW": 0.10}, notes)
        now = pd.Timestamp(self.today).tz_localize("UTC") + pd.Timedelta(hours=15)
        out = midday_check(sim, now, self.quotes(), {"USD": 0.8, "EUR": 0.93})

        self.assertTrue(out["ok"])
        self.assertIn("MIDDAY CHECK", notes[-1])
        self.assertEqual(out["opening_fills"], 1)
        self.assertEqual(out["waiting"], ["NESN.SW"])
        self.assertEqual(acc.broker.pending, [])
        trades = {(t.ticker, t.side): t for t in acc.portfolio.trades}
        self.assertEqual(set(trades), {("SPY", "BUY"), ("QQQ", "BUY")})
        spy_open = self.quotes()["SPY"]["open"]
        self.assertAlmostEqual(trades["SPY", "BUY"].market_price, spy_open)
        self.assertEqual(acc.activity[-1]["time"], "midday")
        self.assertEqual(acc.agent.status.startswith("Decided"), True)

        # The evening run afterwards: restored state carries on normally.
        state = json.loads(json.dumps(sim.to_dict()))
        later = Simulator.from_dict(state, self.full)
        later.accounts[0].agent.build_brief = fake_brief
        later.accounts[0].agent.decide = decider({"SPY": 0.12, "QQQ": 0.10},
                                                 notes)
        later.step(self.today)
        pf = later.accounts[0].portfolio
        self.assertEqual(set(pf.positions), {"SPY", "QQQ"})
        self.assertEqual(len(pf.trades), 2)        # nothing bought twice
        self.assertEqual(later.accounts[0].agent.midday["trades"], 1)

    def test_midday_sell_and_failed_call(self):
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        acc.agent.decide = decider({}, notes)          # sell everything
        now = pd.Timestamp(self.today).tz_localize("UTC") + pd.Timedelta(hours=15)
        midday_check(sim, now, self.quotes(), {"USD": 0.8})
        sides = [t.side for t in acc.portfolio.trades]
        self.assertEqual(sides, ["BUY", "SELL"])
        self.assertEqual(acc.portfolio.positions, {})

        def broken(*a, **k):
            raise RuntimeError("overloaded")
        acc.agent.decide = broken
        out = midday_check(sim, now, self.quotes(), {"USD": 0.8})
        self.assertFalse(out["ok"])
        self.assertIn("overloaded", out["status"])
        self.assertTrue(acc.agent.status.startswith("Decided"))

    def test_a_split_like_jump_is_left_for_the_evening(self):
        """A price a quarter of last night's is most likely a 4-for-1
        split: the evening run restates the holdings first."""
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        quotes = self.quotes()
        quotes["SPY"] = {**quotes["SPY"], "open": quotes["SPY"]["open"] / 4,
                         "last": quotes["SPY"]["last"] / 4}
        now = pd.Timestamp(self.today).tz_localize("UTC") + pd.Timedelta(hours=15)
        out = midday_check(sim, now, quotes, {"USD": 0.8})
        self.assertEqual(out["opening_fills"], 0)
        self.assertEqual([o.ticker for o in acc.broker.pending], ["SPY"])
        self.assertEqual(acc.portfolio.trades, [])

    def test_a_delayed_market_fills_at_that_days_close(self):
        """A Swiss price at midday is about 15 minutes old and no real order
        can trade at it: the change becomes an order for today's close,
        which the evening run fills at that close before marking the day.
        The midday check only has data up to last night's close, so today's
        close cannot leak into its decision."""
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        targets = {"SPY": 0.12, "NOVN.SW": 0.10}
        acc.agent.decide = decider(targets, notes)
        out = midday_check(sim, self.now(), self.quotes(), {"USD": 0.8})

        self.assertIn("about 15 minutes old", notes[-1])
        self.assertEqual((out["trades"], out["at_close"]), (0, ["NOVN.SW"]))
        self.assertEqual(set(acc.portfolio.positions), {"SPY"})
        [order] = acc.broker.pending
        self.assertEqual((order.ticker, order.side, order.kind, order.created),
                         ("NOVN.SW", "BUY", "close", self.today))
        entry = acc.activity[-1]
        self.assertEqual(entry["orders"], [{"ticker": "NOVN.SW", "side": "BUY",
                                            "quantity": order.quantity,
                                            "at_close": True}])
        [sig] = [s for s in entry["signals"] if s["ticker"] == "NOVN.SW"]
        self.assertTrue(sig["ordered"])
        self.assertIn("today's close", sig["note"])

        # Saved and restored, it is still an order for the close ...
        later = self.restored(sim, targets, notes)
        lacc = later.accounts[0]
        self.assertEqual(lacc.broker.pending_to_list()[0]["kind"], "close")
        # ... and the evening run fills it at today's close, not the open.
        later.step(self.today)
        pf = lacc.portfolio
        buys = [t for t in pf.trades if t.ticker == "NOVN.SW"]
        self.assertEqual(len(buys), 1)              # not bought again
        buy = buys[0]
        bar = self.full.bars["NOVN.SW"].loc[self.today]
        self.assertEqual((buy.date, buy.decided, buy.quantity),
                         (self.today, self.today, order.quantity))
        self.assertAlmostEqual(buy.market_price, bar["Close"])
        self.assertNotAlmostEqual(buy.market_price, bar["Open"])
        # The usual costs: commission and slippage.
        self.assertEqual(buy.commission_chf, config.COMMISSION_PER_TRADE_CHF)
        self.assertAlmostEqual(buy.exec_price,
                               bar["Close"] * (1 + config.SLIPPAGE_BPS / 1e4))
        self.assertEqual(lacc.broker.pending, [])
        self.assertGreaterEqual(pf.cash, 0)
        # Marked after the fill: today's value counts the new holding.
        prices = self.full.close_chf(self.today)
        self.assertAlmostEqual(pf.equity_curve.loc[self.today],
                               pf.equity(prices))
        self.assertIn("NOVN.SW", pf.positions)
        # The site can say "at the close, ordered at midday".
        evening = lacc.activity[-1]
        self.assertNotIn("time", evening)
        [fill] = [f for f in evening["fills"] if f["ticker"] == "NOVN.SW"]
        self.assertTrue(fill["at_close"])
        rows = journal.fills(pf, lacc.activity)
        self.assertEqual({r["ticker"]: r["session"] for r in rows},
                         {"SPY": "open", "NOVN.SW": "close"})
        self.assertEqual(rows[-1]["decision"]["time"], "midday")

    def test_a_us_market_without_a_real_time_price_waits_for_the_close(self):
        """Without Finnhub, US prices come from Yahoo too (delayed)."""
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        quotes = self.quotes()
        quotes["QQQ"] = {**quotes["QQQ"], "realtime": False}
        acc.agent.decide = decider({"SPY": 0.12, "QQQ": 0.10}, notes)
        out = midday_check(sim, self.now(), quotes, {"USD": 0.8})
        self.assertEqual(out["at_close"], ["QQQ"])
        self.assertEqual([(o.ticker, o.kind) for o in acc.broker.pending],
                         [("QQQ", "close")])
        self.assertNotIn("QQQ", acc.portfolio.positions)

    def test_a_sell_at_the_close_pays_for_a_buy_at_the_same_close(self):
        """Nearly fully invested, swapping one Swiss market for another
        needs the sale's money: both trade at the close, sells first."""
        notes = []
        held = {"SPY": 0.15, "QQQ": 0.15, "IWM": 0.15, "DIA": 0.15,
                "VGK": 0.15, "NOVN.SW": 0.15}
        sim = self.evening_sim(notes, held)
        acc = sim.accounts[0]
        close = self.before.close_panel.loc[self.evening]
        quotes = {t: {"open": float(close[t]), "last": float(close[t]),
                      "time": "", "live": True,
                      "realtime": not t.endswith(".SW")} for t in held}
        quotes["UBSG.SW"] = {**quotes["NOVN.SW"],
                             "open": float(close["UBSG.SW"]),
                             "last": float(close["UBSG.SW"])}
        swap = {**held, "NOVN.SW": 0.0, "UBSG.SW": 0.15}
        acc.agent.decide = decider(swap, notes)
        fx_now = self.before.fx_close.loc[self.evening].to_dict()
        out = midday_check(sim, self.now(), quotes, fx_now)
        self.assertEqual(out["opening_fills"], 6)
        self.assertEqual(sorted(out["at_close"]), ["NOVN.SW", "UBSG.SW"])
        orders = {o.ticker: o for o in acc.broker.pending}
        self.assertEqual({t: o.side for t, o in orders.items()},
                         {"NOVN.SW": "SELL", "UBSG.SW": "BUY"})
        # The buy is bigger than the cash there is before the sale.
        cost = orders["UBSG.SW"].quantity * float(close["UBSG.SW"])
        self.assertGreater(cost, acc.portfolio.cash)

        later = self.restored(sim, swap, notes)
        later.step(self.today)
        pf = later.accounts[0].portfolio
        closing = [t for t in pf.trades if t.decided == self.today]
        self.assertEqual([(t.ticker, t.side) for t in closing],
                         [("NOVN.SW", "SELL"), ("UBSG.SW", "BUY")])
        self.assertNotIn("NOVN.SW", pf.positions)
        self.assertGreater(pf.positions["UBSG.SW"].quantity, 0)
        self.assertGreaterEqual(pf.cash, 0)

    def test_a_second_check_the_same_day_replaces_its_close_orders(self):
        """A manual re-run must not order the same market twice."""
        notes = []
        sim = self.evening_sim(notes)
        acc = sim.accounts[0]
        acc.agent.decide = decider({"SPY": 0.12, "NOVN.SW": 0.10}, notes)
        midday_check(sim, self.now(), self.quotes(), {"USD": 0.8})
        first = acc.broker.pending[0].quantity
        midday_check(sim, self.now(), self.quotes(), {"USD": 0.8})
        self.assertEqual([(o.ticker, o.quantity) for o in acc.broker.pending],
                         [("NOVN.SW", first)])
        # The opening fills are not repeated either.
        self.assertEqual(len(acc.portfolio.trades), 1)

    def test_each_news_agent_checks_its_own_account(self):
        notes = []
        news_agent = make_agent("news")
        opus = make_agent("news_opus")
        for agent, targets in ((news_agent, {"SPY": 0.12}),
                               (opus, {"QQQ": 0.10})):
            agent.build_brief = fake_brief
            agent.decide = decider(targets, notes)
        sim = Simulator(self.before,
                        build_accounts(self.before, [news_agent, opus]))
        sim.run(self.before.calendar[-3:])
        now = pd.Timestamp(self.today).tz_localize("UTC") + pd.Timedelta(hours=15)
        for key in ("news", "news_opus"):
            self.assertTrue(midday_check(sim, now, self.quotes(),
                                         {"USD": 0.8}, key)["ok"])
        held = [set(a.portfolio.positions) for a in sim.accounts]
        self.assertEqual(held, [{"SPY"}, {"QQQ"}])
        self.assertIsNotNone(opus.midday)


class FinnhubQuoteTest(unittest.TestCase):
    def test_parse_quote(self):
        from finnhub_feed import parse_quote
        now = pd.Timestamp("2026-10-08 15:00", tz="UTC")
        t = int(pd.Timestamp("2026-10-08 14:59", tz="UTC").timestamp())
        q = parse_quote({"c": 101.0, "o": 100.0, "pc": 99.0, "t": t}, now, 45)
        self.assertEqual((q["open"], q["last"], q["live"]), (100.0, 101.0, True))
        old = int(pd.Timestamp("2026-10-07 20:00", tz="UTC").timestamp())
        q = parse_quote({"c": 99.0, "o": 98.0, "t": old}, now, 45)
        self.assertIsNone(q["open"])
        self.assertFalse(q["live"])
        self.assertIsNone(parse_quote({"c": 0, "t": 0}, now, 45))


if __name__ == "__main__":
    unittest.main()
