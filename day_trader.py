"""Live day trading: the Day Trader's checks while New York is open.

GitHub Actions runs it every weekday (``.github/workflows/day-trader.yml``)
in two parts, each well under GitHub's six-hour limit for one job::

    python day_trader.py --until 12:45   # from before the open to 12:45 New York
    python day_trader.py                 # from there to the close

    python day_trader.py --replay 20     # research: the rules on the last
                                         # 20 sessions of Yahoo 5-minute prices

What a live run does:

1. opens the Day Trader's account as the last evening run left it
   (``state/paper_state.json``; 100,000 CHF before its first day), plus the
   fills of any day the evening run has not booked yet,
2. picks up today's record (``state/day_trader/<day>.json``) if the
   morning part wrote one,
3. every 5 minutes from 10:00 New York time reads real-time prices for 50
   US shares and SPY from Finnhub and the dollar rate from Yahoo, applies
   the rules (``models/day_trader_agent.py``) and saves the record,
4. stops at ``--until``, or after the last check before the close, by
   which time everything has been sold.

It needs ``FINNHUB_API_KEY``. Without it, or when a run stops early, the
evening run replays the part it missed on Yahoo's 5-minute prices (and
says so on the website). Nothing here contacts a broker: fills are
simulated with the usual costs, and the evening run books them into the
account.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd

import config
import finnhub_feed
from engine.broker import SimulatedBroker
from engine.portfolio import Portfolio
from main import setup_logging
from models.day_trader_agent import (BENCH, NY, DayBook, DayRun, _usable,
                                     book_path, check_times, load_book,
                                     ny_time, opening_ranges, save_book,
                                     session, slice_day)

logger = logging.getLogger("vanguard3.daytrader")

#: Checks in a row without a live SPY price (or dollar rate) before a live
#: run gives up and leaves the rest of the day to the evening replay. Six
#: checks is half an hour; on a market holiday there is nothing to replay.
MAX_MISSES = 6


class _Currencies:
    """The part of ``MarketData`` that ``SimulatedBroker.fill_at`` reads:
    every market the Day Trader trades is priced in dollars."""

    def __init__(self, tickers: list[str]):
        self.currencies = {t: "USD" for t in tickers}


# ---------------------------------------------------------------------------
# Prices (network)
# ---------------------------------------------------------------------------
def yahoo_bars(tickers: list[str], day=None, days: int | None = None
               ) -> dict:
    """5-minute bars from Yahoo for ``tickers`` and the dollar rate: the
    week up to ``day``, or the last ``days`` days (Yahoo keeps 60).

    Returns ``{"bars": {ticker: DataFrame}, "fx": Series}``, indexed by
    each bar's start (UTC), as ``slice_day`` reads them."""
    import yfinance as yf
    fx_symbol = config.FX_TICKERS["USD"]
    kw = dict(interval="5m", group_by="ticker", auto_adjust=False,
              prepost=False, progress=False, threads=True)
    symbols = list(tickers) + [fx_symbol]
    if day is not None:
        d = pd.Timestamp(day)
        raw = yf.download(symbols,
                          start=(d - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                          end=(d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                          **kw)
    else:
        raw = yf.download(symbols, period=f"{min(int(days or 59), 59)}d", **kw)
    out: dict = {"bars": {}, "fx": None}
    for t in symbols:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        if df.empty:
            continue
        idx = (df.index if df.index.tz is not None
               else df.index.tz_localize("UTC"))
        df = df.set_axis(idx.tz_convert("UTC"))[
            ["Open", "High", "Low", "Close"]].astype(float)
        if t == fx_symbol:
            out["fx"] = df["Close"]
        else:
            out["bars"][t] = df
    return out


def yahoo_fx() -> float | None:
    """CHF per dollar now (Yahoo, a few minutes old at most)."""
    try:
        import yfinance as yf
        df = yf.download(config.FX_TICKERS["USD"], period="5d",
                         interval="5m", auto_adjust=False, progress=False)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        close = close[close > 0]
        return float(close.iloc[-1]) if len(close) else None
    except Exception as exc:
        logger.warning("Dollar rate from Yahoo failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------
def start_account(state_path: Path, folder: Path, day: str, params: dict,
                  markets: list[str]) -> tuple[Portfolio, SimulatedBroker]:
    """The Day Trader's account at the start of ``day``: as the last
    evening run saved it, plus the live fills of days it has not booked
    yet (an evening run that failed)."""
    pf = Portfolio("Day Trader", config.INITIAL_CAPITAL_CHF)
    last = None
    if state_path.exists():
        saved = json.loads(state_path.read_text())
        last = saved.get("last_date")
        for a in saved.get("accounts", []):
            if a.get("agent") == "daytrader":
                pf = Portfolio.from_dict(a["portfolio"])
                break
    broker = SimulatedBroker(pf, _Currencies(markets + [BENCH]))
    for path in sorted(Path(folder).glob("*.json")) if Path(folder).exists() \
            else []:
        if (last is None or path.stem > last) and path.stem < day:
            book = load_book(folder, path.stem)
            run = DayRun(book, pf, broker, params, markets)
            for rec in book.fills:
                run.apply(rec)
            logger.info("Not booked yet: %s, %d fills", path.stem,
                        len(book.fills))
    return pf, broker


# ---------------------------------------------------------------------------
# The live run
# ---------------------------------------------------------------------------
def run_live(until: str | None = None, folder: Path = config.DAY_TRADER_DIR,
             state_path: Path = config.PAPER_STATE_FILE, *, now_fn=None,
             sleep_fn=time.sleep, quotes_fn=None, fx_fn=None, bars_fn=None,
             params: dict | None = None) -> DayBook | None:
    """Trade today live until ``until`` (New York time, ``HH:MM``) or the
    last check of the day. Saves the day's record after every check and
    returns it (``None`` when there is nothing to do today).

    The keyword arguments replace the clock, the waiting and the price
    sources (the tests use made-up ones)."""
    now_fn = now_fn or (lambda: pd.Timestamp.now(tz="UTC"))
    quotes_fn = quotes_fn or finnhub_feed.snapshots
    fx_fn = fx_fn or yahoo_fx
    bars_fn = bars_fn or (lambda tickers, day: yahoo_bars(tickers, day=day))
    p = {**config.DAY_TRADER_PARAMS, **(params or {})}
    markets = list(config.DAY_TRADER_MARKETS)
    folder = Path(folder)

    now = now_fn()
    day = now.tz_convert(NY).strftime("%Y-%m-%d")
    if pd.Timestamp(day).weekday() >= 5:
        logger.info("Weekend: New York is closed")
        return None
    times = check_times(day, p)
    end = times[-1]
    if until:
        end = min(end, pd.Timestamp(f"{day} {until}", tz=NY).tz_convert("UTC"))
    book = load_book(folder, day)
    if book is not None and book.finished:
        logger.info("Today's day trading is already done")
        return book
    if now > end:
        logger.info("Too late for this part of the day (until %s New York)",
                    ny_time(end))
        return book
    if quotes_fn is finnhub_feed.snapshots and not finnhub_feed.api_key():
        logger.warning("FINNHUB_API_KEY is not set: no live prices, so the "
                       "evening run replays the day on 5-minute prices")
        return book

    pf, broker = start_account(Path(state_path), folder, day, p, markets)
    if book is None:
        book = DayBook(day=day, equity=round(pf.cash, 2))
        logger.info("New day: %s CHF to trade with",
                    f"{book.equity:,.0f}")
    run = DayRun(book, pf, broker, p, markets)
    for rec in list(book.fills):              # this morning's (afternoon part)
        run.apply(rec)
    done_before = pd.Timestamp(book.last_check) if book.last_check else None
    range_end = session(day)[0] + pd.Timedelta(minutes=p["range_minutes"])
    late = pd.Timedelta(minutes=2 * p["check_minutes"])
    fx, misses = None, 0
    for t in times:
        if t > end:
            break
        if done_before is not None and t <= done_before:
            continue
        wait = (t - now_fn()).total_seconds()
        if wait > 0:
            sleep_fn(wait)
        elif -wait > p["check_minutes"] * 60:
            continue                          # missed it (a late start)
        quotes = quotes_fn(markets + [BENCH])
        now = now_fn()
        fx = fx_fn() or fx
        if not book.ranges and now - range_end > late:
            book.ranges = _late_ranges(bars_fn, day, p, markets, book)
        spy_ok = _usable(quotes.get(BENCH), now,
                         pd.Timedelta(minutes=p["stale_minutes"]))
        if not spy_ok or not fx:
            misses += 1
            logger.warning("Check %s: %s", ny_time(now),
                           "no dollar rate" if spy_ok else
                           "no live SPY price")
            if misses >= MAX_MISSES:
                book.note(f"No live prices from {ny_time(now)} on: the live "
                          "run stopped")
                save_book(book, folder)
                return book
            continue
        misses = 0
        for rec in run.check(now, quotes, fx):
            logger.info("%s %s %d %s at %.2f: %s", rec["time"],
                        rec["side"].lower(), rec["quantity"], rec["ticker"],
                        rec["price"], rec["reason"])
        save_book(book, folder)
    if book.last_check and pd.Timestamp(book.last_check) >= times[-1]:
        book.finished = True
    save_book(book, folder)
    logger.info("%s: %d checks, %d fills, %+.2f CHF realised; %s",
                day, book.checks, len(book.fills), book.realized_chf,
                "day finished" if book.finished
                else f"continues after {ny_time(end)}")
    return book


def _late_ranges(bars_fn, day, p, markets, book) -> dict:
    """A live run that starts after the opening range has ended reads the
    range from Yahoo's 5-minute bars (the live high and low would include
    later prices); failing that, the next check uses the day's range so
    far."""
    try:
        ranges = opening_ranges(slice_day(bars_fn(markets, day), day), day,
                                p, markets)
    except Exception as exc:
        logger.warning("Opening ranges from Yahoo failed: %s", exc)
        ranges = {}
    if not ranges:
        book.note("Started late: the opening range is the day's range so "
                  "far")
    return ranges


# ---------------------------------------------------------------------------
# Research: the rules on past days
# ---------------------------------------------------------------------------
def replay_days(n: int, data: dict | None = None,
                params: dict | None = None,
                now: pd.Timestamp | None = None) -> dict:
    """Replay the rules on the last ``n`` finished sessions of 5-minute
    prices, from a fresh 100,000 CHF account. Nothing is saved."""
    p = {**config.DAY_TRADER_PARAMS, **(params or {})}
    markets = list(config.DAY_TRADER_MARKETS)
    if data is None:
        data = yahoo_bars(markets + [BENCH], days=n + 7)
    spy = data["bars"].get(BENCH)
    if spy is None or spy.empty:
        raise RuntimeError("No SPY prices to replay with")
    now = now or pd.Timestamp.now(tz="UTC")
    days = sorted({d for d in spy.index.tz_convert(NY).strftime("%Y-%m-%d")
                   if session(d)[1] <= now})
    # The first day has no earlier close to compare with.
    days = days[1:][-n:]
    pf = Portfolio("Day Trader", config.INITIAL_CAPITAL_CHF)
    broker = SimulatedBroker(pf, _Currencies(markets + [BENCH]))
    rows, sells = [], []
    for day in days:
        d = slice_day(data, day)
        book = DayBook(day=day, equity=pf.cash, source="replayed")
        run = DayRun(book, pf, broker, p, markets)
        run.replay(d)
        if pf.positions:
            last = {t: float(d["bars"][t]["Close"].iloc[-1])
                    for t in pf.positions if t in d["bars"]}
            fx = d["fx"].iloc[-1] if d["fx"] is not None else None
            if fx:
                run.sell_rest(last, float(fx), "Sold at the close", "16:00")
        fills = [f for _, f in run.done]
        sells += [f for f in fills if f.side == "SELL"]
        rows.append({"day": day, "fills": len(fills),
                     "pnl_chf": round(sum(f.realized_pnl_chf for f in fills
                                          if f.side == "SELL"), 2),
                     "account_chf": round(pf.cash, 2)})
    spy_ret = None
    if days:                                  # SPY over the same days
        first, last = slice_day(data, days[0]), slice_day(data, days[-1])
        if BENCH in first["prev_close"] and BENCH in last["bars"]:
            spy_ret = (float(last["bars"][BENCH]["Close"].iloc[-1])
                       / first["prev_close"][BENCH] - 1)
    fees = sum(t.commission_chf + t.slippage_chf + t.fx_cost_chf
               for t in pf.trades)
    return {"days": rows, "return": pf.cash / pf.initial_cash - 1,
            "fills": len(pf.trades), "fees_chf": fees,
            "win_rate": (sum(f.realized_pnl_chf > 0 for f in sells)
                         / len(sells)) if sells else None,
            "spy_return": spy_ret}


def print_replay(report: dict) -> None:
    print(f"{'Day':<12}{'Fills':>6}{'Result CHF':>12}{'Account CHF':>14}")
    for r in report["days"]:
        print(f"{r['day']:<12}{r['fills']:>6}{r['pnl_chf']:>12,.0f}"
              f"{r['account_chf']:>14,.0f}")
    win = report["win_rate"]
    spy = report["spy_return"]
    print(f"\nReturn {report['return']:+.2%} over {len(report['days'])} days, "
          f"{report['fills']} fills, {report['fees_chf']:,.0f} CHF in costs, "
          f"{'no' if win is None else f'{win:.0%}'} winning trades"
          + (f"; SPY {spy:+.2%} (in dollars)" if spy is not None else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--until", help="stop after this New York time "
                        "(HH:MM); default: the close")
    parser.add_argument("--replay", type=int, metavar="DAYS",
                        help="replay the rules on the last DAYS sessions "
                        "(at most about 55) and print the results")
    parser.add_argument("--folder", type=Path, default=config.DAY_TRADER_DIR)
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)
    if args.replay:
        print_replay(replay_days(args.replay))
        return
    book = run_live(args.until, args.folder, args.state)
    if book is not None:
        print(f"Saved {book_path(args.folder, book.day)}")


if __name__ == "__main__":
    main()
