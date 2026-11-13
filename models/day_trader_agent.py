"""Agent 12 - "The Day Trader" (buys and sells within the same day).

Every other agent decides once a day, after the close. The Day Trader looks
at live prices every few minutes while New York is open and is back in
cash before every close: it never holds anything overnight.

Its rule is the opening-range breakout, one of the oldest day-trading rules
(all numbers are in ``config.DAY_TRADER_PARAMS``):

* The first half hour sets each share's opening range: its highest and
  lowest price from 9:30 to 10:00 New York time.
* After that, a share whose price climbs above the top of its range is
  bought when the share is up on yesterday's close, the S&P 500 (SPY) is
  above today's opening price, the range is between 0.4% and 3% of the
  price, and the price has not already run more than half a range past
  the top. The strongest shares against SPY go first.
* Each buy gets a stop in the middle of the range and a target twice as
  far above the buy as the stop is below it. Its size is set so that
  hitting the stop costs about 0.5% of the account, and at most 20%.
* It sells at the stop, at the target, or 10 minutes before the close.
* At most 4 shares at once, 6 buys a day, each share once a day, no new
  buys after 15:00 New York time, and none once the day has lost 1%.

Where it runs: ``day_trader.py`` trades it live (GitHub Actions, real-time
prices from Finnhub) and writes every check and fill to one file per day
in ``state/day_trader/``. The evening run books that day's fills into the
account with the usual costs (``Simulator.step`` calls ``trade_day``). If
the live run stopped early or never ran, the rest of the day is replayed
under the same rules on Yahoo's 5-minute prices, and whatever is still
held is sold at the official close. Each day's record says which part was
live and which was replayed, so nothing is hidden.

No look-ahead: a check at time t sees only prices up to t (the live quote,
or the 5-minute bars finished by t) and fills at that price, with the same
slippage, FX spread and fee as every other fill. Pure rules: no Claude
calls, no network calls here (``day_trader.py`` fetches the prices).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date as Date
from datetime import timedelta
from pathlib import Path

import pandas as pd

import config
from engine.broker import Order
from engine.portfolio import Portfolio, TradeRecord
from models.base_agent import BaseAgent

logger = logging.getLogger(__name__)

NY = "America/New_York"
BENCH = config.BENCHMARK_TICKER
#: Minutes per Yahoo bar used by the replay.
BAR_MINUTES = 5
#: As in the midday check: a price this far from yesterday's close most
#: likely means a share split today, so that share is left alone.
SPLIT_LIKE = (0.6, 1.6)
#: Days of summaries kept in the saved state (the website shows them).
KEEP_DAYS = 30


# ---------------------------------------------------------------------------
# The trading day in New York
# ---------------------------------------------------------------------------
def _thanksgiving(year: int) -> Date:
    """Fourth Thursday of November."""
    first = Date(year, 11, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7, weeks=3)


def early_close(day) -> bool:
    """New York closes at 13:00 on the day after Thanksgiving, and on 24
    December and 3 July when they fall on Monday to Thursday (on a Friday
    the exchange is closed instead)."""
    d = pd.Timestamp(day).date()
    if d == _thanksgiving(d.year) + timedelta(days=1):
        return True
    return (d.month, d.day) in ((12, 24), (7, 3)) and d.weekday() < 4


def session(day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Opening and closing time of the New York session on ``day`` (UTC)."""
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    end = "13:00" if early_close(day) else "16:00"
    return (pd.Timestamp(f"{d} 09:30", tz=NY).tz_convert("UTC"),
            pd.Timestamp(f"{d} {end}", tz=NY).tz_convert("UTC"))


def check_times(day, params: dict) -> list[pd.Timestamp]:
    """Every check of the day (UTC): from the end of the opening range to
    the last check before the close, ``check_minutes`` apart."""
    open_, close = session(day)
    first = open_ + pd.Timedelta(minutes=params["range_minutes"])
    last = close - pd.Timedelta(minutes=params["flat_minutes"])
    return list(pd.date_range(first, last,
                              freq=f"{params['check_minutes']}min"))


def entry_deadline(day, params: dict) -> pd.Timestamp:
    """No new buys after this (UTC): ``last_entry``, or an hour before an
    early close."""
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    late = pd.Timestamp(f"{d} {params['last_entry']}", tz=NY).tz_convert("UTC")
    return min(late, session(day)[1] - pd.Timedelta(hours=1))


def ny_time(ts: pd.Timestamp) -> str:
    """'10:35': the New York clock time of a UTC timestamp."""
    return ts.tz_convert(NY).strftime("%H:%M")


# ---------------------------------------------------------------------------
# Prices: a quote is what the agent sees of one market at a check
# ---------------------------------------------------------------------------
# {"last", "open", "high", "low", "prev_close": floats in the share's own
#  currency, "time": UTC timestamp of the last price}. Live quotes come
# from Finnhub (day_trader.py); the replay builds them from 5-minute bars.

def snapshot(bars: pd.DataFrame | None, prev_close: float | None,
             now: pd.Timestamp) -> dict | None:
    """The quote at ``now`` from the day's 5-minute bars (indexed by their
    start, UTC): only bars that have finished by ``now`` count."""
    if bars is None or prev_close is None or not bars.size:
        return None
    done = bars[bars.index + pd.Timedelta(minutes=BAR_MINUTES) <= now]
    if done.empty:
        return None
    return {"last": float(done["Close"].iloc[-1]),
            "open": float(done["Open"].iloc[0]),
            "high": float(done["High"].max()),
            "low": float(done["Low"].min()),
            "prev_close": float(prev_close),
            "time": done.index[-1] + pd.Timedelta(minutes=BAR_MINUTES)}


def fx_at(series: pd.Series | None, now: pd.Timestamp) -> float | None:
    """CHF per dollar from the 5-minute bars finished by ``now``."""
    if series is None or not len(series):
        return None
    done = series[series.index + pd.Timedelta(minutes=BAR_MINUTES) <= now]
    done = done[done > 0]
    return float(done.iloc[-1]) if len(done) else None


def slice_day(data: dict, day) -> dict:
    """One day out of several days of 5-minute bars.

    ``data`` is ``{"bars": {ticker: DataFrame}, "fx": Series}`` (indexed
    by bar start, UTC, columns Open/High/Low/Close). Returns the day's bars
    per ticker, each ticker's previous close (its last bar before the
    day) and the dollar rate up to the end of the day."""
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    bars, prev = {}, {}
    for t, df in data.get("bars", {}).items():
        if df is None or df.empty:
            continue
        local = df.index.tz_convert(NY).strftime("%Y-%m-%d")
        today, before = df[local == d], df[local < d]
        if today.empty:
            continue
        bars[t] = today
        if not before.empty:
            prev[t] = float(before["Close"].iloc[-1])
    fx = data.get("fx")
    if fx is not None and len(fx):
        fx = fx[fx.index < session(day)[1] + pd.Timedelta(hours=1)]
    return {"bars": bars, "prev_close": prev, "fx": fx}


def opening_ranges(day_data: dict, day, params: dict,
                   markets: list[str]) -> dict:
    """Each share's opening range from 5-minute bars (``slice_day``):
    for a live run that starts late, when the live high and low already
    include later prices."""
    end = session(day)[0] + pd.Timedelta(minutes=params["range_minutes"])
    out = {}
    for t in markets:
        q = snapshot(day_data["bars"].get(t), 0.0, end)
        if q is not None:
            out[t] = [q["low"], q["high"]]
    return out


def _usable(q: dict | None, now: pd.Timestamp, stale: pd.Timedelta) -> bool:
    if not q:
        return False
    try:
        nums = [float(q[k]) for k in ("last", "open", "high", "low",
                                      "prev_close")]
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in nums):
        return False
    # A price from the future would be look-ahead; an old one is stale.
    if not now - stale <= q["time"] <= now:
        return False
    return SPLIT_LIKE[0] <= q["last"] / q["prev_close"] <= SPLIT_LIKE[1]


# ---------------------------------------------------------------------------
# The day's record (one JSON file per day in state/day_trader/)
# ---------------------------------------------------------------------------
@dataclass
class DayBook:
    """Everything the Day Trader did and knows on one day.

    The live run writes it after every check, so a run that stops can be
    picked up again (by the afternoon part, or by the evening replay)."""

    day: str                                   # YYYY-MM-DD (New York)
    equity: float                              # the account at the start (CHF)
    source: str = "live"                       # "live" or "replayed"
    #: Ticker -> [low, high] of the opening range.
    ranges: dict = field(default_factory=dict)
    #: Ticker -> {"quantity", "entry", "stop", "target", "time"}.
    held: dict = field(default_factory=dict)
    #: Tickers bought today (each only once a day).
    traded: list = field(default_factory=list)
    realized_chf: float = 0.0
    #: Every fill: time (New York), ticker, side, quantity, price (before
    #: costs, the share's currency), fx (CHF per unit), reason, check.
    fills: list = field(default_factory=list)
    checks: int = 0
    last_check: str | None = None              # UTC, ISO
    finished: bool = False
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DayBook":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


def book_path(folder: Path, day) -> Path:
    return Path(folder) / f"{pd.Timestamp(day):%Y-%m-%d}.json"


def load_book(folder: Path, day) -> DayBook | None:
    path = book_path(folder, day)
    if not path.exists():
        return None
    return DayBook.from_dict(json.loads(path.read_text()))


def save_book(book: DayBook, folder: Path) -> Path:
    """Write the day's record (a whole new file, so a run that is stopped
    halfway never leaves half a file)."""
    path = book_path(folder, book.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(book.to_dict(), indent=1, allow_nan=False)
                   + "\n")
    tmp.replace(path)
    return path


# ---------------------------------------------------------------------------
# One day of trading: the rules, applied check by check
# ---------------------------------------------------------------------------
class DayRun:
    """Applies the rules to one day's checks on a real account.

    The live run, the evening booking and the replay all go through here,
    so every fill pays the same costs through ``SimulatedBroker.fill_at``.
    ``done`` collects ``(record, TradeRecord)`` for every fill made.
    """

    def __init__(self, book: DayBook, portfolio: Portfolio, broker,
                 params: dict, markets: list[str]):
        self.book, self.pf, self.broker = book, portfolio, broker
        self.params, self.markets = params, markets
        self.date = pd.Timestamp(book.day)
        self.done: list[tuple[dict, TradeRecord]] = []

    # -- booking a fill made earlier (live) ---------------------------------
    def apply(self, rec: dict) -> TradeRecord | None:
        """Book a fill recorded by the live run, at its own price and
        rate, with the usual costs."""
        order = Order(rec["ticker"], rec["side"], int(rec["quantity"]),
                      self.date, rec.get("reason", ""))
        fill = self.broker.fill_at(order, self.date, float(rec["price"]),
                                   float(rec["fx"]))
        if fill is None or fill.quantity != order.quantity:
            got = fill.quantity if fill is not None else 0
            self.book.note(f"{rec['side'].title()} of {rec['quantity']} "
                           f"{rec['ticker']} at {rec['time']} booked as "
                           f"{got} shares (the cash differed from the live "
                           "run's)")
        if fill is not None:
            self.done.append((rec, fill))
        return fill

    # -- a check ------------------------------------------------------------
    def check(self, now: pd.Timestamp, quotes: dict, fx: float,
              live: bool = True) -> list[dict]:
        """Decide and trade at ``now`` (UTC) on ``quotes`` (ticker ->
        quote) with ``fx`` CHF per dollar. Returns the new fill records."""
        p, b = self.params, self.book
        stale = pd.Timedelta(minutes=p["stale_minutes"])
        fresh = {t: q for t, q in quotes.items() if _usable(q, now, stale)}
        open_, close = session(b.day)
        if not b.ranges and now >= open_ + pd.Timedelta(
                minutes=p["range_minutes"]):
            # The day's high and low so far: the opening range, when the
            # check is on time (a late live start sets ``ranges`` itself).
            b.ranges = {t: [q["low"], q["high"]] for t, q in fresh.items()
                        if t in self.markets}
        made = []
        flat = now >= close - pd.Timedelta(minutes=p["flat_minutes"])
        for t in sorted(b.held):
            h, q = b.held[t], fresh.get(t)
            if q is None:
                continue                    # no price now: look again later
            price = q["last"]
            if flat:
                why = ("Day's end: sold before the close, a day trader holds "
                       "nothing overnight")
            elif price <= h["stop"]:
                why = (f"Stop: fell to {price:.2f}, at or under the stop at "
                       f"{h['stop']:.2f} (the middle of the opening range)")
            elif price >= h["target"]:
                why = (f"Target: rose to {price:.2f}, at or over the target "
                       f"at {h['target']:.2f} (twice the risk taken)")
            else:
                continue
            rec = self._sell(t, price, fx, now, why, live)
            if rec:
                made.append(rec)
        if not flat and now <= entry_deadline(b.day, p):
            made += self._buys(now, fresh, fx, live)
        b.checks += 1
        b.last_check = now.isoformat()
        return made

    def _buys(self, now, fresh, fx, live) -> list[dict]:
        p, b = self.params, self.book
        spy = fresh.get(BENCH)
        if spy is None or spy["last"] <= spy["open"]:
            return []                       # the market is falling today
        if b.realized_chf <= -p["day_loss_limit"] * b.equity:
            b.note(f"Day loss limit: down more than "
                   f"{p['day_loss_limit']:.0%} today, so no more buys")
            return []
        spy_move = spy["last"] / spy["prev_close"] - 1
        picks = []
        for t in self.markets:
            q, rng = fresh.get(t), b.ranges.get(t)
            if q is None or not rng or t in b.traded or t in b.held:
                continue
            low, high = rng
            if not low > 0:
                continue
            width = (high - low) / low
            if not p["min_range"] <= width <= p["max_range"]:
                continue
            if not high < q["last"] <= high + p["max_chase"] * (high - low):
                continue
            if not q["last"] > q["prev_close"]:
                continue
            picks.append((q["last"] / q["prev_close"] - 1 - spy_move, t))
        made = []
        for strength, t in sorted(picks, reverse=True):
            if (len(b.held) >= p["max_positions"]
                    or len(b.traded) >= p["max_entries"]):
                break
            rec = self._buy(t, fresh[t], fx, now, strength, spy_move, live)
            if rec:
                made.append(rec)
        return made

    def _buy(self, t, q, fx, now, strength, spy_move, live) -> dict | None:
        p, b, pf = self.params, self.book, self.pf
        low, high = b.ranges[t]
        price = q["last"]
        stop = (low + high) / 2
        target = price + p["target_r"] * (price - stop)
        costs = pf.costs
        unit = costs.buy_price_chf(price, fx, "USD")
        by_risk = p["risk_pct"] * b.equity / ((price - stop) * fx)
        by_size = p["max_position_pct"] * b.equity / unit
        by_cash = ((pf.cash * (1 - config.CASH_BUFFER_PCT)
                    - costs.commission_chf) / unit)
        qty = int(math.floor(max(min(by_risk, by_size, by_cash), 0)))
        b.traded.append(t)                  # tried today: once is enough
        if qty * unit < config.MIN_ORDER_CHF:
            b.note(f"{t} broke out at {ny_time(now)} but the buy would be "
                   f"under {config.MIN_ORDER_CHF:,.0f} CHF")
            return None
        reason = (f"Breakout: {price:.2f} is above the opening range "
                  f"({low:.2f} to {high:.2f}), the share is up "
                  f"{q['last'] / q['prev_close'] - 1:+.1%} on the day and "
                  "SPY is above its open")
        check = (f"Opening range {low:.2f} to {high:.2f}; price {price:.2f} "
                 f"at {ny_time(now)} New York; stop {stop:.2f}, target "
                 f"{target:.2f}")
        order = Order(t, "BUY", qty, self.date, reason)
        fill = self.broker.fill_at(order, self.date, price, fx)
        if fill is None:
            return None
        b.held[t] = {"quantity": fill.quantity, "entry": price,
                     "stop": round(stop, 4), "target": round(target, 4),
                     "time": ny_time(now)}
        rec = {"time": ny_time(now), "ticker": t, "side": "BUY",
               "quantity": fill.quantity, "price": price, "fx": fx,
               "reason": reason, "check": check, "live": live,
               "details": {"range_low": low, "range_high": high,
                           "stop": round(stop, 4), "target": round(target, 4),
                           "day_move": round(q["last"] / q["prev_close"] - 1, 5),
                           "spy_move": round(spy_move, 5),
                           "lead_on_spy": round(strength, 5)}}
        b.fills.append(rec)
        self.done.append((rec, fill))
        return rec

    def _sell(self, t, price, fx, now, why, live, at: str | None = None
              ) -> dict | None:
        b = self.book
        h = b.held.pop(t, None) or {}
        # What this day bought (a share left over from an unbooked earlier
        # day is sold by the evening run, at that day's close).
        qty = min(h.get("quantity") or self.pf.quantity(t),
                  self.pf.quantity(t))
        if qty <= 0:
            return None
        order = Order(t, "SELL", qty, self.date, why)
        fill = self.broker.fill_at(order, self.date, price, fx)
        if fill is None:
            return None
        b.realized_chf += fill.realized_pnl_chf
        rec = {"time": at or ny_time(now), "ticker": t, "side": "SELL",
               "quantity": fill.quantity, "price": price, "fx": fx,
               "reason": why, "live": live,
               "pnl_chf": round(fill.realized_pnl_chf, 2),
               "check": (f"Bought at {h['entry']:.2f} ({h['time']}); stop "
                         f"{h['stop']:.2f}, target {h['target']:.2f}; now "
                         f"{price:.2f}") if h else None}
        b.fills.append(rec)
        self.done.append((rec, fill))
        return rec

    # -- the replay ----------------------------------------------------------
    def replay(self, day_data: dict, fallback_fx: float | None = None,
               until: pd.Timestamp | None = None) -> int:
        """Run the checks after the book's last check on 5-minute bars
        (``slice_day``), up to ``until`` (UTC; ``None``: the whole day).
        Returns the number of checks replayed."""
        b, p = self.book, self.params
        after = pd.Timestamp(b.last_check) if b.last_check else None
        bars, prev = day_data["bars"], day_data["prev_close"]
        n = 0
        for now in check_times(b.day, p):
            if after is not None and now <= after:
                continue
            if until is not None and now > until:
                break
            fx = fx_at(day_data.get("fx"), now) or fallback_fx
            if not fx:
                continue
            quotes = {t: snapshot(bars.get(t), prev.get(t), now)
                      for t in self.markets + [BENCH]}
            self.check(now, quotes, fx, live=False)
            n += 1
        return n

    def sell_rest(self, prices: dict[str, float], fx: float, why: str,
                  at: str) -> None:
        """Sell everything still held at ``prices`` (a share without a
        price stays, and is noted)."""
        for t in sorted(self.pf.positions):
            price = prices.get(t, math.nan)
            if not (math.isfinite(price) and price > 0):
                self.book.note(f"No price to sell {t} at the close")
                continue
            self.book.held.setdefault(t, {})
            self._sell(t, price, fx, None, why, live=False, at=at)


# ---------------------------------------------------------------------------
# The agent in the race
# ---------------------------------------------------------------------------
class DayTraderAgent(BaseAgent):
    name = "Day Trader"
    style = ("Buys shares breaking out of their first half hour's range and "
             "sells them the same day")
    #: Holds nothing overnight: nothing for the Team Manager to copy.
    intraday = True

    def __init__(self, params: dict | None = None):
        super().__init__({**config.DAY_TRADER_PARAMS, **(params or {})})
        #: Where the live run writes its day records (``config.
        #: DAY_TRADER_DIR``; set by daily_run). ``None``: not connected, as
        #: in tests on made-up prices, so the account just keeps its cash.
        self.folder: Path | None = None
        #: ``loader(tickers, day) -> {"bars", "fx"}`` with 5-minute prices
        #: for the replay (``day_trader.yahoo_bars``; set by daily_run).
        self.bars_loader = None
        #: First day it traded live: it joins the race that day.
        self.first_live: str | None = None
        #: One summary per day, newest last.
        self.days: list[dict] = []

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close": bars["Close"]})

    def markets(self) -> list[str]:
        have = set(self.market.tickers) if self.market is not None else None
        return [t for t in config.DAY_TRADER_MARKETS
                if have is None or t in have]

    def trades_on(self, date: pd.Timestamp) -> bool:
        """From its first live day on (a replay alone never starts it)."""
        if self.first_live:
            return date >= pd.Timestamp(self.first_live)
        return self.folder is not None and book_path(self.folder,
                                                     date).exists()

    def calculate_signals(self, date, portfolio) -> list:
        return []                           # nothing to decide after the close

    # -- the evening: book the day ------------------------------------------
    def trade_day(self, date: pd.Timestamp, portfolio: Portfolio,
                  broker) -> dict | None:
        """Book ``date``'s day trading into the account, before the day is
        marked: the live fills, then a replay of whatever the live run did
        not reach, then a sale at the close of anything still held.
        Returns the day's activity entry (``None`` if nothing traded)."""
        day = date.strftime("%Y-%m-%d")
        # The race has a session whenever any of its markets trades, so it
        # also steps US holidays when Europe is open (Thanksgiving, 4 July).
        # New York has no session then: nothing to book or replay, and a
        # replayed day would only raise a false alarm.
        if not self._ny_open(date):
            return None
        book = load_book(self.folder, date) if self.folder else None
        if self.first_live is None or date < pd.Timestamp(self.first_live):
            if book is None:
                return None                 # not started yet
            self.first_live = day
        live_part = book is not None
        if book is None:
            book = DayBook(day=day, equity=self._equity(portfolio, date),
                           source="replayed")
            book.note("No live run today: the whole day was replayed on "
                      "5-minute prices with the same rules")
        run = DayRun(book, portfolio, broker, self.params, self.markets())
        for rec in list(book.fills):
            run.apply(rec)
        live_checks = book.checks
        replayed = 0
        if not book.finished:
            if live_part:
                stop = (ny_time(pd.Timestamp(book.last_check))
                        if book.last_check else "the start")
                book.note(f"The live run stopped at {stop}: the rest of the "
                          "day was replayed on 5-minute prices")
            replayed = self._replay(run, date)
        if portfolio.positions:
            close = {t: self._close(t, date) for t in portfolio.positions}
            run.sell_rest(close, self._usd(date, "Close"),
                          "Not sold during the day: sold at the close",
                          ny_time(session(date)[1]))
        book.held = {}
        pnl = sum(f.realized_pnl_chf for _, f in run.done if f.side == "SELL")
        source = ("replayed" if not live_part else
                  "live, then replayed" if replayed else "live")
        summary = {
            "date": day, "source": source, "live_checks": live_checks,
            "replayed_checks": replayed, "trades": len(run.done),
            "pnl_chf": round(pnl, 2), "start_chf": round(book.equity, 2),
            "notes": book.notes[-6:],
            "fills": [{"time": r["time"], "ticker": r["ticker"],
                       "side": r["side"], "quantity": f.quantity,
                       "price": round(float(r["price"]), 4),
                       "pnl_chf": (round(f.realized_pnl_chf, 2)
                                   if f.side == "SELL" else None),
                       "live": bool(r.get("live", True)),
                       "reason": r["reason"]} for r, f in run.done],
        }
        self.days = [d for d in self.days if d["date"] != day][-KEEP_DAYS + 1:]
        self.days.append(summary)
        logger.info("Day Trader %s (%s): %d fills, %+.2f CHF", day, source,
                    len(run.done), pnl)
        if not run.done:
            return None
        return {
            "date": day, "time": "intraday",
            "signals": [{"ticker": r["ticker"], "action": r["side"],
                         "reason": r["reason"], "ordered": True,
                         "note": f"{r['time']} New York"
                                 + ("" if r.get("live", True)
                                    else " (replayed)"),
                         "check": r.get("check"),
                         "details": {**r.get("details", {}),
                                     "time": r["time"],
                                     "live": bool(r.get("live", True))}}
                        for r, _ in run.done],
            "orders": [{"ticker": f.ticker, "side": f.side,
                        "quantity": f.quantity} for _, f in run.done],
            "fills": [{"ticker": f.ticker, "side": f.side,
                       "quantity": f.quantity,
                       "price": round(f.exec_price, 4),
                       "pnl_chf": round(f.realized_pnl_chf, 2)}
                      for _, f in run.done],
            "day": {k: v for k, v in summary.items() if k != "fills"},
        }

    def _replay(self, run: DayRun, date: pd.Timestamp) -> int:
        if self.bars_loader is None:
            run.book.note("No 5-minute prices to replay the day with")
            return 0
        try:
            data = slice_day(self.bars_loader(self.markets() + [BENCH], date),
                             date)
        except Exception as exc:            # network: never stop the evening
            logger.warning("Day Trader: no 5-minute prices for %s: %s",
                           date.date(), exc)
            run.book.note("Yahoo's 5-minute prices could not be loaded")
            return 0
        return run.replay(data, self._usd(date, "Open"))

    def _ny_open(self, date: pd.Timestamp) -> bool:
        """Whether New York traded on ``date``: SPY has a daily price."""
        spy = self.market.bars.get(BENCH) if self.market is not None else None
        return spy is None or date in spy.index

    def _usd(self, date: pd.Timestamp, field_: str) -> float:
        """CHF per dollar on ``date`` from the daily prices."""
        panel = (self.market.fx_close if field_ == "Close"
                 else self.market.fx_open)
        return float(panel.at[date, "USD"])

    def _close(self, ticker: str, date: pd.Timestamp) -> float:
        bars = self.market.bars.get(ticker)
        if bars is None or date not in bars.index:
            return math.nan
        return float(bars.at[date, "Close"])

    def _equity(self, portfolio: Portfolio, date: pd.Timestamp) -> float:
        prev = self.market.calendar[self.market.calendar < date]
        if not portfolio.positions or not len(prev):
            return portfolio.cash
        return portfolio.equity(self.market.close_chf(prev[-1]))

    # -- saved state and the website ----------------------------------------
    def get_state(self) -> dict:
        return {"first_live": self.first_live, "days": self.days}

    def set_state(self, state: dict) -> None:
        self.first_live = state.get("first_live")
        self.days = list(state.get("days", []))

    def watch(self, date, portfolio) -> list[dict]:
        return []                           # nothing waits overnight

    def day_view(self) -> dict:
        """The website's day-by-day view: the latest days, newest first."""
        days = list(reversed(self.days))
        return {"first_live": self.first_live, "params": self.params,
                "days": days}
