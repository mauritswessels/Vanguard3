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
.venv/bin/python luck_study.py                # skill or luck: everyone against 300 monkeys
```

## Live paper trading and dashboard

`daily_run.py` advances every agent by the sessions completed since its last
run and saves everything (cash, positions, pending orders, trailing stops) to
`state/paper_state.json`. The GitHub Actions workflow in
`.github/workflows/daily.yml` runs it every weekday evening between the New
York close and midnight in Zurich (after midnight Yahoo leaves out the
European markets' day), commits the new state, and refreshes `docs/data/`
(the 5-year backtest only on Fridays: it is 4 MB and barely moves in a day).
GitHub Pages serves `docs/index.html` as the dashboard, so nothing needs to
run on your own computer.

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

Two trading rules stop it from churning. Its random tries (5% of decisions,
there so it keeps learning) are learned on paper and never traded, and it
keeps every holding at least 10 sessions (`explore_on_paper` and `min_hold`
in `LEARNER_PARAMS`). A sell it wants sooner counts as a hold, so the model
learns from what the account really did. Without these rules it bought and
sold the next day almost every time: replayed over the last 5 years it made
8,108 fills, paid about 49,500 CHF in costs and lost 64.5%. With them the
same replay makes 678 fills, pays about 6,300 CHF and gains 27%. Over 10
random seeds the median is +31% and every seed gains. That is still behind
buy-and-hold SPY (+63%) and the typical random-pick monkey (+44%).

Its twin, the **Opus Learner** (`models/opus_learner_agent.py`), runs the
same learning model but lets Claude Opus check its picks: once per evening it
reads the model's proposed sells and its best proposed buys, with recent
price moves and a few headlines each, and approves or turns down every one.
Only approved trades are placed, so the race against the AI Learner shows
whether an AI reviewer improves a simple learning model. One Opus call per
evening at most, about 0.05 USD (`LEARNER_OPUS_PARAMS` in `config.py`); like
the News Analyst it needs the `ANTHROPIC_API_KEY` secret and only trades on
the newest session.

The model learns from what the account did. A pick Opus turns down or leaves
out is learned as a hold, and so is every pick on an evening without a
review (catching up, no key, a failed call). It used to learn each pick as
if it had been placed. Opus cannot be replayed honestly, so this was
checked over the last 5 years with a stand-in reviewer that approves picks
at random, on 40 seeds. With half the picks approved the median return went
from +16% to +30%; with a quarter, from +22% to +36%; with one in ten, from
+32% to +52%. It trades a little more (724 fills instead of 631 at one in
two) and wins on about two seeds in three. This says nothing about whether
Opus itself chooses well.

A ninth account, the **News Analyst** (`models/news_agent.py`, `news.py`),
reads free headlines (Google News RSS) on every market and on politics and
the economy, plus each stock's latest quarterly results (Yahoo Finance), and
asks Claude for target weights with a short stated reason per market. It
needs an `ANTHROPIC_API_KEY` repository secret; without one it waits and
the dashboard says so. It only decides for the newest session (news cannot
be replayed honestly) and cannot be backtested, because the model already
knows how past markets turned out. `python news.py` prints today's brief, and
the manual "News check" workflow does the same on GitHub.

Its twin, the **News Analyst (Opus)**, reads the same news (downloaded
once and handed to both) under the same rules and limits but asks Claude Opus, a stronger and pricier model
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

How many weeks? `luck_study.py` puts a number on it. It runs 300 monkeys,
each with its own dice, over the same days as each account: over the last
five years for every agent that can be replayed honestly (the three
strategies with fixed settings, their learning versions re-tuned each year
as in the walk-forward study, and the AI Learner), and live for every paper
account from its first decision on. For each account it gives the share of
monkeys it beat, its average lead a year over SPY with a 95% range (its own
days reshuffled in runs of 20, a block bootstrap), and a verdict: **skill**
when the lead is too big for luck even allowing for the number of agents
racing (Holm's correction), **looks like luck** when the results rule out
an edge of 10% a year, and **can't tell yet** otherwise, with how many more
weeks of live results it would take to spot such an edge. A rule's
five-year result depends a lot on the day it starts (started a few days
apart, the Trend Follower ended anywhere between +22% and +59%), so each replayed
agent starts on 5 days a week apart and the middle one counts. Expect years
rather than weeks: day-to-day swings are large next to any edge, so even
10% a year over random picks takes well over ten years to show. The news
agents, the Opus Learner and the Team Manager are judged on their live
results only. The study runs every Saturday (workflow "Skill or luck",
about 5 minutes; settings in `LUCK_PARAMS` in `config.py`), writes
`docs/data/skill.json` and is on the dashboard under Research > Skill or
luck?

`docs/data/skill.json` keeps a fixed shape, so pages can rely on it. Shares
and returns are fractions (0.1 = 10%), dates are `YYYY-MM-DD`, and a value
that does not apply is `null`. At the top: `generated_utc`, `as_of` (the
last session with results), `data_source`, `method` (the method in a few
plain sentences), `verdict_meanings` (each verdict explained), `settings`
(`LUCK_PARAMS`), `past` (`from`, `to`, `years`, `days`, `monkeys`,
`agents_tested`, `start_days`, and `monkey_returns`: every monkey's
return over those years, for a histogram), `live` (`from`, `to`, `monkeys`, `agents_tested`;
`null` before paper trading starts), and `accounts`, one entry per account
(racing accounts first, the two yardsticks last):

| Field | Meaning |
| --- | --- |
| `id`, `key`, `name` | As in `paper.json`: `trend-fixed`, `trend`, "Trend Follower (fixed)" |
| `fixed_twin`, `yardstick` | A fixed twin; Buy & Hold SPY or the Monkey (never judged) |
| `verdict` | "skill", "can't tell yet" or "looks like luck" against the monkeys: live once there are `min_days` live sessions, otherwise from the past prices |
| `verdict_from` | "live", "past prices", or `null` (no results yet, or a yardstick) |
| `summary` | A few plain sentences: one on the past prices, one on the live results |
| `past`, `live` | The two parts, with the same fields below (`null` when the account has none) |

Fields of `past` and `live`:

| Field | Meaning |
| --- | --- |
| `from`, `to`, `days` | Counted from this close (live: the account's first decision) to `to`; `days` sessions with a result |
| `return`, `spy_return`, `monkey_median_return` | Over those days: the account, buy-and-hold SPY, the middle monkey |
| `percentile_vs_monkeys` | Share of the monkeys it beat (0 to 1) |
| `verdict`, `verdict_vs_spy` | The verdict against the monkeys, and against SPY |
| `excess_vs_monkey`, `excess_vs_monkey_low`, `excess_vs_monkey_high` | Average lead a year over the typical monkey, with its 95% range |
| `excess_vs_spy`, `excess_vs_spy_low`, `excess_vs_spy_high` | The same over SPY |
| `p_vs_monkeys`, `p_vs_monkeys_adjusted`, `p_vs_spy`, `p_vs_spy_adjusted` | Chance of a result this good by luck alone, before and after allowing for the number of agents tested |
| `weeks_needed`, `weeks_needed_vs_spy` | Live only, while it can't tell yet: more weeks of results needed to spot an edge of `settings.edge` a year |
| `returns_by_start_day` | Past only, replayed agents: the return of each start-day copy, lowest first (the fields above describe the middle one) |

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

If a run fails, a scheduled run never starts, a news agent cannot decide,
or an order does not go through (not enough cash, or its market did not
open for a week), `health_check.py` notices and the workflow opens (or adds
to) a GitHub issue titled "Vanguard3 needs attention", which GitHub emails
out. Every pull request runs the tests first (workflow "Tests").

That issue needs a run to notice the problem. For a run that never starts
at all, add a free watchdog at [healthchecks.io](https://healthchecks.io):
make a check with the schedule `40 21 * * 1-5` (time zone UTC, grace time 3
hours) and save its ping address as the repository secret
`HEALTHCHECK_URL`. Every evening run then tells it "all fine" once the
accounts are up to date (also on market holidays) or "failed" when the run
broke, and healthchecks.io emails you when neither arrives. The server's
morning run does the same with its own check (schedule `30 8 * * 1-5`, time
zone Europe/Zurich, grace time 1 hour): put
`HEALTHCHECK_URL=<that check's ping address>` in
`/opt/Vanguard3/ibkr_morning.env`.

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
the reasons, rule values and scores the agent recorded when it decided,
and for the last 90 days also the headlines and other details it read), **Risk** (drawdowns, volatility, concentration, exposure and
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
| `ibkr_summary.py` | The paper account next to the simulated agent, for the website (`ibkr_logs/public/ibkr.json`) |
| `server/` | Cloud server: IB Gateway in Docker and the weekday runs (`setup.sh`); `publish.sh` puts the summary on GitHub |
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
| `luck_study.py` | Skill or luck: every account against hundreds of monkeys and SPY |
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

Backtests use Yahoo's dividend- and split-adjusted prices. The live paper
accounts are paid each dividend in cash on its ex-date, after the tax a
Swiss investor cannot reclaim (`DIVIDEND_TAX` in `config.py`: 15% on US and
European dividends, none on Swiss ones), and a share split restates the
holding, its pending orders and stops before the next session is
simulated. Both show up in the agents' activity on the dashboard.

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

European customers may not buy US-listed funds (EU rules), so for each of
the 26 US funds the bridge holds its closest European (UCITS) version
instead, listed in `IBKR_STAND_INS` in `config.py`: for example CSPX on the
London Stock Exchange for SPY. Most trade in US dollars, follow the same
index and differ only a little in price moves (and in how they pay
dividends: several keep them inside the fund). The evening run looks up their prices
on Yahoo, so the bridge can size the orders; the logs show them as
"SPY (as CSPX)".

Before the stock orders, the bridge changes currency (`change_currency`
in `IBKR_PARAMS`): it works out how many US dollars, euros or francs the
new holdings need, compares that with the cash the account holds in each
currency, and places currency orders for the difference (with a 1% margin),
so a buy in another currency than the account's no longer borrows it.

IBKR may still refuse some markets (regions without trading permission);
the bridge then remembers that and keeps their share in cash.

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
   top three and the yardsticks) after each run, followed by why the top
   three hold what they hold: how each one picks, its biggest holdings
   with the reason it bought them, and what it trades at the next open.

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

### The paper account on the website

The simulation fills every order at the open with fixed costs. A real
broker does not: orders can be refused, fill late or only in part, a US
fund is held as its European version, and prices differ a little. To show
that gap, every morning run can publish a small summary of the paper
account next to the simulated Team Manager.

After the orders are placed, `ibkr_summary.py` reads that run's log and
the results it copied and writes `ibkr_logs/public/ibkr.json`;
`server/publish.sh` then pushes it to GitHub. Both run in their own steps
after the orders, so they cannot stop or change them: a problem only adds
one line to the morning message ("Could not publish the account summary
for the website: ..."), and the run still counts as a success.

The file goes to its own public repository (default
`mauritswessels/vanguard3-ibkr-data`, branch `ibkr-data`), not to this
one. The server writes with a GitHub deploy key, and a deploy key opens
the whole repository it belongs to: in this repository it could also
change the code, the workflows and so reach the secrets. In a repository
of its own it can only ever change the summary. `publish.sh` also refuses
to push to `main` or `master`, and trusts only GitHub's published server
keys (`server/github_known_hosts`). Each morning replaces a single commit
there; the file keeps its own history (the last 750 mornings,
`summary_days` in `IBKR_PARAMS`). The website reads it from

    https://raw.githubusercontent.com/mauritswessels/vanguard3-ibkr-data/ibkr-data/ibkr.json

(GitHub serves it to any website; it can take up to five minutes to
show a new version).

Set it up once, after the server setup above:

1. On the server, as root:

       bash /opt/Vanguard3/server/setup.sh --publish

   Press Enter to keep the suggested repository name. It makes the key
   (`/root/.ssh/vanguard3_publish`, never in git), saves the settings in
   `ibkr_morning.env` (`PUBLISH_REPO`, `PUBLISH_BRANCH`, `PUBLISH_KEY`)
   and prints the two steps below with the key filled in. Leave it
   waiting.
2. On GitHub, make the repository at https://github.com/new: name
   `vanguard3-ibkr-data`, Public, no README > Create repository.
3. In that repository, Settings > Deploy keys > Add deploy key: title
   "Vanguard3 server", paste the line starting with `ssh-ed25519` that
   the setup printed, tick **Allow write access** > Add key.
4. Back on the server, press Enter. The setup checks that the key may
   push (a dry run: nothing is published yet) and says Done. The first
   summary appears after the next morning run.

To stop publishing, delete the `PUBLISH_` lines from `ibkr_morning.env`
(and the deploy key on GitHub).

Nothing personal is published: no account ID, username, password, token
or Telegram chat, and none of IBKR's own messages, which can name the
account (a refused order shows only IBKR's error code). Before the file is
written it is searched for the account ID, anything shaped like an IBKR
account ID, and every login detail and token on the server; if one turns
up, nothing is written.

Both accounts are valued at the same close: the paper account before
that morning's orders (so at the last close), the Team Manager at the
close whose results were copied. Returns are in francs, at the results'
exchange rates, so the account's own currency (usually US dollars) does
not blur the comparison. Whether an order filled is judged the next
morning, from the account's holdings: until then it is `null`.

`ibkr.json` keeps a fixed shape. Shares and returns are fractions (0.1 =
10%), dates are `YYYY-MM-DD`, money is rounded to cents, and a value that
is not known is `null`. At the top: `schema` (1), `generated_utc`,
`about` (a plain sentence on what it shows), `agent` and `agent_name` (the
copied agent), `account_currency`, `since` (the first morning the
returns count from), `latest` (the newest morning in detail) and `history`
(one row per morning, oldest first).

Rows of `history`:

| Field | Meaning |
| --- | --- |
| `date` | The morning of the run |
| `results_of` | The close whose results were copied; both values are measured there |
| `same_close` | `false` when the results were older than the last weekday close (the evening run failed, or a holiday): that row has no returns |
| `value`, `value_chf` | The paper account's net liquidation value, in its own currency and in CHF |
| `cash_chf`, `invested`, `positions` | Its cash (value minus positions), share invested and number of positions |
| `sim_value_chf`, `sim_invested`, `sim_positions` | The same for the simulated agent |
| `return`, `sim_return`, `difference` | Since the previous row with `same_close`, in CHF; `difference` = account minus simulation |
| `return_total`, `sim_return_total`, `difference_total` | The same since `since` |
| `holdings_gap` | Share of the account held differently from the simulation: half the sum of the differences per market (0 = the same holdings) |
| `planned`, `sent`, `refused`, `kept_in_cash` | This morning's orders: worked out, taken by IBKR, refused, and markets left in cash |
| `filled`, `partly_filled`, `not_filled` | What became of the orders sent, filled in the next morning (`null` until then) |

`latest` has `date`, `results_of`, `same_close` and:

| Field | Meaning |
| --- | --- |
| `real` | `value`, `currency`, `value_chf`, `cash`, `cash_chf`, `invested`, `positions`, `watchlist_positions` |
| `sim` | `value_chf`, `cash_chf`, `invested`, `positions` |
| `tracking` | The row's returns, `since`, `holdings_gap`, and `tracking_error_yearly`: how much the daily differences swing, scaled to a year (from 5 mornings on) |
| `weights` | Per market, biggest first: `ticker`, `holds_as` (the European fund held instead of a US one, or `null`), `sim`, `real`, `difference` |
| `orders` | `planned`, `sent`, `refused`; `orders` (`ticker`, `holds_as`, `side`, `quantity`, `value` in the account currency, `outcome` "sent" or "refused", `note`); `currency` (currency changes: `currency`, `side`, `amount`, `value`, `outcome`); `kept_in_cash` (`ticker`, `holds_as`, `reason`) |
| `previous_orders` | The orders of the last earlier run and what became of them: `date`, `sent`, `filled`, `partly_filled`, `not_filled`, and `orders` (`ticker`, `holds_as`, `side`, `quantity`, `outcome`: "filled", "partly filled" or "not filled"); `null` on the first morning |

## Going live with Interactive Brokers

1. Add `IBKRProvider(DataProvider)` in `data_manager.py` (`ib.reqHistoricalData`).
2. Add `IBKRBroker(BaseBroker)` in `engine/broker.py`: `submit` places MOO
   orders via `ib_insync`; fills are passed to `Portfolio.record_fill`.
3. Run `prepare` + `calculate_signals` + `execute_trade` once per evening.

The agents and the portfolio accounting do not change.
