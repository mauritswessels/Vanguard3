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
   decisions at today's close),
4. saves the state and refreshes ``docs/data/paper.json`` for the dashboard.

If a run is missed, the next one catches up on all skipped sessions.
Paper trading never uses synthetic data unless explicitly asked to (tests).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

import config
from data_manager import load_market_data
from engine.simulator import Simulator, build_accounts
from learning import LOOKBACK_YEARS, paper_lineup, retune
from models import agent_key
from main import setup_logging
from reporting import dashboard_payload, print_scoreboard, write_json

logger = logging.getLogger("vanguard3.paper")


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


def advance(state_path: Path, source: str, paper_start: pd.Timestamp,
            cutoff: pd.Timestamp, seed: int = config.SYNTHETIC_SEED
            ) -> tuple[Simulator | None, int]:
    """Load state, simulate new sessions up to ``cutoff``, save state.

    Returns the simulator (``None`` before the first session) and the number
    of sessions simulated in this call.
    """
    # Learning agents replay the last LOOKBACK_YEARS at every review.
    data_start = (paper_start - pd.DateOffset(years=LOOKBACK_YEARS)
                  - pd.Timedelta(days=config.WARMUP_DAYS))
    # An account holding (or about to trade) a ticker that failed to
    # download could not be valued, so such a failure aborts the run (the
    # next run catches up). Any other failing ticker is skipped for today.
    saved = json.loads(state_path.read_text()) if state_path.exists() else None
    needed = {p["ticker"] for a in (saved or {}).get("accounts", [])
              for p in a["portfolio"]["positions"] + a["pending_orders"]}
    market = load_market_data(source, data_start, cutoff, seed=seed,
                              strict=needed or {config.BENCHMARK_TICKER})

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

    cal = market.calendar
    new = cal[(cal >= paper_start) & (cal <= cutoff)]
    if sim.last_date is not None:
        new = new[new > sim.last_date]
    sim.run(new)

    if sim.last_date is not None:
        write_json(sim.to_dict(), state_path)
    return (sim if sim.last_date is not None else None), len(new)


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
    cutoff = last_completed_session()
    sim, n_new = advance(args.state, args.source, start, cutoff)

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
    write_json(dashboard_payload(sim, "paper", start,
                                 {"status": "live"}), args.dashboard)


if __name__ == "__main__":
    main()
