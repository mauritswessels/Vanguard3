"""Join dates, and every account against the yardsticks over the same days."""

import json
import unittest

import pandas as pd

import config
import reporting
import weekly_report
from data_manager import load_market_data
from engine.simulator import (JOINED_BEFORE_RECORDS, Simulator,
                              build_accounts, joined_before_records)
from models import make_agent

#: A short watchlist (SPY plus shares in all three currencies).
WATCH = {t: config.WATCHLIST[t] for t in [
    "SPY", "QQQ", "GLD", "AAPL", "MSFT", "NESN.SW", "NOVN.SW", "SAP.DE"]}


def synthetic(end="2026-06-30", days=200):
    end = pd.Timestamp(end)
    return load_market_data("synthetic", end - pd.Timedelta(days=days), end,
                            watchlist=WATCH, cache_dir=None, seed=8)


def practising(live_from):
    """The AI Learner, practising without orders until ``live_from``."""
    return make_agent("learner", {"live_from": f"{live_from:%Y-%m-%d}",
                                  "pretrain_years": 0, "pretrain_epochs": 1})


def equity(acc, day):
    return float(acc.portfolio.equity_curve[day])


class JoinedTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic()
        cls.days = cls.market.calendar[-40:]

    def test_accounts_join_on_the_first_session_they_could_trade(self):
        d = self.days
        sim = Simulator(self.market, build_accounts(self.market, [
            make_agent("benchmark"), practising(d[5])]))
        sim.run(d[:10])
        sim.add_account(make_agent("monkey"), d[0])
        self.assertIsNone(sim.accounts[2].joined)
        sim.run(d[10:])
        self.assertEqual([a.joined for a in sim.accounts], [d[0], d[5], d[10]])
        # The days before are filled in with the starting cash.
        self.assertEqual(equity(sim.accounts[2], d[3]),
                         config.INITIAL_CAPITAL_CHF)

    def test_the_ai_learner_joins_when_its_practice_run_ends(self):
        learner = make_agent("learner", {"live_from": "2026-06-01"})
        self.assertFalse(learner.trades_on(pd.Timestamp("2026-05-29")))
        self.assertTrue(learner.trades_on(pd.Timestamp("2026-06-01")))

    def test_join_dates_are_saved(self):
        d = self.days
        sim = Simulator(self.market, build_accounts(self.market, [
            make_agent("benchmark"), practising(d[-1] + pd.Timedelta(days=9))]))
        sim.run(d[:5])
        state = json.loads(json.dumps(sim.to_dict()))
        self.assertEqual([a["joined"] for a in state["accounts"]],
                         [f"{d[0]:%Y-%m-%d}", None])
        again = Simulator.from_dict(state, self.market)
        self.assertEqual([a.joined for a in again.accounts], [d[0], None])

    def test_states_saved_before_join_dates_were_recorded(self):
        """The live accounts that joined late are known by name; every other
        account joined on its first session, or when it could first trade."""
        days = pd.bdate_range("2026-10-07", "2026-10-20")

        def saved(key, name, days=days):
            return {"agent": key, "name": name, "portfolio": {
                "equity": {f"{d:%Y-%m-%d}": 1e5 for d in days}}}

        self.assertEqual(joined_before_records(
            saved("benchmark", "Buy & Hold SPY"), make_agent("benchmark")),
            days[0])
        self.assertEqual(joined_before_records(
            saved("monkey", "Monkey"), make_agent("monkey")),
            pd.Timestamp(JOINED_BEFORE_RECORDS[("monkey", "Monkey")]))
        learner = make_agent("learner", {"live_from": "2026-10-13"})
        self.assertEqual(joined_before_records(
            saved("learner", "AI Learner"), learner),
            pd.Timestamp("2026-10-13"))
        # Outside the dates it covers, the list is ignored.
        early = saved("monkey", "Monkey", pd.bdate_range("2026-03-02",
                                                         "2026-03-10"))
        self.assertEqual(joined_before_records(early, make_agent("monkey")),
                         pd.Timestamp("2026-03-02"))


class SameDaysTest(unittest.TestCase):
    """A late joiner, and an equal-weight yardstick added later still."""

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic()
        d = cls.days = cls.market.calendar[-40:]
        sim = Simulator(cls.market, build_accounts(cls.market, [
            make_agent("trend"), make_agent("benchmark")]))
        sim.run(d[:10])
        sim.add_account(make_agent("monkey"), d[0])
        sim.run(d[10:20])
        sim.add_account(make_agent("equal_weight"), d[0])
        sim.run(d[20:])
        cls.sim = sim
        cls.payload = reporting.dashboard_payload(sim, "paper", d[0])
        cls.agents = {a["id"]: a for a in cls.payload["agents"]}

    def ratio(self, name, start):
        acc = next(a for a in self.sim.accounts if a.agent.name == name)
        return equity(acc, self.days[-1]) / equity(acc, start) - 1

    def test_a_late_joiner_meets_spy_over_its_own_days(self):
        d = self.days
        monkey = self.agents["monkey"]
        self.assertEqual(monkey["joined"], f"{d[10]:%Y-%m-%d}")
        vs = monkey["same_days"]["benchmark"]
        self.assertEqual((vs["from"], vs["to"], vs["days"]),
                         (f"{d[10]:%Y-%m-%d}", f"{d[-1]:%Y-%m-%d}", 29))
        self.assertAlmostEqual(vs["return"], self.ratio("Monkey", d[10]))
        self.assertAlmostEqual(vs["yardstick_return"],
                               self.ratio("Buy & Hold SPY", d[10]))
        self.assertAlmostEqual(vs["difference"],
                               vs["return"] - vs["yardstick_return"])
        self.assertEqual(vs["name"], "Buy & Hold SPY")
        # Its return since the race began counts the days it was not in.
        spy_all = self.ratio("Buy & Hold SPY", d[0])
        self.assertNotAlmostEqual(vs["yardstick_return"], spy_all)

    def test_a_yardstick_that_joined_later_counts_from_its_own_start(self):
        d = self.days
        for i in ("trend", "monkey", "benchmark"):
            vs = self.agents[i]["same_days"]["equal_weight"]
            self.assertEqual(vs["from"], f"{d[20]:%Y-%m-%d}", i)
            self.assertAlmostEqual(vs["yardstick_return"], self.ratio(
                "Buy & Hold All Markets", d[20]))
        trend = self.agents["trend"]["same_days"]
        self.assertEqual(trend["benchmark"]["from"], f"{d[0]:%Y-%m-%d}")
        self.assertEqual(self.payload["yardsticks"], {
            "benchmark": {"name": "Buy & Hold SPY",
                          "joined": f"{d[0]:%Y-%m-%d}"},
            "equal_weight": {"name": "Buy & Hold All Markets",
                             "joined": f"{d[20]:%Y-%m-%d}"}})

    def test_a_yardstick_is_not_compared_with_itself(self):
        self.assertIsNone(self.agents["benchmark"]["same_days"]["benchmark"])
        ew = self.agents["equal_weight"]["same_days"]
        self.assertIsNone(ew["equal_weight"])
        self.assertIsNotNone(ew["benchmark"])

    def test_the_old_fields_stay(self):
        trend = self.agents["trend"]
        for field in ("id", "key", "name", "benchmark", "stats", "equity",
                      "positions", "trades", "activity", "watch"):
            self.assertIn(field, trend)
        self.assertEqual(trend["equity"][0][0], f"{self.days[0]:%Y-%m-%d}")

    def test_no_comparison_before_an_account_joins(self):
        d = self.days
        sim = Simulator(self.market, build_accounts(self.market, [
            make_agent("benchmark"), practising(d[-1] + pd.Timedelta(days=9))]))
        sim.run(d)
        waiting = reporting.dashboard_payload(sim, "paper", d[0])["agents"][1]
        self.assertIsNone(waiting["joined"])
        self.assertEqual(waiting["same_days"],
                         {"benchmark": None, "equal_weight": None})

    def test_the_weekly_report_gets_the_same_days(self):
        facts = {a["name"]: a for a in weekly_report.week_facts(
            self.payload)["agents"]}
        monkey = facts["Monkey"]
        self.assertEqual(monkey["joined"], f"{self.days[10]:%Y-%m-%d}")
        self.assertEqual(set(monkey["same_days"]),
                         {"Buy & Hold SPY", "Buy & Hold All Markets"})
        self.assertEqual(monkey["same_days"]["Buy & Hold SPY"]["from"],
                         f"{self.days[10]:%Y-%m-%d}")


if __name__ == "__main__":
    unittest.main()
