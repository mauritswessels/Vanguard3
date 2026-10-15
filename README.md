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

Its twin, the **News Analyst (Opus)**, reads the same news under the same
rules and limits but asks Claude Opus, a stronger and pricier model
(`NEWS_OPUS_PARAMS` in `config.py`, about 0.13 USD a look against 0.07). The
race between the two shows whether a smarter model trades better.

It also checks once around midday (`midday_news.py`, workflow "Midday news
check", weekdays 14:37 UTC, while New York and Europe are both open). That
run first fills last evening's orders at the morning's open, reads the news
again with live Yahoo prices (about 15 minutes delayed) and asks Claude
whether anything changed. Changes fill at once at the live price, with the
usual costs; a market that is closed at that moment waits for the evening.
Only the two news agents' accounts are touched. Like everything else it is a
simulation: no broker is contacted.

A second yardstick, the **Monkey** (`models/monkey_agent.py`), picks markets
at random under the same rules as the agents (10 positions of 10%, same
costs; each evening a holding has a 1 in 20 chance of being sold). With
nine accounts racing, one will lead by luck alone; an agent shows skill only
if it keeps beating the Monkey over many weeks.

The **Team Manager** (`models/manager_agent.py`) picks agents, not
markets: it owns its share of what the agents it backs own. Until there are
35 days of results it backs every racing agent equally; after that, on the
first trading day of each month, it backs the 3 agents with the best return
over the last 3 months.

Three shared safety rules (`BaseAgent.guard`, off by default) can be
switched on by the monthly review of the learning agents, which tries every
mix of them on top of its best core settings; the fixed twins keep them off,
so the race shows whether they help:

* market weather: no new buys while SPY is under its 200-day average,
* stop loss: sell a holding that is down 12% since the buy,
* similar markets: skip a buy that moved almost in step (correlation above
  0.8 over 60 days) with something already owned.

The News Analyst grades its own trades against SPY after 5 and 20 trading
days. The report card is on the dashboard, and the latest graded trades go
in front of every brief, so Claude can learn from its record.

Every Saturday morning `weekly_report.py` (workflow "Weekly report") hands
Claude the facts of the week (each account's return, trades and stated
reasons, holdings) and asks for a short report in plain words. It goes on
the dashboard ("The week in plain words", from `docs/data/weekly.json`) and
arrives by email as a closed GitHub issue. Claude only describes the facts;
it decides nothing.

If a run fails, a scheduled run never starts, or a news agent cannot
decide, `health_check.py` notices and the workflow opens (or adds to) a
GitHub issue titled "Vanguard3 needs attention", which GitHub emails out.

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

The live page has six sections: **Overview** (the 3D network, what each
agent is doing, standings, warnings and latest trades), **Leaderboard**,
**Agent analysis** (any two accounts side by side, with a summary written
only from the numbers), **Trades** (every position from entry to exit, with
the reasons, rule values, scores and headlines the agent recorded when it
decided), **Risk** (drawdowns, volatility, concentration, exposure and
warnings) and **Performance** (all equity curves, zoomable, in CHF, % or
P&L). A time range (today, 7 days, 30 days, all time or custom) applies to
all of them. Every number is computed once, in `docs/metrics.js`, from the
fills and closing values the simulation saved (`engine/journal.py` groups
fills into positions); for "all time" it matches the Python scoreboard.

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
| `models/monkey_agent.py` | The Monkey: random picks, the luck yardstick |
| `models/manager_agent.py` | Team Manager: backs the agents with the best recent results |
| `ibkr_bridge.py` | Copies one agent into an IBKR paper account through TWS or IB Gateway |
| `ibkr_schedule.py`, `ibkr_morning.sh` | Run the bridge by itself every weekday morning (Mac or cloud server) |
| `server/` | Cloud server: IB Gateway in Docker and the weekday runs (`setup.sh`) |
| `health_check.py` | Notices missed or failed runs for the alert issue |
| `reporting.py` | Scoreboard and dashboard JSON export |
| `main.py` | Backtest entry point |
| `daily_run.py` | Live paper trading, one step per completed session |
| `engine/journal.py` | Fills with their decisions, grouped into positions (entry to exit) |
| `docs/metrics.js` | The dashboard's single source for performance and risk numbers |
| `docs/terminal.js` | Leaderboard, Agent analysis, Trades, Risk and Performance views |
| `midday_news.py` | News agents' midday check: live prices, trades fill at once |
| `telegram_chart.py` | Race chart and top three for the Telegram morning message |
| `weekly_report.py` | Saturday report: Claude explains the week in plain words |
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

## Interactive Brokers paper account (`ibkr_bridge.py`)

The agents keep running in the cloud. `ibkr_bridge.py` runs on your own
computer next to Trader Workstation (TWS), or on a small cloud server next
to IB Gateway (see below), and copies **one** agent into an IBKR paper
account (`IBKR_PARAMS["agent"]` in `config.py`, default the Team
Manager; `--agent trend` etc. to try another).

Set up TWS once: log in with **Paper Trading** selected, then in File (or
Edit) > Global Configuration > API > Settings tick "Enable ActiveX and Socket
Clients", untick "Read-Only API" and check the port is 7497; under API >
Precautions tick "Bypass Order Precautions for API Orders".

Then, in this folder:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-ibkr.txt
    .venv/bin/python ibkr_bridge.py           # shows the plan only
    .venv/bin/python ibkr_bridge.py --send    # places the orders

Run it each weekday morning before 09:00 Swiss time (before the Swiss,
European and US opens). It downloads the latest results from GitHub, works
out what the agent holds once its pending orders fill (as a share of its
account), and sends market orders so the paper account holds the same
shares scaled to its own size; orders wait for each market's open. It only
trades paper accounts (IDs starting with "D"), only touches watchlist
markets, and cancels its own unfilled orders from an earlier run first.
Each run is logged in `ibkr_logs/`.

Known differences from the simulator: IBKR may refuse some markets (for
example US funds for European customers, or regions without trading
permission), and buying shares in another currency than the account's
borrows that currency instead of converting it.

### Every weekday morning by itself (Mac)

    .venv/bin/python ibkr_schedule.py              # every weekday at 08:30
    .venv/bin/python ibkr_schedule.py --time 08:15
    .venv/bin/python ibkr_schedule.py --remove     # stop

Each morning run (`ibkr_morning.sh`) updates this folder from GitHub, runs
`ibkr_bridge.py --send` (up to three tries, two minutes apart) and shows a
notification with the result; details go to `ibkr_logs/morning.log`. The
Mac has to be on: if it is asleep at that time, the run starts as soon as
it wakes up. TWS has to stay logged in to Paper Trading: under Global
Configuration > Lock and Exit choose "Auto restart", and log in again when
IBKR asks (about once a week).

### Every weekday morning on a cloud server

A small cloud server (for example at Hetzner, about 5 euros a month) runs
IB Gateway, IBKR's trading app for servers, next to the bridge, so your
own computer can stay off.

1. Create a server with Ubuntu 24.04, about 4 GB of memory and a public
   IPv4 address, and add your SSH key.
2. On the Mac, stop the Mac schedule (`ibkr_schedule.py --remove`) and
   quit TWS: IBKR allows one login at a time, and from now on the
   server keeps it.
3. Log in to the server as root (`ssh root@<server address>`) and run:

       git clone https://github.com/mauritswessels/Vanguard3.git /opt/Vanguard3
       bash /opt/Vanguard3/server/setup.sh

   It installs Docker and Python, asks once for the IBKR **paper**
   username and password (IBKR website: person icon > Settings > Paper
   Trading Account), starts IB Gateway (`server/docker-compose.yml`), plans the
   runs for 08:30 Swiss time every weekday and ends with a dry run.
4. For a message on your phone after every run, install the free ntfy
   app and subscribe to the topic the setup prints (it is kept in
   `ibkr_morning.env`). Prefer Telegram? Make a bot with @BotFather in
   Telegram, then run `bash /opt/Vanguard3/server/telegram.sh` on the
   server and paste the bot's token. Telegram then also gets the race
   chart (`telegram_chart.py`: every account's return since launch, the
   top three and the yardsticks) after each run.

IB Gateway restarts itself every night and logs in afresh on Sundays,
and the server updates it every Saturday. If it stops answering (IBKR
sometimes refuses its early-morning re-login), the bridge gives up after
60 seconds instead of waiting forever, and the morning run restarts IB
Gateway before its next try; a run that still fails sends a "Morning run
failed" message. The login stays on the server
(`server/.env`, `server/ib_password.txt`) and never goes into git.
Useful commands on the server:

    systemctl start vanguard3-bridge          # run it now
    systemctl list-timers 'vanguard3*'        # when it runs next
    tail -n 40 /opt/Vanguard3/ibkr_logs/morning.log
    docker logs --tail 30 ib-gateway          # what IB Gateway is doing
    bash /opt/Vanguard3/server/setup.sh --login   # type a new login

## Going live with Interactive Brokers

1. Add `IBKRProvider(DataProvider)` in `data_manager.py` (`ib.reqHistoricalData`).
2. Add `IBKRBroker(BaseBroker)` in `engine/broker.py`: `submit` places MOO
   orders via `ib_insync`; fills are passed to `Portfolio.record_fill`.
3. Run `prepare` + `calculate_signals` + `execute_trade` once per evening.

The agents and the portfolio accounting do not change.
