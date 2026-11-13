"""Live paper trading: advance every agent by the sessions since the last run.

Run once per evening after the US close (GitHub Actions does this on a
schedule, see ``.github/workflows/daily.yml``)::

    python daily_run.py

What it does:

1. downloads fresh end-of-day data,
2. restores all accounts (cash, positions, pending orders, trailing stops)
   from ``state/paper_state.json``,
3. simulates every *completed* session since the last run, exactly like a
   backtest day (yesterday's orders fill at today's open, then new
   decisions at today's close), plus dividends and share splits,
4. books the Day Trader's trades of each new day (``day_trader.py`` makes
   them live; what it missed is replayed on 5-minute prices),
5. saves the state and refreshes ``docs/data/paper.json`` for the dashboard.

If a run is missed, the next one catches up on all skipped sessions.
Paper trading never uses synthetic data unless explicitly asked to (tests).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd

import config
from data_manager import YFinanceProvider, load_market_data
from engine.simulator import Simulator, build_accounts
from learning import LOOKBACK_YEARS, paper_lineup, retune
from models import agent_key
from main import setup_logging
from reporting import dashboard_payload, print_scoreboard, write_json

logger = logging.getLogger("vanguard3.paper")

#: Yahoo suffixes of the European exchanges on the watchlist.
EUROPE = (".SW", ".DE", ".PA", ".AS")

#: Yahoo leaves the European markets' newest day out of downloads for a few
#: hours after midnight in Zurich (seen until about 03:30). A run that
#: starts in that gap (GitHub sometimes starts the evening run hours late)
#: waits for the prices until this time in Zurich, instead of booking
#: nothing that night.
EUROPE_WAIT_UNTIL = pd.Timedelta(hours=4, minutes=30)

#: How often a waiting run downloads the prices again.
EUROPE_RECHECK = pd.Timedelta(minutes=10)


def last_completed_session(now_utc: pd.Timestamp | None = None
                           ) -> pd.Timestamp:
    """Latest date whose New York close has settled (bars are final)."""
    now = (now_utc or pd.Timestamp.now(tz="UTC")).tz_convert(
        "America/New_York")
    settled = now.normalize() + pd.Timedelta(
        hours=16, minutes=config.CLOSE_SETTLE_MINUTES)
    day = now.normalize() if now >= settled else (
        now.normalize() - pd.Timedelta(days=1))
    return day.tz_localize(None)


def europe_wait_deadline(now_utc: pd.Timestamp) -> pd.Timestamp | None:
    """Until when (UTC) a run started at ``now_utc`` waits for missing
    European prices: only inside the gap after midnight in Zurich. Before
    midnight a missing European day means a European holiday, so the run
    does not wait."""
    zurich = now_utc.tz_convert("Europe/Zurich")
    until = zurich.normalize() + EUROPE_WAIT_UNTIL
    return until.tz_convert("UTC") if zurich < until else None


def load_for_state(saved: dict | None, source: str,
                   paper_start: pd.Timestamp, cutoff: pd.Timestamp,
                   seed: int = config.SYNTHETIC_SEED,
                   cache_dir: Path | None = config.CACHE_DIR):
    """Daily bars up to ``cutoff`` for every watched market.

    An account holding (or about to trade) a ticker that failed to
    download could not be valued, so such a failure aborts the run (the
    next run catches up). Any other failing ticker is skipped for today.
    """
    # Learning agents replay the last LOOKBACK_YEARS at every review.
    data_start = (paper_start - pd.DateOffset(years=LOOKBACK_YEARS)
                  - pd.Timedelta(days=config.WARMUP_DAYS))
    needed = {p["ticker"] for a in (saved or {}).get("accounts", [])
              for p in a["portfolio"]["positions"] + a["pending_orders"]}
    return load_market_data(source, data_start, cutoff, seed=seed,
                            cache_dir=cache_dir,
                            strict=needed or {config.BENCHMARK_TICKER})


def europe_missing(market, day: pd.Timestamp) -> bool:
    """True when ``day`` has New York prices but none from Europe.

    Yahoo leaves the European markets' latest day out of downloads made
    after midnight in Zurich; simulating that day would keep European
    prices a day old and leave every European order unfilled. (On the few
    days all of Europe is closed and New York open, waiting a day is
    harmless.)
    """
    opens = market.open_panel.loc[day]
    europe = [t for t in opens.index if t.endswith(EUROPE)]
    others = [t for t in opens.index if not t.endswith(EUROPE)]
    return (bool(europe) and bool(opens[others].notna().any())
            and bool(opens[europe].isna().all()))


def advance(state_path: Path, source: str, paper_start: pd.Timestamp,
            cutoff: pd.Timestamp, seed: int = config.SYNTHETIC_SEED, *,
            wait_until: pd.Timestamp | None = None, now_fn=None,
            sleep_fn=time.sleep, loader=None
            ) -> tuple[Simulator | None, int]:
    """Load state, simulate new sessions up to ``cutoff``, save state.

    When the newest day has New York prices but none from Europe yet, it
    downloads again every ``EUROPE_RECHECK`` until ``wait_until`` (UTC;
    ``None``: no waiting) before leaving that day to the next run.
    ``now_fn``, ``sleep_fn`` and ``loader`` replace the clock, the waiting
    and the download (the tests use made-up ones).

    Returns the simulator (``None`` before the first session) and the number
    of sessions simulated in this call.
    """
    now_fn = now_fn or (lambda: pd.Timestamp.now(tz="UTC"))
    loader = loader or load_for_state
    saved = json.loads(state_path.read_text()) if state_path.exists() else None
    market = loader(saved, source, paper_start, cutoff, seed)
    done = pd.Timestamp(saved["last_date"]) if saved else None

    def waiting_on_europe(market) -> pd.Timestamp | None:
        days = market.calendar[market.calendar <= cutoff]
        if (len(days) and (done is None or days[-1] > done)
                and europe_missing(market, days[-1])):
            return days[-1]
        return None

    day = waiting_on_europe(market)
    while (day is not None and wait_until is not None
           and now_fn() + EUROPE_RECHECK <= wait_until):
        logger.info("No European prices for %s yet (Yahoo leaves them out "
                    "for a few hours after midnight in Zurich): looking "
                    "again in %d minutes", day.date(),
                    EUROPE_RECHECK.total_seconds() // 60)
        sleep_fn(EUROPE_RECHECK.total_seconds())
        # Straight from Yahoo: the copy saved on disk lacks the new prices.
        try:
            market = loader(saved, source, paper_start, cutoff, seed,
                            cache_dir=None)
        except Exception as exc:   # keep the first download, try again
            logger.warning("Downloading again failed: %s", exc)
        day = waiting_on_europe(market)
    if day is not None:
        logger.warning("No European prices for %s yet: that day is "
                       "simulated by the next run", day.date())
        market = market.until(day - pd.Timedelta(days=1))

    if saved is not None:
        sim = Simulator.from_dict(saved, market, tuner=retune)
        # Agents added to the lineup after launch join with fresh accounts.
        have = {(agent_key(a.agent), a.agent.name) for a in sim.accounts}
        for agent in paper_lineup(market):
            if (agent_key(agent), agent.name) not in have:
                logger.info("Adding new account: %s", agent.name)
                sim.add_account(agent, paper_start)
    else:
        logger.info("No saved state: opening fresh %s CHF accounts",
                    f"{config.INITIAL_CAPITAL_CHF:,.0f}")
        sim = Simulator(market, build_accounts(market, paper_lineup(market)),
                        tuner=retune)

    # The Day Trader books what its live run did today (day_trader.py) and
    # replays on Yahoo's 5-minute prices whatever that run missed. On
    # made-up prices (tests) it is not connected and keeps its cash.
    if source == "yfinance":
        from day_trader import yahoo_bars
        for acc in sim.accounts:
            if hasattr(acc.agent, "trade_day"):
                acc.agent.folder = config.DAY_TRADER_DIR
                acc.agent.bars_loader = (
                    lambda tickers, day: yahoo_bars(tickers, day=day))

    # Dividends are paid and splits applied in live paper trading only.
    sim.corporate_actions = True
    for split in sim.apply_splits():
        logger.info("Share split: %s, %g new shares per old one (%s)",
                    split["ticker"], split["ratio"], split["date"])

    cal = market.calendar
    new = cal[(cal >= paper_start) & (cal <= cutoff)]
    if sim.last_date is not None:
        new = new[new > sim.last_date]
    sim.run(new)

    if sim.last_date is not None:
        write_json(sim.to_dict(), state_path)
    return (sim if sim.last_date is not None else None), len(new)


def stand_in_prices(last: pd.Timestamp, provider=None) -> dict:
    """Last close of each European fund the IBKR copy holds instead of a
    US fund (``config.IBKR_STAND_INS``), for the IBKR bridge. One that
    fails to download is left out (the bridge keeps that fund in cash)."""
    provider = provider or YFinanceProvider(retries=2)
    out = {}
    for us, (symbol, exchange, ccy, yahoo) in config.IBKR_STAND_INS.items():
        try:
            bars = provider.fetch(yahoo, last - pd.Timedelta(days=10), last)
            out[us] = {"symbol": symbol, "exchange": exchange,
                       "currency": ccy, "price": float(bars["Close"].iloc[-1]),
                       "date": bars.index[-1].strftime("%Y-%m-%d")}
        except Exception as exc:
            logger.warning("No price for %s (the IBKR version of %s): %s",
                           yahoo, us, exc)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="yfinance",
                        choices=["yfinance", "synthetic"])
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("--dashboard", type=Path,
                        default=config.DASHBOARD_DATA_DIR / "paper.json")
    parser.add_argument("--start", default=config.PAPER_START_DATE,
                        help="first paper-trading session (YYYY-MM-DD)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    start = pd.Timestamp(args.start)
    now = pd.Timestamp.now(tz="UTC")
    cutoff = last_completed_session(now)
    sim, n_new = advance(args.state, args.source, start, cutoff,
                         wait_until=(europe_wait_deadline(now)
                                     if args.source == "yfinance" else None))
    # The workflow skips testing and publishing when nothing is new.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"new_sessions={n_new}\n")

    if sim is None:
        logger.info("Paper trading starts %s; nothing to simulate yet "
                    "(last completed session %s)", start.date(),
                    cutoff.date())
        write_json({"mode": "paper", "status": "waiting",
                    "start": start.strftime("%Y-%m-%d"),
                    "generated_utc": pd.Timestamp.now(tz="UTC").isoformat()},
                   args.dashboard)
        return

    logger.info("Simulated %d new session(s); state is at %s", n_new,
                sim.last_date.date())
    print_scoreboard(sim, "VANGUARD3 PAPER TRADING")
    payload = dashboard_payload(sim, "paper", start, {"status": "live"})
    if args.source == "yfinance":
        payload["stand_ins"] = stand_in_prices(sim.last_date)
    write_json(payload, args.dashboard)


if __name__ == "__main__":
    main()
