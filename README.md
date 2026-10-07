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
.venv/bin/python walk_forward.py              # tune on the past, test blind
.venv/bin/python main.py --days 1825 --dashboard   # refresh dashboard backtest
```

## Live paper trading and dashboard

`daily_run.py` advances every agent by the sessions completed since its last
run and saves everything (cash, positions, pending orders, trailing stops) to
`state/paper_state.json`. The GitHub Actions workflow in
`.github/workflows/daily.yml` runs it every weekday at 21:30 UTC, commits the
new state, and refreshes `docs/data/`. GitHub Pages serves `docs/index.html`
as the dashboard, so nothing needs to run on your own computer.

Live, each strategy runs twice: a **learning** agent that reviews its own
settings on the first trading day of every month (`learning.py`: it replays
the last 3 years with every allowed setting and switches only when another
one is clearly better), and a **fixed twin** that never changes. Comparing
the two on the dashboard shows whether learning pays off.

To start over, delete `state/paper_state.json` and change
`PAPER_START_DATE` in `config.py`.

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
| `engine/simulator.py` | The daily loop shared by backtests and paper trading, with save/restore |
| `models/benchmark_agent.py` | Buy & Hold SPY, run as an agent so it pays the same costs |
| `reporting.py` | Scoreboard and dashboard JSON export |
| `main.py` | Backtest entry point |
| `daily_run.py` | Live paper trading, one step per completed session |
| `learning.py` | Monthly self-tuning for the live learning agents |
| `walk_forward.py` | Walk-forward parameter study |
| `docs/index.html` | Dashboard (GitHub Pages) reading `docs/data/*.json` |
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
