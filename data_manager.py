"""Data Fetching Engine: downloads, caches and aligns end-of-day market data.

This module is the only place that knows where prices come from. The
simulation engine consumes a ``MarketData`` object and never imports a data
vendor, so swapping yfinance for Interactive Brokers (``ib_insync``) means
writing one new ``DataProvider`` subclass and nothing else.

Conventions
-----------
* Bars are daily OHLCV DataFrames with a tz-naive, normalised DatetimeIndex
  and columns ``Open, High, Low, Close, Volume``.
* Prices are split/dividend adjusted.
* FX bars give the price of 1 unit of foreign currency in CHF.
"""

from __future__ import annotations

import logging
import time
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


class DataUnavailableError(RuntimeError):
    """Raised when a provider cannot deliver data for a symbol."""


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class DataProvider(ABC):
    """Interface every market-data source must implement."""

    name = "base"

    @abstractmethod
    def fetch(self, symbol: str, start: pd.Timestamp,
              end: pd.Timestamp) -> pd.DataFrame:
        """Return daily OHLCV bars for ``symbol`` in ``[start, end]``."""


class YFinanceProvider(DataProvider):
    """Free end-of-day data from Yahoo Finance."""

    name = "yfinance"

    def __init__(self, retries: int = 3):
        self.retries = retries

    def fetch(self, symbol, start, end):
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - environment issue
            raise DataUnavailableError("yfinance is not installed") from exc

        last_error = None
        for attempt in range(self.retries):
            try:
                raw = yf.Ticker(symbol).history(
                    start=start.strftime("%Y-%m-%d"),
                    # yfinance treats ``end`` as exclusive.
                    end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    interval=config.DATA_INTERVAL,
                    auto_adjust=True,
                    actions=False,
                )
                if raw is not None and not raw.empty:
                    return clean_bars(raw)
                last_error = DataUnavailableError(f"No data for {symbol}")
            except Exception as exc:  # network hiccup, rate limit, ...
                last_error = exc
            if attempt + 1 < self.retries:
                time.sleep(2 ** attempt)
        raise DataUnavailableError(f"{symbol}: {last_error}")


class SyntheticProvider(DataProvider):
    """Deterministic random-walk data for offline tests and demos.

    Prices follow a geometric Brownian motion whose drift switches between
    bull, bear and sideways regimes, so every strategy sees trends,
    reversals and breakouts. Each symbol gets its own reproducible seed.
    """

    name = "synthetic"

    def __init__(self, seed: int = config.SYNTHETIC_SEED):
        self.seed = seed

    def fetch(self, symbol, start, end):
        dates = pd.bdate_range(start, end)
        n = len(dates)
        if n == 0:
            raise DataUnavailableError(f"Empty date range for {symbol}")
        rng = np.random.default_rng(self.seed + zlib.crc32(symbol.encode()))

        is_fx = symbol.endswith("=X")
        base_vol = 0.006 if is_fx else rng.uniform(0.010, 0.025)
        start_px = rng.uniform(0.8, 0.95) if is_fx else rng.uniform(30, 500)

        # Regime-switching drift: each regime lasts roughly 40-120 days.
        drift = np.empty(n)
        i = 0
        while i < n:
            length = int(rng.integers(40, 120))
            drift[i:i + length] = rng.choice([0.0012, -0.0010, 0.0001])
            i += length
        if is_fx:
            drift *= 0.1

        rets = drift + base_vol * rng.standard_normal(n)
        close = start_px * np.exp(np.cumsum(rets))
        gap = 1 + 0.3 * base_vol * rng.standard_normal(n)
        open_ = np.r_[start_px, close[:-1]] * gap
        spread = np.abs(rng.standard_normal((2, n))) * base_vol * 0.6
        high = np.maximum(open_, close) * (1 + spread[0])
        low = np.minimum(open_, close) * (1 - spread[1])
        volume = rng.integers(1_000_000, 50_000_000, n).astype(float)

        return pd.DataFrame(
            {"Open": open_, "High": high, "Low": low,
             "Close": close, "Volume": volume},
            index=dates,
        )


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw vendor DataFrame into the canonical bar format."""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise DataUnavailableError(f"Bars missing columns {missing}")
    df = df[OHLCV]
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    df["Volume"] = df["Volume"].fillna(0.0)
    return df.astype(float)


# ---------------------------------------------------------------------------
# Aligned market data handed to the engine
# ---------------------------------------------------------------------------
@dataclass
class MarketData:
    """Aligned price and FX data for one simulation run.

    ``bars`` keeps each ticker's own trading days (no forward filling) so
    agents compute indicators on real bars only. The panels are aligned to a
    common calendar for fast lookups by the engine.
    """

    bars: dict[str, pd.DataFrame]
    fx: dict[str, pd.DataFrame]
    currencies: dict[str, str]
    source: str
    calendar: pd.DatetimeIndex = field(init=False)
    open_panel: pd.DataFrame = field(init=False)
    close_panel: pd.DataFrame = field(init=False)
    fx_open: pd.DataFrame = field(init=False)
    fx_close: pd.DataFrame = field(init=False)

    def __post_init__(self):
        dates = sorted(set().union(*(df.index for df in self.bars.values())))
        self.calendar = pd.DatetimeIndex(dates)
        # Open is NOT forward filled: NaN means "no session, cannot fill".
        self.open_panel = pd.DataFrame(
            {t: df["Open"] for t, df in self.bars.items()}
        ).reindex(self.calendar)
        # Close IS forward filled so positions can always be marked.
        self.close_panel = pd.DataFrame(
            {t: df["Close"] for t, df in self.bars.items()}
        ).reindex(self.calendar).ffill()

        fx_open, fx_close = {}, {}
        for ccy in set(self.currencies.values()):
            if ccy == config.BASE_CURRENCY:
                fx_open[ccy] = pd.Series(1.0, index=self.calendar)
                fx_close[ccy] = pd.Series(1.0, index=self.calendar)
                continue
            bars = self.fx[ccy]
            close = bars["Close"].reindex(self.calendar).ffill().bfill()
            fx_close[ccy] = close
            fx_open[ccy] = bars["Open"].reindex(self.calendar).fillna(close)
        self.fx_open = pd.DataFrame(fx_open)
        self.fx_close = pd.DataFrame(fx_close)

    @property
    def tickers(self) -> list[str]:
        return list(self.bars)

    def history(self, ticker: str, end: pd.Timestamp) -> pd.DataFrame:
        """Bars for ``ticker`` up to and including ``end`` (no look-ahead)."""
        return self.bars[ticker].loc[:end]

    def fx_rate(self, ticker: str, date: pd.Timestamp,
                field_: str = "Close") -> float:
        """CHF value of 1 unit of ``ticker``'s currency on ``date``."""
        panel = self.fx_close if field_ == "Close" else self.fx_open
        return float(panel.at[date, self.currencies[ticker]])

    def close_chf(self, date: pd.Timestamp) -> pd.Series:
        """Last known close of every ticker, converted to CHF."""
        fx = self.fx_close.loc[date]
        rates = pd.Series({t: fx[c] for t, c in self.currencies.items()})
        return self.close_panel.loc[date] * rates


# ---------------------------------------------------------------------------
# Manager: caching + orchestration of providers
# ---------------------------------------------------------------------------
class DataManager:
    """Loads market data through a provider with an on-disk CSV cache."""

    def __init__(self, provider: DataProvider,
                 cache_dir: Path | None = config.CACHE_DIR):
        self.provider = provider
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, symbol: str) -> Path:
        safe = symbol.replace("=", "_").replace("^", "_").replace("/", "_")
        return self.cache_dir / f"{self.provider.name}_{safe}.csv"

    def _read_cache(self, symbol, start, end) -> pd.DataFrame | None:
        if not self.cache_dir:
            return None
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        # Cache is valid only if it covers the full window. A gap of up to
        # 5 days at each edge is tolerated (weekends and holidays).
        if df.empty or df.index[0] > start + pd.Timedelta(days=5) \
                or df.index[-1] < end - pd.Timedelta(days=5):
            return None
        return df.loc[start:end]

    def _write_cache(self, symbol, df):
        if self.cache_dir:
            df.to_csv(self._cache_path(symbol))

    def get_bars(self, symbol: str, start: pd.Timestamp,
                 end: pd.Timestamp) -> pd.DataFrame:
        """Return cleaned bars for one symbol, using the cache if possible."""
        cached = self._read_cache(symbol, start, end)
        if cached is not None:
            logger.debug("cache hit %s", symbol)
            return cached
        df = clean_bars(self.provider.fetch(symbol, start, end))
        self._write_cache(symbol, df)
        return df

    # -- public API ----------------------------------------------------------
    def load(self, watchlist: dict[str, str], start: pd.Timestamp,
             end: pd.Timestamp, strict: bool = False) -> MarketData:
        """Fetch all tickers plus the FX rates they need.

        With ``strict`` every ticker must load; otherwise failing tickers
        are skipped with a warning.
        """
        bars = {}
        for ticker in watchlist:
            try:
                bars[ticker] = self.get_bars(ticker, start, end)
            except Exception as exc:  # one bad ticker must not kill a run
                if strict:
                    raise
                logger.warning("Skipping %s: %s", ticker, exc)
        if not bars:
            raise DataUnavailableError(
                f"No ticker could be loaded from {self.provider.name}")

        currencies = {t: watchlist[t] for t in bars}
        fx = {}
        for ccy in set(currencies.values()) - {config.BASE_CURRENCY}:
            fx[ccy] = self.get_bars(config.FX_TICKERS[ccy], start, end)
        return MarketData(bars=bars, fx=fx, currencies=currencies,
                          source=self.provider.name)


def load_market_data(source: str, start: pd.Timestamp, end: pd.Timestamp,
                     watchlist: dict[str, str] = config.WATCHLIST,
                     cache_dir: Path | None = config.CACHE_DIR,
                     seed: int = config.SYNTHETIC_SEED,
                     strict: bool = False) -> MarketData:
    """Convenience loader honouring ``config.DATA_SOURCE`` semantics.

    ``auto`` tries yfinance first and falls back to synthetic data when the
    network is unavailable, logging a clear warning.
    """
    if source in ("yfinance", "auto"):
        try:
            return DataManager(YFinanceProvider(), cache_dir).load(
                watchlist, start, end, strict=strict)
        except Exception as exc:
            if source == "yfinance":
                raise
            logger.warning("yfinance unavailable (%s); using synthetic data",
                           exc)
    # Synthetic data is generated deterministically, so it is never cached.
    return DataManager(SyntheticProvider(seed), cache_dir=None).load(
        watchlist, start, end)
