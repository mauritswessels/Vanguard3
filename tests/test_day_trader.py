"""The Day Trader: its rules on made-up 5-minute prices, the live run with a
made-up clock, the evening booking, and no look-ahead."""

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pandas as pd

import config
import day_trader
import finnhub_feed
from data_manager import load_market_data
from engine import journal
from engine.broker import SimulatedBroker
from engine.portfolio import Portfolio
from engine.simulator import Simulator, build_accounts
from models import agent_key, make_agent
from models.day_trader_agent import (DayBook, DayRun, check_times,
                                     early_close, entry_deadline, load_book,
                                     save_book, session, slice_day, snapshot)

DAY = "2025-03-31"          # a Monday, New York on summer time (UTC-4)
PREV = "2025-03-28"
FX = 0.9
P = dict(config.DAY_TRADER_PARAMS)


def bar_times(day: str) -> pd.DatetimeIndex:
    open_, close = session(day)
    return pd.date_range(open_, close - pd.Timedelta(minutes=5), freq="5min")


def frame(day: str, closes: list[float], prev: float) -> pd.DataFrame:
    """5-minute bars (indexed by their start, UTC) closing at ``closes``,
    each opening at the close before; the last close repeats to the end."""
    idx = bar_times(day)
    closes = (list(closes) + [closes[-1]] * len(idx))[:len(idx)]
    opens = [prev] + closes[:-1]
    df = pd.DataFrame({"Open": opens, "Close": closes}, index=idx)
    df["High"] = df[["Open", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "Close"]].min(axis=1)
    return df


def path(prev, rng, flat_to: int, then: list[float]) -> list[float]:
    """First half hour moving between ``rng`` (6 bars), flat at the middle
    until bar ``flat_to``, then ``then``."""
    lo, hi = rng
    mid = (lo + hi) / 2
    first = [lo, hi, lo, hi, mid, mid]
    return first + [mid] * (flat_to - 6) + then


def market_bars(spy_up: bool = True) -> dict:
    """The made-up day:

    * AAPL breaks out at 10:35 and reaches its target at 11:30;
    * MSFT breaks out at 10:40 and falls back to its stop at 11:00;
    * NVDA breaks out at 15:30, after the last buy time;
    * JPM breaks out at 10:35 and drifts until the end of the day;
    * KO's opening range is too narrow to trade;
    * SPY rises all day (or falls, with ``spy_up=False``).
    Bar 12 starts at 10:30 and ends at 10:35.
    """
    out = {
        "AAPL": (100.0, path(100.0, (100.2, 101.0), 12,
                             [101.3] * 11 + [103.0])),
        "MSFT": (200.0, path(200.0, (200.4, 202.0), 13,
                             [202.6] * 4 + [200.5])),
        "NVDA": (50.0, path(50.0, (50.1, 50.5), 72, [50.6])),
        "JPM": (150.0, path(150.0, (150.3, 151.5), 12, [151.8])),
        "KO": (60.0, path(60.0, (60.10, 60.11), 12, [60.2])),
    }
    spy = [500.5 + (i * 0.05 if spy_up else -i * 0.05) for i in range(78)]
    bars = {t: pd.concat([frame(PREV, [prev], prev).tail(1),
                          frame(DAY, closes, prev)])
            for t, (prev, closes) in out.items()}
    bars["SPY"] = pd.concat([frame(PREV, [500.0], 500.0).tail(1),
                             frame(DAY, spy, 500.0)])
    fx = pd.Series(FX, index=bars["SPY"].index)
    return {"bars": bars, "fx": fx}


def fresh_account():
    pf = Portfolio("Day Trader")
    broker = SimulatedBroker(pf, day_trader._Currencies(
        config.DAY_TRADER_MARKETS + ["SPY"]))
    return pf, broker


def replayed(data=None, params=None):
    pf, broker = fresh_account()
    book = DayBook(day=DAY, equity=pf.cash, source="replayed")
    run = DayRun(book, pf, broker, {**P, **(params or {})},
                 list(config.DAY_TRADER_MARKETS))
    run.replay(slice_day(data or market_bars(), DAY))
    return run


def summary(fills):
    return [(r["time"], r["ticker"], r["side"]) for r in fills]


class Clock:
    """A made-up clock: waiting moves it on, a quote round takes 50 s."""

    def __init__(self, start):
        self.t = pd.Timestamp(start)

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += pd.Timedelta(seconds=seconds)


def live_feed(clock, data, minutes_late=0):
    """Finnhub stand-in: the quote at the clock's time from the bars."""
    day = slice_day(data, DAY)

    def quotes(tickers):
        q = {t: snapshot(day["bars"].get(t), day["prev_close"].get(t),
                         clock.now()) for t in tickers}
        clock.sleep(50)
        return {t: v for t, v in q.items() if v}
    return quotes


class RulesTest(unittest.TestCase):
    def test_trading_day(self):
        self.assertEqual(session("2025-03-31")[0],
                         pd.Timestamp("2025-03-31 13:30", tz="UTC"))
        self.assertEqual(session("2026-11-04")[1],      # winter time
                         pd.Timestamp("2026-11-04 21:00", tz="UTC"))
        self.assertTrue(early_close("2026-11-27"))      # after Thanksgiving
        self.assertTrue(early_close("2026-12-24"))      # a Thursday
        self.assertFalse(early_close("2027-12-24"))     # a Friday: closed
        self.assertTrue(early_close("2025-07-03"))
        self.assertFalse(early_close("2026-11-26"))
        self.assertEqual(session("2026-11-27")[1],
                         pd.Timestamp("2026-11-27 18:00", tz="UTC"))
        times = check_times("2026-11-04", P)
        self.assertEqual(len(times), 71)                # 10:00 to 15:50
        self.assertEqual(times[0], pd.Timestamp("2026-11-04 15:00", tz="UTC"))
        self.assertEqual(check_times("2026-11-27", P)[-1],
                         pd.Timestamp("2026-11-27 17:50", tz="UTC"))
        self.assertEqual(entry_deadline("2026-11-27", P),
                         pd.Timestamp("2026-11-27 17:00", tz="UTC"))

    def test_breakouts_stops_targets_and_the_close(self):
        run = replayed()
        self.assertEqual(summary(run.book.fills), [
            ("10:35", "AAPL", "BUY"), ("10:35", "JPM", "BUY"),
            ("10:40", "MSFT", "BUY"), ("11:00", "MSFT", "SELL"),
            ("11:30", "AAPL", "SELL"), ("15:50", "JPM", "SELL")])
        reasons = [r["reason"].split(":")[0] for r in run.book.fills
                   if r["side"] == "SELL"]
        self.assertEqual(reasons, ["Stop", "Target", "Day's end"])
        self.assertEqual(run.pf.positions, {})          # in cash overnight
        self.assertTrue(run.pf.cash > 0)
        # Every fill pays the usual costs.
        for t in run.pf.trades:
            self.assertEqual(t.commission_chf, config.COMMISSION_PER_TRADE_CHF)
            self.assertGreater(t.slippage_chf, 0)
            self.assertGreater(t.fx_cost_chf, 0)
        # Sized by risk, at most 20% of the account.
        buy = run.pf.trades[0]
        self.assertLessEqual(buy.gross_chf, 0.2 * 100_000 + 1)
        # Cash adds up.
        flows = sum(t.cash_flow_chf for t in run.pf.trades)
        self.assertAlmostEqual(run.pf.cash, 100_000 + flows, places=6)

    def test_no_buys_while_spy_falls(self):
        run = replayed(market_bars(spy_up=False))
        self.assertEqual(run.book.fills, [])

    def test_limits(self):
        one = replayed(params={"max_positions": 1})
        buys = [r["ticker"] for r in one.book.fills if r["side"] == "BUY"]
        # AAPL leads SPY by more than JPM at 10:35; MSFT waits for room,
        # which AAPL's target sale only makes after MSFT's breakout passed.
        self.assertEqual(buys[0], "AAPL")
        self.assertEqual(len({r["ticker"] for r in one.book.fills}),
                         len(buys))                # each share once a day
        lost = replayed(params={"day_loss_limit": 0.0001})
        later = [r for r in lost.book.fills
                 if r["side"] == "BUY" and r["time"] > "11:00"]
        self.assertEqual(later, [])
        self.assertTrue(any("Day loss limit" in n for n in lost.book.notes))

    def test_too_late_and_too_narrow(self):
        tickers = {r["ticker"] for r in replayed().book.fills}
        self.assertNotIn("NVDA", tickers)               # after 15:00
        self.assertNotIn("KO", tickers)                 # range under 0.4%

    def test_no_look_ahead(self):
        """Changing prices after 11:00 changes nothing decided before."""
        data = market_bars()
        changed = market_bars()
        for df in changed["bars"].values():
            late = df.index >= pd.Timestamp(f"{DAY} 15:00", tz="UTC")  # 11:00 NY
            df.loc[late, ["Open", "High", "Low", "Close"]] *= 1.2
        a = [r for r in replayed(data).book.fills if r["time"] <= "11:00"]
        b = [r for r in replayed(changed).book.fills if r["time"] <= "11:00"]
        self.assertEqual(a, b)
        # A quote only sees bars that have finished.
        bars = slice_day(data, DAY)["bars"]["AAPL"]
        q = snapshot(bars, 100.0, pd.Timestamp(f"{DAY} 14:34", tz="UTC"))
        self.assertEqual(q["time"], pd.Timestamp(f"{DAY} 14:30", tz="UTC"))
        self.assertLess(q["last"], 101.3)              # 10:35's bar not done

    def test_a_quote_from_the_future_or_too_old_is_ignored(self):
        pf, broker = fresh_account()
        book = DayBook(day=DAY, equity=pf.cash)
        run = DayRun(book, pf, broker, P, ["AAPL"])
        now = pd.Timestamp(f"{DAY} 14:35", tz="UTC")
        book.ranges = {"AAPL": [100.2, 101.0]}
        spy = {"last": 501, "open": 500.5, "high": 501, "low": 500,
               "prev_close": 500, "time": now}
        q = {"last": 101.3, "open": 100.0, "high": 101.3, "low": 100.2,
             "prev_close": 100.0}
        for when in (now + pd.Timedelta(minutes=1),
                     now - pd.Timedelta(minutes=11)):
            run.check(now, {"SPY": spy, "AAPL": {**q, "time": when}}, FX)
        self.assertEqual(book.fills, [])
        run.check(now, {"SPY": spy, "AAPL": {**q, "time": now}}, FX)
        self.assertEqual(summary(book.fills), [("10:35", "AAPL", "BUY")])


class LiveRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "day_trader"
        self.state = Path(self.tmp.name) / "paper_state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def live(self, until=None, start=f"{DAY} 13:05", data=None):
        data = data or market_bars()
        clock = Clock(pd.Timestamp(start, tz="UTC"))
        return day_trader.run_live(
            until, self.folder, self.state, now_fn=clock.now,
            sleep_fn=clock.sleep, quotes_fn=live_feed(clock, data),
            fx_fn=lambda: FX, bars_fn=lambda tickers, day: data)

    def test_live_day_matches_the_replay(self):
        book = self.live()
        self.assertTrue(book.finished)
        self.assertEqual(book.source, "live")
        self.assertEqual(book.checks, 71)
        self.assertEqual(summary(book.fills), summary(replayed().book.fills))
        saved = load_book(self.folder, DAY)
        self.assertEqual(saved.to_dict(), book.to_dict())

    def test_two_parts_make_the_same_day(self):
        morning = self.live(until="12:45")
        self.assertFalse(morning.finished)
        # The last check of the morning: 12:45 New York (16:45 UTC), with
        # the 50 seconds the prices took.
        self.assertEqual(pd.Timestamp(morning.last_check).floor("min"),
                         pd.Timestamp(f"{DAY} 16:45", tz="UTC"))
        afternoon = self.live(start=f"{DAY} 16:46")
        self.assertTrue(afternoon.finished)
        self.assertEqual(summary(afternoon.fills),
                         summary(replayed().book.fills))
        # A third start that day has nothing to do.
        again = self.live(start=f"{DAY} 17:00")
        self.assertEqual(again.to_dict(), afternoon.to_dict())

    def test_a_late_start_reads_the_opening_range_from_bars(self):
        book = self.live(start=f"{DAY} 15:02")
        self.assertEqual(book.ranges["AAPL"], [100.0, 101.0])
        self.assertFalse(any(r["time"] < "11:00" and r["side"] == "BUY"
                             for r in book.fills))

    def test_starts_from_the_saved_account(self):
        pf = Portfolio("Day Trader", 100_000)
        pf.cash = 90_000.0
        self.state.write_text(json.dumps({"last_date": PREV, "accounts": [
            {"agent": "daytrader", "portfolio": pf.to_dict()}]}))
        self.assertEqual(self.live(until="10:30").equity, 90_000.0)

    def test_no_live_prices_leaves_the_day_open(self):
        clock = Clock(pd.Timestamp(f"{DAY} 13:55", tz="UTC"))
        book = day_trader.run_live(
            None, self.folder, self.state, now_fn=clock.now,
            sleep_fn=clock.sleep, quotes_fn=lambda tickers: {},
            fx_fn=lambda: FX, bars_fn=lambda tickers, day: market_bars())
        self.assertFalse(book.finished)
        self.assertEqual(book.checks, 0)
        self.assertTrue(any("No live prices" in n for n in book.notes))

    def test_no_key_no_run(self):
        clock = Clock(pd.Timestamp(f"{DAY} 13:55", tz="UTC"))
        with unittest.mock.patch.dict("os.environ", {"FINNHUB_API_KEY": ""}):
            book = day_trader.run_live(None, self.folder, self.state,
                                       now_fn=clock.now, sleep_fn=clock.sleep)
        self.assertIsNone(book)
        self.assertFalse(self.folder.exists())

    def test_weekend(self):
        clock = Clock(pd.Timestamp("2025-03-29 15:00", tz="UTC"))
        self.assertIsNone(day_trader.run_live(None, self.folder, self.state,
                                              now_fn=clock.now))


class EveningBookingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_market_data("synthetic", pd.Timestamp("2025-01-01"),
                                      pd.Timestamp(DAY), seed=5)
        cls.market.source = "test"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sim(self, loader=None):
        agent = make_agent("daytrader")
        agent.folder = self.folder
        agent.bars_loader = loader
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.market.calendar[-3:-1])            # the days before
        return sim, sim.accounts[0]

    def live_book(self, until=None):
        clock = Clock(pd.Timestamp(f"{DAY} 13:05", tz="UTC"))
        data = market_bars()
        return day_trader.run_live(
            until, self.folder, Path(self.tmp.name) / "none.json",
            now_fn=clock.now, sleep_fn=clock.sleep,
            quotes_fn=live_feed(clock, data), fx_fn=lambda: FX,
            bars_fn=lambda tickers, day: data)

    def test_books_the_live_day(self):
        book = self.live_book()
        sim, acc = self.sim()
        self.assertIsNone(acc.joined)                   # not started yet
        self.assertEqual(acc.portfolio.trades, [])
        sim.step(pd.Timestamp(DAY))
        pf = acc.portfolio
        self.assertEqual(acc.joined, pd.Timestamp(DAY))
        self.assertEqual(pf.positions, {})
        self.assertEqual(len(pf.trades), len(book.fills))
        live_pf, _ = fresh_account()
        live_run = DayRun(DayBook(day=DAY, equity=100_000), live_pf,
                          SimulatedBroker(live_pf, self.market), P, [])
        for rec in book.fills:
            live_run.apply(rec)
        self.assertAlmostEqual(pf.cash, live_pf.cash, places=6)
        self.assertAlmostEqual(pf.equity_curve.iloc[-1], pf.cash, places=6)
        day = acc.agent.days[-1]
        self.assertEqual((day["source"], day["trades"]), ("live", 6))
        entry = acc.activity[-1]
        self.assertEqual(entry["time"], "intraday")
        rows = journal.fills(pf, acc.activity)
        self.assertEqual({r["session"] for r in rows}, {"intraday"})
        self.assertTrue(all(r["decision"] for r in rows))
        self.assertEqual(rows[0]["decision"]["details"]["time"], "10:35")
        # Saved and restored.
        state = json.loads(json.dumps(sim.to_dict()))
        again = Simulator.from_dict(state, self.market)
        self.assertEqual(again.accounts[0].agent.first_live, DAY)
        self.assertEqual(agent_key(again.accounts[0].agent), "daytrader")

    def test_replays_what_the_live_run_missed(self):
        self.live_book(until="11:10")
        sim, acc = self.sim(loader=lambda tickers, day: market_bars())
        sim.step(pd.Timestamp(DAY))
        fills = [(f.ticker, f.side) for f in acc.portfolio.trades]
        self.assertEqual(fills, [(t, s) for _, t, s in
                                 summary(replayed().book.fills)])
        day = acc.agent.days[-1]
        self.assertEqual(day["source"], "live, then replayed")
        self.assertTrue(any("11:10" in n for n in day["notes"]))
        # Live until 11:10: three buys and MSFT's stop; AAPL's target
        # (11:30) and JPM's sale before the close were replayed.
        live = [f["live"] for f in day["fills"]]
        self.assertEqual(live, [True] * 4 + [False] * 2)

    def test_leftovers_are_sold_at_the_close(self):
        self.live_book(until="11:10")                   # JPM still held
        sim, acc = self.sim(loader=None)                # nothing to replay
        sim.step(pd.Timestamp(DAY))
        self.assertEqual(acc.portfolio.positions, {})
        last = acc.portfolio.trades[-1]
        self.assertEqual((last.ticker, last.side), ("JPM", "SELL"))
        self.assertEqual(last.market_price, float(
            self.market.bars["JPM"].at[pd.Timestamp(DAY), "Close"]))

    def test_not_started_without_a_live_day(self):
        sim, acc = self.sim(loader=lambda tickers, day: market_bars())
        sim.step(pd.Timestamp(DAY))
        self.assertIsNone(acc.joined)
        self.assertEqual(acc.portfolio.trades, [])
        self.assertEqual(acc.agent.days, [])

    def test_a_day_without_a_live_run_is_replayed(self):
        sim, acc = self.sim(loader=lambda tickers, day: market_bars())
        acc.agent.first_live = PREV
        sim.step(pd.Timestamp(DAY))
        self.assertEqual(acc.agent.days[-1]["source"], "replayed")
        self.assertEqual(len(acc.portfolio.trades), 6)

    def test_unconnected_keeps_its_cash(self):
        agent = make_agent("daytrader")                 # folder None
        sim = Simulator(self.market, build_accounts(self.market, [agent]))
        sim.run(self.market.calendar[-5:])
        self.assertEqual(sim.accounts[0].portfolio.cash, 100_000)


class TeamTest(unittest.TestCase):
    def test_team_manager_does_not_copy_the_day_trader(self):
        market = load_market_data("synthetic", pd.Timestamp("2025-01-01"),
                                  pd.Timestamp(DAY), seed=5)
        agents = [make_agent("trend"), make_agent("daytrader"),
                  make_agent("manager")]
        sim = Simulator(market, build_accounts(market, agents))
        sim.step(market.calendar[-1])
        manager = sim.accounts[-1].agent
        self.assertEqual([a.agent.name for a in manager._racers()],
                         ["Trend Follower"])


class FinnhubTest(unittest.TestCase):
    def test_quote_and_symbols(self):
        q = finnhub_feed.parse_snapshot({"c": 101.3, "o": 100.0, "h": 101.5,
                                         "l": 99.8, "pc": 99.5,
                                         "t": 1743431700})
        self.assertEqual(q["time"], pd.Timestamp("2025-03-31 14:35",
                                                 tz="UTC"))
        self.assertEqual((q["high"], q["prev_close"]), (101.5, 99.5))
        self.assertIsNone(finnhub_feed.parse_snapshot({"c": 0, "t": 0}))
        self.assertEqual(finnhub_feed.symbol("BRK-B"), "BRK.B")


class BookFileTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = DayBook(day=DAY, equity=100_000.0)
            book.note("hello")
            save_book(book, Path(tmp))
            self.assertEqual(load_book(Path(tmp), DAY).to_dict(),
                             book.to_dict())
            self.assertIsNone(load_book(Path(tmp), PREV))


if __name__ == "__main__":
    unittest.main()
