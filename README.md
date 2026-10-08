# Vanguard3

End-of-day, multi-agent paper-trading simulator. Three rule-based agents
(pure pandas/NumPy, no LLM calls) each trade their own 100,000 CHF account
against the same watchlist of 108 large markets (US, Swiss and euro-area shares plus index, sector, bond and commodity funds), all tradable at Interactive Brokers; a scoreboard ranks them against buy-and-hold SPY.

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

An eighth account, the **AI Learner** (`models/learner_agent.py`), learns
every day instead of every month. It is the Python version of the lab's
reinforcement-learning agent: a linear score for SELL / HOLD / BUY built from
10 price features, updated after every close with what its last decisions
earned. It practises on the 3 years before its first day, then runs in
practice mode (deciding and learning, but placing no orders) until
`LEARNER_PARAMS["live_from"]` in `config.py`. Accounts added to the lineup
after launch join automatically on the next daily run.

A ninth account, the **News Analyst** (`models/news_agent.py`, `news.py`),
reads free headlines (Google News RSS) on every market and on politics and
the economy, plus each stock's latest quarterly results (Yahoo Finance), and
asks Claude for target weights with a short stated reason per market. It
needs an `ANTHROPIC_API_KEY` repository secret; without one it waits and
the dashboard says so. It only decides for the newest session (news cannot
be replayed honestly) and cannot be backtested, because the model already
knows how past markets turned out. `python news.py` prints today's brief, and
the manual "News check" workflow does the same on GitHub.

It also checks once around midday (`midday_news.py`, workflow "Midday news
check", weekdays 14:37 UTC, while New York and Europe are both open). That
run first fills last evening's orders at the morning's open, reads the news
again with live Yahoo prices (about 15 minutes delayed) and asks Claude
whether anything changed. Changes fill at once at the live price, with the
usual costs; a market that is closed at that moment waits for the evening.
Only the News Analyst's account is touched. Like everything else it is a
simulation: no broker is contacted.

With a `FINNHUB_API_KEY` repository secret (free plan at finnhub.io), the
midday check takes real-time US prices from Finnhub instead (Yahoo stays the
backup, and covers Swiss and European markets), and the brief adds each US
company's latest news from Finnhub (`finnhub_feed.py`).

The dashboard also shows what each agent is doing right now: for every
watched market, the agent's own rule with the values from the last close
(`entry_check` / `exit_check` in each agent; used for display only, never to
trade) and a rough closeness score to its buy rule. The 3D network at the top
(`docs/hub.js`) adds a small point every day an agent comes close to buying
a market, so it gets denser the longer the accounts run.

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
| `midday_news.py` | News Analyst midday check: live prices, trades fill at once |
| `learning.py` | Monthly self-tuning for the live learning agents |
| `walk_forward.py` | Walk-forward parameter study |
| `docs/index.html` | Dashboard (GitHub Pages) reading `docs/data/*.json` |
| `docs/lab/` | 3D AI research lab: a browser-only reinforcement-learning simulation (see below) |
| `tests/` | Accounting, no-look-ahead, broker timing and full-backtest tests |

## 3D AI research lab (`docs/lab/`)

An interactive 3D view of a learning trading agent, running entirely in the
browser on the prices in `docs/data/backtest.json`. It is a research
simulation: nothing in it can place a real order.

Run it locally:

```bash
cd docs
python3 -m http.server 8000
# open http://localhost:8000/lab/
```

It is also served by GitHub Pages at `/lab/`. Opening `index.html` straight
from disk works too, but browsers block the data file there, so it falls back
to a synthetic market (the System Health panel says so).

| File | Layer | Role |
| --- | --- | --- |
| `js/core.js` | shared | Event bus, `V3.EVENTS` contract, config, component graph, helpers |
| `js/sim/market.js` | simulation | Loads and CHF-converts prices, 10 causal features, regime classifier |
| `js/sim/agent.js` | simulation | Linear Q-learning agent, risk manager, simulated execution |
| `js/sim/engine.js` | simulation | Training episodes, validation on the held-out final year, versions, backtests |
| `js/viz/graph3d.js` | visualization | three.js network, camera controls, particles, decision flow |
| `js/ui/*.js` | UI | Panels, charts, tabs; they only listen to the bus and read `engine.state()` |
| `js/main.js` | wiring | Boots everything and connects the bus to the 3D view |

To plug in your own model, keep the same `act()` / `update()` shape in
`sim/agent.js`, or replace `V3.Engine` in `main.js` with your own object that
emits the same `V3.EVENTS`. The UI and the 3D view need no changes.

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
