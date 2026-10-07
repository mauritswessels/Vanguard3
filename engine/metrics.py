"""Performance statistics computed from a daily equity curve."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

import config


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def sharpe_ratio(returns: pd.Series,
                 risk_free: float = config.RISK_FREE_RATE,
                 periods: int = config.TRADING_DAYS_PER_YEAR) -> float:
    """Annualised Sharpe ratio of daily returns (sample std, ddof=1)."""
    if len(returns) < 2:
        return float("nan")
    excess = returns - risk_free / periods
    std = excess.std(ddof=1)
    if not np.isfinite(std) or std < 1e-12:
        return float("nan")
    return float(excess.mean() / std * math.sqrt(periods))


def sortino_ratio(returns: pd.Series,
                  risk_free: float = config.RISK_FREE_RATE,
                  periods: int = config.TRADING_DAYS_PER_YEAR) -> float:
    """Annualised Sortino ratio using downside deviation."""
    if len(returns) < 2:
        return float("nan")
    excess = returns - risk_free / periods
    downside = np.sqrt((np.minimum(excess, 0.0) ** 2).mean())
    # A flat (all-cash) curve has no risk to reward: report undefined.
    if downside < 1e-12 or returns.std(ddof=1) < 1e-12:
        return float("nan")
    return float(excess.mean() / downside * math.sqrt(periods))


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough loss as a negative fraction (e.g. -0.12)."""
    if equity.empty:
        return float("nan")
    running_peak = equity.cummax()
    return float((equity / running_peak - 1.0).min())


def cagr(equity: pd.Series, initial: float) -> float:
    """Compound annual growth rate from ``initial`` to the last value."""
    if equity.empty or initial <= 0:
        return float("nan")
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0:
        return float("nan")
    return float((equity.iloc[-1] / initial) ** (365.25 / days) - 1.0)


def summarize(equity: pd.Series, initial: float) -> dict[str, float]:
    """Headline statistics for the scoreboard."""
    rets = daily_returns(pd.concat([pd.Series([initial]), equity],
                                   ignore_index=True))
    periods = config.TRADING_DAYS_PER_YEAR
    final = float(equity.iloc[-1]) if not equity.empty else initial
    mdd = max_drawdown(pd.concat([pd.Series([initial]), equity],
                                 ignore_index=True))
    growth = cagr(equity, initial)
    return {
        "final_equity_chf": final,
        "total_return": final / initial - 1.0,
        "cagr": growth,
        "volatility": float(rets.std(ddof=1) * math.sqrt(periods))
        if len(rets) > 1 else float("nan"),
        "sharpe": sharpe_ratio(rets),
        "sortino": sortino_ratio(rets),
        "max_drawdown": mdd,
        "calmar": growth / abs(mdd) if mdd and mdd < 0 else float("nan"),
    }
