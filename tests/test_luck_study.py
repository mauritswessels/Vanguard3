"""Skill or luck: the statistics, and both parts on synthetic data."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import config
import luck_study as ls
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from models import make_agent
from reporting import write_json
from walk_forward import make_folds

#: Small settings so the tests stay quick.
S = {**config.LUCK_PARAMS, "monkeys": 40, "years": 1, "resamples": 400}

#: A short watchlist (SPY plus shares in all three currencies).
WATCH = {t: config.WATCHLIST[t] for t in [
    "SPY", "QQQ", "GLD", "TLT", "AAPL", "MSFT", "JPM", "XOM",
    "NESN.SW", "NOVN.SW", "UBSG.SW", "SAP.DE", "MC.PA", "ASML.AS"]}


def synthetic(days=900, seed=4):
    end = pd.Timestamp("2026-06-30")
    return load_market_data("synthetic", end - pd.Timedelta(days=days), end,
                            watchlist=WATCH, cache_dir=None, seed=seed)


class StatisticsTest(unittest.TestCase):
    def test_holm_scales_the_smallest_p_by_the_number_of_tests(self):
        self.assertEqual(ls.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])
        self.assertEqual(ls.holm([0.5, None]), [0.5, None])
        self.assertEqual(ls.holm([0.6, 0.7]), [1.0, 1.0])

    def test_block_bootstrap_is_repeatable_and_centred(self):
        x = np.random.default_rng(1).normal(0.001, 0.01, 500)
        a = ls.block_means(x, 300, 20, np.random.default_rng(7))
        b = ls.block_means(x, 300, 20, np.random.default_rng(7))
        np.testing.assert_array_equal(a, b)
        self.assertAlmostEqual(a.mean(), x.mean(), delta=0.0005)
        flat = ls.block_means(np.full(50, 0.002), 100, 7,
                              np.random.default_rng(0))
        np.testing.assert_allclose(flat, 0.002)

    def test_a_steady_lead_is_significant_and_noise_is_not(self):
        rng = np.random.default_rng(3)
        steady = ls.lead(rng.normal(0.002, 0.005, 400), S, rng)
        self.assertLess(steady["p"], 0.01)
        self.assertGreater(steady["low"], 0)
        self.assertAlmostEqual(steady["per_year"], 0.002 * 252, delta=0.15)
        noise = ls.lead(rng.normal(0.0, 0.01, 400) - 0.0005, S, rng)
        self.assertGreater(noise["p"], 0.2)
        self.assertIsNone(ls.lead([0.01], S, rng)["p"])

    def test_monkey_rank_counts_the_monkeys_beaten(self):
        beat, p = ls.monkey_rank(0.2, [0.1, 0.0, -0.1, 0.3])
        self.assertEqual(beat, 0.75)
        self.assertEqual(p, 2 / 5)
        self.assertEqual(ls.monkey_rank(1.0, np.zeros(99)), (1.0, 0.01))

    def test_sessions_needed_follows_the_sample_size_rule(self):
        s = {**S, "edge": 0.10, "alpha": 0.05, "power": 0.8}
        one = ls.sessions_needed(0.01, s, 1)
        # (1.645 + 0.842) standard errors of 1% a day for 10% a year.
        self.assertAlmostEqual(one, (2.4865 * 0.01 * 252 / 0.10) ** 2,
                               delta=5)
        self.assertGreater(ls.sessions_needed(0.01, s, 10), one)
        self.assertAlmostEqual(ls.sessions_needed(0.005, s, 1), one / 4)
        self.assertIsNone(ls.sessions_needed(None, s, 1))
        self.assertIsNone(ls.sessions_needed(0.0, s, 1))

    def test_verdict_rules(self):
        s = {**S, "min_days": 20, "alpha": 0.05, "edge": 0.10}
        self.assertEqual(ls.verdict(0.001, 0.5, 10, s), "unclear")
        self.assertEqual(ls.verdict(0.01, 0.5, 100, s), "skill")
        self.assertEqual(ls.verdict(0.4, 0.05, 100, s), "luck")
        self.assertEqual(ls.verdict(0.4, 0.30, 100, s), "unclear")
        self.assertEqual(ls.verdict(None, None, 100, s), "unclear")


class JudgeTest(unittest.TestCase):
    """Made-up daily returns: one agent with a real edge, one monkey-like."""

    def setUp(self):
        rng = np.random.default_rng(11)
        days = pd.bdate_range("2021-01-04", periods=750)
        market = rng.normal(0.0003, 0.01, len(days))
        self.monkeys = pd.DataFrame(
            market[:, None] + rng.normal(0, 0.006, (len(days), 60)),
            index=days)
        self.spy = pd.Series(market + rng.normal(0, 0.002, len(days)),
                             index=days)
        self.skilled = (self.monkeys.mean(axis=1) + 0.0015
                        + pd.Series(rng.normal(0, 0.006, len(days)),
                                    index=days))
        self.lucky = pd.Series(market + rng.normal(0, 0.006, len(days)),
                               index=days)

    def results(self, racers):
        rng = np.random.default_rng(0)
        res = {i: ls.compare(r, self.spy, self.monkeys, S, rng)
               for i, r in racers.items()}
        return res, ls.judge(res, S, list(racers))

    def test_a_real_edge_is_skill_and_a_lucky_draw_is_not(self):
        res, tests = self.results({"skilled": self.skilled,
                                   "lucky": self.lucky})
        self.assertEqual(tests, 2)
        self.assertEqual(res["skilled"]["monkey"]["beat"], 1.0)
        self.assertEqual(res["skilled"]["monkey"]["verdict"], "skill")
        self.assertNotEqual(res["lucky"]["monkey"]["verdict"], "skill")
        self.assertEqual(res["skilled"]["sessions"], 750)
        for part in ("monkey", "spy"):
            self.assertIn(res["lucky"][part]["verdict"], ls.VERDICTS)
            self.assertGreaterEqual(res["lucky"][part]["p_adjusted"],
                                    res["lucky"][part]["p"])

    def test_more_agents_racing_need_a_bigger_lead(self):
        alone, _ = self.results({"lucky": self.lucky})
        crowd, tests = self.results({f"x{i}": self.lucky + 1e-6 * i
                                     for i in range(5)})
        self.assertEqual(tests, 5)
        self.assertGreater(crowd["x0"]["spy"]["p_adjusted"],
                           alone["lucky"]["spy"]["p_adjusted"])
        self.assertGreater(crowd["x0"]["monkey"]["sessions_needed"],
                           alone["lucky"]["monkey"]["sessions_needed"])

    def test_weeks_more_never_drop_below_the_minimum_record(self):
        res, _ = self.results({"short": self.skilled.iloc[:8]})
        part = res["short"]["monkey"]
        self.assertEqual(part["verdict"], "unclear")
        self.assertGreaterEqual(part["weeks_more"],
                                (S["min_days"] - 8) / 5 - 1e-9)


class ReplayTest(unittest.TestCase):
    """Past prices, with one strategy and a one-setting grid to stay quick."""

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic()
        cls.part = ls.replay(cls.market, S, keys=("trend",),
                             grids={"trend": {"adx_threshold": [25.0]}},
                             train_years=1)

    def test_fixed_and_learning_versions_race_the_same_days(self):
        res = self.part["results"]
        self.assertEqual(set(res), {"trend-fixed", "trend", "benchmark",
                                    "monkey"})
        self.assertEqual(self.part["tested"], 2)
        self.assertEqual(len(self.part["monkey_returns"]), S["monkeys"])
        self.assertEqual(res["trend"]["first"], res["trend-fixed"]["first"])
        self.assertEqual(res["trend"]["last"],
                         self.market.calendar[-1].strftime("%Y-%m-%d"))
        self.assertEqual(self.part["names"]["trend-fixed"],
                         "Trend Follower (fixed)")
        # The first counted session is the walk-forward's first blind day.
        cal = self.market.calendar
        blind = cal[cal >= make_folds(cal[-1], 1)[0][0]][0]
        self.assertEqual(res["trend"]["first"], blind.strftime("%Y-%m-%d"))

    def test_yardsticks_are_shown_but_not_judged(self):
        res = self.part["results"]
        self.assertIsNone(res["benchmark"]["spy"])
        self.assertNotIn("verdict", res["monkey"]["monkey"])
        self.assertNotIn("verdict", res["benchmark"]["monkey"])
        self.assertIn(res["trend"]["monkey"]["verdict"], ls.VERDICTS)

    def test_report_is_strict_json_with_plain_words(self):
        report = ls.build_report(self.part, None, S, "synthetic")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "luck.json"
            write_json(report, path)
            data = json.loads(path.read_text())
        self.assertIsNone(data["live"])
        self.assertEqual(data["verdicts"]["unclear"], "can't tell yet")
        rows = {r["id"]: r for r in data["agents"]}
        self.assertTrue(rows["trend-fixed"]["fixed_twin"])
        self.assertTrue(rows["benchmark"]["yardstick"])
        past = rows["trend"]["summary"][0]
        self.assertTrue(past.startswith("Past 1 year:"), past)
        self.assertIn("monkeys", past)
        self.assertEqual([r["id"] for r in data["agents"]][-2:],
                         ["benchmark", "monkey"])


class LiveTest(unittest.TestCase):
    """A saved paper state with a late joiner, judged against fresh monkeys."""

    @classmethod
    def setUpClass(cls):
        cls.market = synthetic(days=500, seed=9)
        cal = cls.market.calendar
        days = cal[cal >= pd.Timestamp("2026-03-02")][:60]
        sim = Simulator(cls.market, build_accounts(cls.market, [
            make_agent("benchmark"), make_agent("trend"),
            make_agent("monkey")]))
        sim.run(days[:30])
        sim.add_account(make_agent("trend", name="Trend Follower (fixed)"),
                        days[0])
        sim.run(days[30:])
        cls.days = days
        cls.state = json.loads(json.dumps(sim.to_dict()))
        cls.s = {**S, "min_days": 40}
        cls.part = ls.live(cls.state, cls.market, cls.s)

    def test_each_account_counts_from_its_first_decision(self):
        res = self.part["results"]
        self.assertEqual(self.part["order"],
                         ["benchmark", "trend", "monkey", "trend-fixed"])
        self.assertEqual(self.part["tested"], 2)
        late = res["trend-fixed"]
        self.assertGreaterEqual(pd.Timestamp(late["since"]), self.days[30])
        self.assertLess(late["sessions"], 30)
        self.assertEqual(res["trend"]["last"],
                         self.days[-1].strftime("%Y-%m-%d"))

    def test_short_records_wait_and_say_how_long(self):
        res = self.part["results"]
        self.assertEqual(res["trend-fixed"]["monkey"]["verdict"], "unclear")
        report = ls.build_report(None, self.part, self.s, "synthetic")
        rows = {r["id"]: r for r in report["agents"]}
        live = rows["trend-fixed"]["summary"][-1]
        self.assertIn("too few to judge", live)
        self.assertIn(f"since {self.days[30].day}", live)
        self.assertTrue(rows["monkey"]["summary"][-1].startswith("Live:"))
        self.assertEqual(list(rows)[-2:], ["benchmark", "monkey"])
        self.assertIsNone(rows["trend"]["history"])

    def test_news_agents_explain_why_there_is_no_replay(self):
        row = {"id": "news", "key": "news", "name": "News Analyst",
               "fixed_twin": False, "yardstick": False,
               "history": None, "live": None}
        self.assertEqual(ls.summary(row, None, None, S), [
            "No replay on past prices: it asks Claude, who already knows "
            "how those years turned out.", "Live: no decisions yet."])


class FoldsTest(unittest.TestCase):
    def test_yearly_folds_tile_up_to_the_end(self):
        end = pd.Timestamp("2026-10-07")
        folds = make_folds(end, 3)
        self.assertEqual(len(folds), 3)
        self.assertEqual(folds[-1][1], end)
        self.assertEqual(folds[0][0], pd.Timestamp("2023-10-08"))
        for (_, hi), (lo, _) in zip(folds[:-1], folds[1:]):
            self.assertEqual(lo - hi, pd.Timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
