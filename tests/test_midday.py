"""Midday news check: opening fills, live trades, closed markets wait."""

import json
import unittest

import pandas as pd

import news
from data_manager import load_market_data
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

    def evening_sim(self, notes):
        agent = make_agent("news")
        agent.build_brief = fake_brief
        agent.decide = decider({"SPY": 0.12}, notes)
        sim = Simulator(self.before, build_accounts(self.before, [agent]))
        sim.run(self.before.calendar[-3:])
        return sim

    def quotes(self):
        close = self.before.close_panel.loc[self.evening]
        q = lambda t, live: {"open": float(close[t]) * 1.01,
                             "last": float(close[t]) * 1.02,
                             "time": "", "live": live}
        return {"SPY": q("SPY", True), "QQQ": q("QQQ", True),
                "NESN.SW": q("NESN.SW", False)}

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


if __name__ == "__main__":
    unittest.main()
