"""Global configuration for the Vanguard3 paper-trading simulator.

Every tunable number lives here so that experiments never require edits to
the engine or the agents. All monetary values are in the base currency (CHF)
unless the name says otherwise.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
RESULTS_DIR = PROJECT_ROOT / "results"
DASHBOARD_DATA_DIR = PROJECT_ROOT / "docs" / "data"
PAPER_STATE_FILE = PROJECT_ROOT / "state" / "paper_state.json"

# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
BASE_CURRENCY = "CHF"
INITIAL_CAPITAL_CHF = 100_000.0

# ---------------------------------------------------------------------------
# Execution / cost model (modelled on Interactive Brokers, fixed pricing)
# ---------------------------------------------------------------------------
COMMISSION_PER_TRADE_CHF = 2.0   # flat fee charged on every fill
SLIPPAGE_BPS = 5.0               # adverse price move per fill (1 bp = 0.01 %)
FX_CONVERSION_BPS = 2.0          # spread paid when converting CHF <-> foreign
CASH_BUFFER_PCT = 0.005          # cash kept back when sizing to absorb gaps

# ---------------------------------------------------------------------------
# Watchlist: ticker -> trading currency.
# The currency decides which FX rate converts prices into CHF.
# ---------------------------------------------------------------------------
WATCHLIST = {
    # High-volume US technology
    "AAPL": "USD",
    "MSFT": "USD",
    "NVDA": "USD",
    "GOOGL": "USD",
    "AMZN": "USD",
    # Global index ETFs
    "SPY": "USD",   # S&P 500
    "QQQ": "USD",   # Nasdaq 100
    "EWL": "USD",   # MSCI Switzerland
    "VGK": "USD",   # FTSE Europe
    "EWJ": "USD",   # MSCI Japan
    "EEM": "USD",   # MSCI Emerging Markets
    # Macro: rates, commodities and metals
    "TLT": "USD",   # 20y+ US Treasuries
    "GLD": "USD",   # Gold
    "SLV": "USD",   # Silver
    "DBC": "USD",   # Broad commodities basket
}

# Yahoo Finance symbol giving the price of 1 unit of the currency in CHF.
FX_TICKERS = {
    "USD": "USDCHF=X",
    "EUR": "EURCHF=X",
    "GBP": "GBPCHF=X",
    "JPY": "JPYCHF=X",
}

# Ticker used for the passive buy-and-hold benchmark on the scoreboard.
BENCHMARK_TICKER = "SPY"

# Competitors, by registry key (see models/__init__.py). The benchmark runs
# as a normal agent so it pays the same costs as everyone else.
AGENT_LINEUP = ["trend", "reversion", "volatility", "benchmark"]

# ---------------------------------------------------------------------------
# Simulation window
# ---------------------------------------------------------------------------
DATA_INTERVAL = "1d"             # end-of-day bars only
BACKTEST_DAYS = 365              # calendar days traded in the backtest
WARMUP_DAYS = 400                # history so 200-day indicators are ready
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.005           # annual CHF risk-free rate used for Sharpe

# "yfinance", "synthetic", or "auto" (yfinance, falling back to synthetic).
DATA_SOURCE = "auto"
SYNTHETIC_SEED = 42

# ---------------------------------------------------------------------------
# Live paper trading (daily_run.py)
# ---------------------------------------------------------------------------
PAPER_START_DATE = "2026-10-07"  # first session the paper accounts trade
# Minutes after the 16:00 New York close before a day's bar is final.
CLOSE_SETTLE_MINUTES = 30

# ---------------------------------------------------------------------------
# Agent parameters
# ---------------------------------------------------------------------------
TREND_PARAMS = {
    "ema_fast": 20,
    "ema_slow": 50,
    "adx_period": 14,
    "adx_threshold": 25.0,
    "position_pct": 0.10,        # target weight of equity per position
}

REVERSION_PARAMS = {
    "rsi_period": 14,
    "rsi_entry": 40.0,           # walk-forward: 30 almost never triggered
    "bb_period": 20,
    "bb_std": 2.0,
    "quality_sma": 0,            # 0 = off; 200 = only buy above long trend
    "max_holding_days": 20,      # time stop if the snap-back never comes
    "position_pct": 0.10,
}

VOLATILITY_PARAMS = {
    "donchian_entry": 55,        # walk-forward: 20/10 churned on noise
    "donchian_exit": 20,
    "atr_period": 14,
    "atr_stop_mult": 3.5,        # trailing stop distance in ATRs
    "risk_per_trade_pct": 0.01,  # equity lost if the initial stop is hit
    "max_position_pct": 0.15,
}
