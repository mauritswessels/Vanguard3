"""Vanguard3 backtest: run the agent competition over history and score it.

Usage::

    python main.py                       # 1-year backtest (auto data)
    python main.py --source synthetic    # offline, deterministic data
    python main.py --days 1825           # 5-year backtest
    python main.py --dashboard           # also export docs/data/backtest.json

See ``engine/simulator.py`` for the daily loop and ``daily_run.py`` for
live paper trading.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

import config
from data_manager import MarketData, load_market_data
from engine.simulator import Account, Simulator, build_accounts
from models import make_agent
from reporting import dashboard_payload, print_scoreboard, write_json

logger = logging.getLogger("vanguard3")


def default_agents(market: MarketData, overrides: dict | None = None):
    """Instantiate the configured lineup, skipping unavailable benchmarks."""
    overrides = overrides or {}
    agents = []
    for key in config.AGENT_LINEUP:
        if key == "benchmark" and config.BENCHMARK_TICKER not in market.bars:
            continue
        agents.append(make_agent(key, overrides.get(key)))
    return agents


def run_simulation(market: MarketData, start: pd.Timestamp,
                   accounts: list[Account] | None = None,
                   end: pd.Timestamp | None = None) -> Simulator:
    """Backtest every account from ``start`` to ``end`` (default: last bar)."""
    accounts = accounts or build_accounts(market, default_agents(market))
    sim = Simulator(market, accounts)
    dates = market.calendar[market.calendar >= start]
    if end is not None:
        dates = dates[dates <= end]
    if len(dates) == 0:
        raise ValueError(f"No trading days on or after {start.date()}")
    sim.run(dates)
    return sim


def save_results(sim: Simulator) -> None:
    out = config.RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    pd.concat([a.portfolio.equity_curve for a in sim.accounts],
              axis=1).to_csv(out / "equity_curves.csv")
    for acc in sim.accounts:
        slug = acc.agent.name.lower().replace(" ", "_").replace("&", "and")
        acc.portfolio.trade_log().to_csv(out / f"trades_{slug}.csv",
                                         index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=config.DATA_SOURCE,
                        choices=["auto", "yfinance", "synthetic"])
    parser.add_argument("--days", type=int, default=config.BACKTEST_DAYS,
                        help="calendar days to backtest")
    parser.add_argument("--seed", type=int, default=config.SYNTHETIC_SEED,
                        help="seed for synthetic data")
    parser.add_argument("--dashboard", action="store_true",
                        help="export docs/data/backtest.json")
    parser.add_argument("--no-save", action="store_true",
                        help="do not write CSVs to results/")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    # yfinance is very chatty when offline; keep the console readable.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=args.days)
    data_start = start - pd.Timedelta(days=config.WARMUP_DAYS)

    market = load_market_data(args.source, data_start, end, seed=args.seed)
    logger.info("Loaded %d tickers from %s, %s -> %s", len(market.tickers),
                market.source, market.calendar[0].date(),
                market.calendar[-1].date())

    sim = run_simulation(market, start)
    print_scoreboard(sim, "VANGUARD3 BACKTEST")

    if not args.no_save:
        save_results(sim)
        print(f" Trade logs and equity curves written to {config.RESULTS_DIR}")
    if args.dashboard:
        path = config.DASHBOARD_DATA_DIR / "backtest.json"
        write_json(dashboard_payload(sim, "backtest", start), path)
        print(f" Dashboard data written to {path}")


if __name__ == "__main__":
    main()
