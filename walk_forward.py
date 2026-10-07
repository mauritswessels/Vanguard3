"""Walk-forward parameter study: tune on the past, judge on the unseen future.

For every agent and every parameter set in its grid, one continuous
backtest is run over the whole history. The history is then cut into
yearly *test* windows. For each test year, the parameter set with the best
Sharpe ratio over the preceding ``--train-years`` is chosen, and only its
returns in the test year count. Stitching the test years together gives an
out-of-sample equity curve that never benefited from hindsight.

Usage::

    python walk_forward.py                  # yfinance, 5 test years
    python walk_forward.py --source synthetic --test-years 3

Writes ``docs/data/walkforward.json`` for the dashboard and prints a table.
"""

from __future__ import annotations

import argparse
import logging
import math
import time

import numpy as np
import pandas as pd

import config
from data_manager import load_market_data
from engine import metrics
from engine.simulator import build_accounts
from learning import GRIDS, expand
from main import run_simulation, setup_logging
from models import make_agent
from reporting import write_json

logger = logging.getLogger("vanguard3.wf")

MIN_TRAIN_TRADES = 10   # ignore parameter sets that barely trade


def window_stats(equity: pd.Series, trades: pd.Series,
                 lo: pd.Timestamp, hi: pd.Timestamp) -> dict:
    """Sharpe, return and trade count of a continuous curve inside a window.

    The first return in the window is measured from the last close before
    it, so consecutive windows tile the curve without gaps.
    """
    prev = equity.loc[:lo - pd.Timedelta(days=1)]
    seg = equity.loc[lo:hi]
    if prev.empty or seg.empty:
        return {"sharpe": math.nan, "return": math.nan, "trades": 0}
    full = pd.concat([prev.iloc[-1:], seg])
    rets = full.pct_change().dropna()
    return {
        "sharpe": metrics.sharpe_ratio(rets),
        "return": float(full.iloc[-1] / full.iloc[0] - 1),
        "trades": int(((trades.index >= lo) & (trades.index <= hi)).sum()),
        "returns": rets,
    }


def label(params: dict, grid: dict) -> str:
    keys = [k for key in grid for k in (key if isinstance(key, tuple)
                                        else (key,))]
    return ", ".join(f"{k}={params[k]}" for k in keys)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=config.DATA_SOURCE,
                        choices=["auto", "yfinance", "synthetic"])
    parser.add_argument("--test-years", type=int, default=5)
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    end = pd.Timestamp.today().normalize()
    years = args.test_years + args.train_years
    sim_start = end - pd.DateOffset(years=years)
    market = load_market_data(
        args.source, sim_start - pd.Timedelta(days=config.WARMUP_DAYS), end)
    end = market.calendar[-1]
    test_edges = [end - pd.DateOffset(years=args.test_years - i)
                  for i in range(args.test_years + 1)]
    folds = [(e0 + pd.Timedelta(days=1), e1)
             for e0, e1 in zip(test_edges[:-1], test_edges[1:])]

    # Benchmark over the same test years, for reference.
    bench = run_simulation(market, sim_start, build_accounts(
        market, [make_agent("benchmark")])).accounts[0].portfolio
    bench_eq = bench.equity_curve

    report = {"generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
              "data_source": market.source,
              "train_years": args.train_years,
              "folds": [[a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")]
                        for a, b in folds],
              "agents": []}
    rows = []

    for key, grid in GRIDS.items():
        combos = expand(grid)
        default = {k: config.__dict__[f"{key.upper()}_PARAMS"][k]
                   for k in combos[0]}
        if default not in combos:
            combos.append(default)
        t0 = time.time()
        runs = []
        for params in combos:
            acc = run_simulation(market, sim_start, build_accounts(
                market, [make_agent(key, params)])).accounts[0]
            log = acc.portfolio.trade_log()
            trades = pd.Series(1, index=pd.DatetimeIndex(
                log["date"] if not log.empty else []))
            runs.append((params, acc.portfolio.equity_curve, trades))
        logger.info("%s: %d parameter sets in %.0fs", key, len(combos),
                    time.time() - t0)

        fold_rows, oos, oos_default = [], [], []
        for lo, hi in folds:
            train_lo = lo - pd.DateOffset(years=args.train_years)
            best, best_sharpe = None, -math.inf
            for params, eq, trades in runs:
                s = window_stats(eq, trades, train_lo,
                                 lo - pd.Timedelta(days=1))
                if (s["trades"] >= MIN_TRAIN_TRADES
                        and s["sharpe"] > best_sharpe):
                    best, best_sharpe = (params, eq, trades), s["sharpe"]
            if best is None:  # nothing traded enough: fall back to defaults
                best = next(r for r in runs if r[0] == default)
            test = window_stats(best[1], best[2], lo, hi)
            dflt = next(r for r in runs if r[0] == default)
            dtest = window_stats(dflt[1], dflt[2], lo, hi)
            oos.append(test["returns"])
            oos_default.append(dtest["returns"])
            fold_rows.append({
                "test": [lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")],
                "params": best[0],
                "train_sharpe": best_sharpe,
                "test_return": test["return"], "test_sharpe": test["sharpe"],
                "test_trades": test["trades"],
                "default_test_return": dtest["return"],
            })

        def curve(parts):
            rets = pd.concat(parts)
            return config.INITIAL_CAPITAL_CHF * (1 + rets).cumprod()

        tuned, dflt_curve = curve(oos), curve(oos_default)
        latest = fold_rows[-1]["params"]
        summary = {
            "tuned": _curve_stats(tuned), "default": _curve_stats(dflt_curve),
            "recommended_params": latest, "default_params": default,
        }
        report["agents"].append({
            "key": key, "name": make_agent(key).name,
            "folds": fold_rows, **summary,
            "tuned_equity": _pairs(tuned),
            "default_equity": _pairs(dflt_curve),
        })
        rows.append((make_agent(key).name, summary, label(latest, grid)))

    no_trades = pd.Series(1, index=pd.DatetimeIndex([]))
    bench_oos = window_stats(bench_eq, no_trades,
                             folds[0][0], folds[-1][1])
    bench_curve = (config.INITIAL_CAPITAL_CHF
                   * (1 + bench_oos["returns"]).cumprod())
    report["benchmark"] = {"name": bench.name, **_curve_stats(bench_curve),
                           "equity": _pairs(bench_curve)}
    write_json(report, config.DASHBOARD_DATA_DIR / "walkforward.json")

    print()
    print("=" * 100)
    print(f" WALK-FORWARD  |  {folds[0][0].date()} -> {folds[-1][1].date()}"
          f"  |  {args.test_years} test years, {args.train_years}y training"
          f"  |  data: {market.source}")
    print("=" * 100)
    print(f" {'Agent':<22}{'Tuned ret':>10}{'Sharpe':>8}{'MaxDD':>8}"
          f"{'Default ret':>13}{'Sharpe':>8}{'MaxDD':>8}   Latest pick")
    for name, s, pick in rows:
        t, d = s["tuned"], s["default"]
        print(f" {name:<22}{t['return']:>10.1%}{t['sharpe']:>8.2f}"
              f"{t['max_drawdown']:>8.1%}{d['return']:>13.1%}"
              f"{d['sharpe']:>8.2f}{d['max_drawdown']:>8.1%}   {pick}")
    b = report["benchmark"]
    print(f" {b['name']:<22}{b['return']:>10.1%}{b['sharpe']:>8.2f}"
          f"{b['max_drawdown']:>8.1%}")
    print(" Tuned = parameters re-chosen each year from the previous "
          f"{args.train_years} years only (out-of-sample).")


def _curve_stats(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    start = config.INITIAL_CAPITAL_CHF
    full = pd.concat([pd.Series([start]), eq.reset_index(drop=True)])
    return {"return": float(eq.iloc[-1] / start - 1),
            "sharpe": metrics.sharpe_ratio(rets),
            "max_drawdown": metrics.max_drawdown(full)}


def _pairs(eq: pd.Series) -> list:
    return [[d.strftime("%Y-%m-%d"), round(float(v), 2)]
            for d, v in eq.items() if np.isfinite(v)]


if __name__ == "__main__":
    main()
