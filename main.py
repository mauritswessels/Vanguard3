"""Vanguard3 orchestrator: run the three-agent competition and score it.

Usage::

    python main.py                       # 1-year backtest (auto data)
    python main.py --source synthetic    # offline, deterministic data
    python main.py --days 730 --seed 7   # longer window, other synthetic seed

Daily loop for every agent, in chronological order:

1. the broker fills yesterday's orders at today's open (with all costs),
2. the portfolio is marked to market at today's close,
3. the agent reads data up to today's close and submits new orders.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import pandas as pd

import config
from data_manager import MarketData, load_market_data
from engine.broker import SimulatedBroker
from engine.portfolio import Portfolio
from models import ReversionAgent, TrendAgent, VolatilityAgent
from models.base_agent import BaseAgent

logger = logging.getLogger("vanguard3")


@dataclass
class Account:
    """One competitor: strategy + its own isolated portfolio and broker."""

    agent: BaseAgent
    portfolio: Portfolio
    broker: SimulatedBroker


def build_accounts(market: MarketData,
                   agents: list[BaseAgent] | None = None) -> list[Account]:
    agents = agents or [TrendAgent(), ReversionAgent(), VolatilityAgent()]
    accounts = []
    for agent in agents:
        pf = Portfolio(agent.name, config.INITIAL_CAPITAL_CHF)
        accounts.append(Account(agent, pf, SimulatedBroker(pf, market)))
    return accounts


def run_simulation(market: MarketData, start: pd.Timestamp,
                   accounts: list[Account] | None = None) -> list[Account]:
    """Run the end-of-day loop from ``start`` to the last available date."""
    accounts = accounts or build_accounts(market)
    for acc in accounts:
        acc.agent.prepare(market)

    dates = market.calendar[market.calendar >= start]
    if len(dates) == 0:
        raise ValueError(f"No trading days on or after {start.date()}")

    for date in dates:
        prices_chf = market.close_chf(date)
        for acc in accounts:
            acc.broker.process(date)
            acc.portfolio.mark_to_market(date, prices_chf)
            signals = acc.agent.calculate_signals(date, acc.portfolio)
            acc.agent.execute_trade(signals, date, acc.portfolio, acc.broker)
            if acc.portfolio.cash < -1e-6:  # defence in depth
                raise AssertionError(f"{acc.agent.name} cash went negative")
    return accounts


def run_benchmark(market: MarketData, start: pd.Timestamp,
                  ticker: str = config.BENCHMARK_TICKER) -> Portfolio | None:
    """Buy-and-hold reference, bought at the first open with full costs."""
    if ticker not in market.tickers:
        return None
    pf = Portfolio(f"Buy & Hold {ticker}", config.INITIAL_CAPITAL_CHF)
    dates = market.calendar[market.calendar >= start]
    bought = False
    for date in dates:
        if not bought:
            price = market.open_panel.at[date, ticker]
            if pd.notna(price):
                fx = market.fx_rate(ticker, date, "Open")
                ccy = market.currencies[ticker]
                qty = pf.max_affordable_qty(price, fx, ccy)
                pf.buy(date, ticker, ccy, qty, float(price), fx, "benchmark")
                bought = True
        pf.mark_to_market(date, market.close_chf(date))
    return pf


def scoreboard(portfolios: list[Portfolio]) -> pd.DataFrame:
    """Rank portfolios by final equity with key risk metrics."""
    rows = []
    for pf in portfolios:
        s = pf.performance()
        rows.append({
            "Agent": pf.name,
            "Final CHF": s["final_equity_chf"],
            "Return %": 100 * s["total_return"],
            "Sharpe": s["sharpe"],
            "Sortino": s["sortino"],
            "Max DD %": 100 * s["max_drawdown"],
            "Vol %": 100 * s["volatility"],
            "Trades": s["trades"],
            "Win %": 100 * s["win_rate"],
            "Costs CHF": s["commissions_chf"] + s["slippage_fx_chf"],
            "Open pos": s["open_positions"],
        })
    board = pd.DataFrame(rows).sort_values("Final CHF", ascending=False)
    board.insert(0, "Rank", range(1, len(board) + 1))
    return board.set_index("Rank")


def save_results(accounts: list[Account],
                 benchmark: Portfolio | None) -> None:
    out = config.RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    curves = [a.portfolio.equity_curve for a in accounts]
    if benchmark is not None:
        curves.append(benchmark.equity_curve)
    pd.concat(curves, axis=1).to_csv(out / "equity_curves.csv")
    for acc in accounts:
        slug = acc.agent.name.lower().replace(" ", "_")
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
    parser.add_argument("--no-save", action="store_true",
                        help="do not write CSVs to results/")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    # yfinance is very chatty when offline; keep the console readable.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=args.days)
    data_start = start - pd.Timedelta(days=config.WARMUP_DAYS)

    market = load_market_data(args.source, data_start, end, seed=args.seed)
    logger.info("Loaded %d tickers from %s, %s -> %s", len(market.tickers),
                market.source, market.calendar[0].date(),
                market.calendar[-1].date())

    accounts = run_simulation(market, start)
    benchmark = run_benchmark(market, start)

    portfolios = [a.portfolio for a in accounts]
    if benchmark is not None:
        portfolios.append(benchmark)
    board = scoreboard(portfolios)

    first = accounts[0].portfolio.equity_curve.index
    print()
    print("=" * 100)
    print(f" VANGUARD3 COMPETITION  |  {first[0].date()} -> {first[-1].date()}"
          f"  |  {len(first)} sessions  |  data: {market.source}"
          f"  |  start {config.INITIAL_CAPITAL_CHF:,.0f} CHF each")
    print("=" * 100)
    with pd.option_context("display.width", 140,
                           "display.float_format", "{:,.2f}".format):
        print(board.to_string())
    print("-" * 100)
    for acc in accounts:
        print(f" {acc.agent.name:<22} {acc.agent.style}")
    print(f" Costs: {config.COMMISSION_PER_TRADE_CHF:.2f} CHF/fill, "
          f"{config.SLIPPAGE_BPS:g} bp slippage, "
          f"{config.FX_CONVERSION_BPS:g} bp FX spread. Fills at next open.")
    if market.source == "synthetic":
        print(" NOTE: synthetic data - results validate the engine, "
              "not the strategies.")

    if not args.no_save:
        save_results(accounts, benchmark)
        print(f" Trade logs and equity curves written to {config.RESULTS_DIR}")


if __name__ == "__main__":
    main()
