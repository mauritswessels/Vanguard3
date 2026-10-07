"""Vectorised technical indicators in pure pandas/NumPy.

Every function is *causal*: the value at bar ``t`` depends only on bars
``<= t``. Agents can therefore compute indicators once over a full history
and read row ``t`` without look-ahead bias (verified in the test suite).
Wilder-smoothed indicators (RSI, ATR, ADX) use ``alpha = 1 / period``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average with span ``period``."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(period, min_periods=period).mean()


def wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (an EMA with alpha = 1/period)."""
    return series.ewm(alpha=1.0 / period, adjust=False,
                      min_periods=period).mean()


def true_range(high: pd.Series, low: pd.Series,
               close: pd.Series) -> pd.Series:
    """True range; the first bar falls back to high - low."""
    prev_close = close.shift(1)
    ranges = pd.concat([high - low,
                        (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=True)


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    return wilder(true_range(high, low, close), period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder), bounded to [0, 100]."""
    delta = close.diff()
    gain = wilder(delta.clip(lower=0.0), period)
    loss = wilder(-delta.clip(upper=0.0), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = gain / loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # No losses at all -> RSI 100; no movement at all -> neutral 50.
    out = out.where(loss > 0, 100.0)
    out = out.where((gain > 0) | (loss > 0), 50.0)
    return out.where(gain.notna())


def bollinger_bands(close: pd.Series, period: int = 20,
                    num_std: float = 2.0) -> pd.DataFrame:
    """Middle (SMA), upper and lower Bollinger Bands."""
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid,
                         "bb_upper": mid + num_std * std,
                         "bb_lower": mid - num_std * std})


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.DataFrame:
    """Average Directional Index with +DI and -DI (Wilder)."""
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0),
                        index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0),
                         index=high.index)
    tr_s = wilder(true_range(high, low, close), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * wilder(plus_dm, period) / tr_s
        minus_di = 100.0 * wilder(minus_dm, period) / tr_s
        di_sum = plus_di + minus_di
        dx = (100.0 * (plus_di - minus_di).abs() / di_sum).where(di_sum > 0,
                                                                 0.0)
    dx = dx.where(tr_s.notna())
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di,
                         "adx": wilder(dx, period)})


def donchian(high: pd.Series, low: pd.Series, period: int) -> pd.DataFrame:
    """Donchian channel of the *previous* ``period`` bars.

    Excluding today's bar makes ``close > upper`` a genuine breakout signal.
    """
    return pd.DataFrame({
        "dc_upper": high.rolling(period, min_periods=period).max().shift(1),
        "dc_lower": low.rolling(period, min_periods=period).min().shift(1),
    })
