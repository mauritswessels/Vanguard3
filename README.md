# Vanguard3

End-of-day, multi-agent paper-trading simulator. Three rule-based agents
(pure pandas/NumPy, no LLM calls) each trade their own 100,000 CHF account
against the same watchlist; a scoreboard ranks them against buy-and-hold SPY.

On macOS the command is `python3` (there is no `python`). Install the
packages once into a virtual environment, then run through it:

```bash
cd vanguard3
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python main.py                      # 1-year backtest (auto data)
.venv/bin/python main.py --source synthetic --seed 7 --days 730
.venv/bin/python -m unittest discover -s tests -t .
```

## Layout

| Path | Role |
| --- | --- |
| `config.py` | Capital, costs, watchlist + currencies, strategy parameters |
| `data_manager.py` | Data Fetching Engine: `DataProvider` interface, `YFinanceProvider`, `SyntheticProvider`, CSV cache, aligned `MarketData` |
| `engine/portfolio.py` | CHF cash, positions, fills, trade log, cost model (2 CHF/fill, slippage, FX spread), metrics |
| `engine/broker.py` | `BaseBroker` interface and `SimulatedBroker` (market-on-open fills) |
| `engine/metrics.py` | Sharpe, Sortino, max drawdown, CAGR, volatility |
| `models/base_agent.py` | `BaseAgent`: `prepare`, `calculate_signals`, `execute_trade`, sizing |
| `models/indicators.py` | Causal EMA, SMA, RSI, ATR, ADX, Bollinger, Donchian |
| `models/trend_agent.py` | Trend Follower: EMA 20/50 + ADX |
| `models/reversion_agent.py` | Bargain Hunter: RSI < 30 + Bollinger, exit at the mean |
| `models/volatility_agent.py` | Volatility Protected: Donchian breakout, ATR trailing stop, risk sizing |
| `main.py` | Orchestrator: daily loop, benchmark, scoreboard, CSV output |
| `tests/` | Accounting, no-look-ahead, broker timing and full-backtest tests |

## Execution model

Agents decide after the close of day *t* using data up to *t*. Orders fill
at the **open of day t+1** with 5 bp adverse slippage, a 2 bp CHF/USD
conversion spread and a flat 2 CHF commission. Buys are scaled down to
available cash; cash can never go negative. Positions are marked at the
close in CHF using the daily USDCHF rate.

## Going live with Interactive Brokers

1. Add `IBKRProvider(DataProvider)` in `data_manager.py` (`ib.reqHistoricalData`).
2. Add `IBKRBroker(BaseBroker)` in `engine/broker.py`: `submit` places MOO
   orders via `ib_insync`; fills are passed to `Portfolio.record_fill`.
3. Run `prepare` + `calculate_signals` + `execute_trade` once per evening.

The agents and the portfolio accounting do not change.
