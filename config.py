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
# Watchlist: ticker (Yahoo Finance symbol) -> trading currency.
# About 100 large, heavily traded markets, all tradable at Interactive
# Brokers. The currency decides which FX rate converts prices into CHF;
# Swiss shares trade in CHF and need no conversion.
# ---------------------------------------------------------------------------
_US_STOCKS = [
    # Technology and communication
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "ORCL",
    "ADBE", "CRM", "AMD", "CSCO", "INTC", "QCOM", "TXN", "IBM", "NFLX", "DIS",
    # Finance
    "BRK-B", "JPM", "V", "MA", "BAC", "GS",
    # Health care
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT",
    # Consumer
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NKE",
    # Energy, industry, telecoms
    "XOM", "CVX", "CAT", "GE", "HON", "BA", "LIN", "T", "VZ",
]
_SWISS_STOCKS = [   # the SMI and other large SIX shares, traded in CHF
    "NESN.SW", "ROG.SW", "NOVN.SW", "UBSG.SW", "ZURN.SW", "ABBN.SW",
    "CFR.SW", "LONN.SW", "SIKA.SW", "GIVN.SW", "ALC.SW", "HOLN.SW",
    "SREN.SW", "PGHN.SW", "SCMN.SW", "SLHN.SW", "GEBN.SW", "LOGN.SW",
    "KNIN.SW", "SOON.SW",
]
_EURO_STOCKS = [    # large euro-area shares, traded in EUR
    "ASML.AS", "SAP.DE", "MC.PA", "SIE.DE", "TTE.PA", "SAN.PA", "ALV.DE",
    "OR.PA", "AIR.PA", "SU.PA", "DTE.DE", "BNP.PA",
]
_FUNDS = [          # US-listed ETFs: indices, countries, sectors, bonds, raw materials
    "SPY", "QQQ", "IWM", "DIA",
    "EWL", "VGK", "EWJ", "EEM", "FXI", "INDA", "EWZ",
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLU", "VNQ",
    "TLT", "IEF", "LQD", "HYG",
    "GLD", "SLV", "DBC", "USO",
]
WATCHLIST = {
    **{t: "USD" for t in _US_STOCKS},
    **{t: "CHF" for t in _SWISS_STOCKS},
    **{t: "EUR" for t in _EURO_STOCKS},
    **{t: "USD" for t in _FUNDS},
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

LEARNER_PARAMS = {
    "lr": 0.01,                  # learning rate of each daily update
    "gamma": 0.9,                # how much tomorrow's value counts today
    "epsilon": 0.05,             # share of random decisions, to keep learning
    "trade_cost": 0.1,           # reward penalty (in %) per change of position
    "pretrain_years": 3,         # practice on this much history before day one
    "pretrain_epochs": 3,
    "position_pct": 0.10,
    "max_positions": 8,
    "seed": 7,
    "live_from": "2026-10-13",   # learns in shadow mode until this session
}

NEWS_PARAMS = {
    "model": "claude-sonnet-5-5",  # Anthropic model that reads the news
    "max_weight": 0.15,          # largest share of the account per market
    "max_total": 0.90,           # at most this much invested, rest cash
    "min_weight": 0.02,          # smaller targets are treated as "no"
    # Rough cost estimate only (USD per million tokens); check your bill.
    "usd_per_m_input": 3.0,
    "usd_per_m_output": 15.0,
}
