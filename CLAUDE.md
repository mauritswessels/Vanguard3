# Vanguard3: notes for Claude

End-of-day paper-trading race: 13 accounts (rule-based agents and their
fixed twins, an RL learner, Claude-driven news agents, a Team Manager, the
Monkey and buy-and-hold SPY) each trade 100,000 CHF on 108 IBKR-tradable
markets. GitHub Actions runs it every weekday and GitHub Pages serves the
dashboard from `docs/`. `README.md` is the full manual with a layout table.
Read the section you need there instead of exploring the whole repo.

## Before you change anything

- **Pull first.** Bots commit to `main` several times every weekday
  ("Paper trading update", "Midday news check", "Backtest update", "Weekly
  report"), so a local checkout falls behind within a day. Run
  `git pull --ff-only` before editing and rebase on `origin/main` before
  pushing.
- **Python.** On macOS the command is `python3`; run everything through
  `.venv/bin/python`. Tests need `requirements.txt` (pandas, NumPy,
  yfinance). `requirements-ibkr.txt` alone is not enough. CI uses Python
  3.12.

## Commands

```bash
.venv/bin/python -m unittest discover -s tests -t .   # all tests, offline
.venv/bin/python main.py --source synthetic --seed 7 --days 730   # offline backtest
.venv/bin/python walk_forward.py                      # tune on the past, test blind
.venv/bin/python ibkr_bridge.py                       # IBKR plan only, sends nothing
```

Two tests in `tests/test_ibkr_schedule.py` fail on macOS because
`ibkr_morning.sh` uses GNU `date -d` (it runs on the Ubuntu server). CI on
Ubuntu is the reference.

## Rules that keep the simulation honest

- **No look-ahead.** Agents decide after the close of day t using data up
  to t, and orders fill at the open of t+1. Tests check this. Never weaken
  them.
- **Accounting.** Cash never goes negative, buys are scaled to the cash
  that is free (waiting orders keep theirs reserved), and every fill pays
  the costs in `config.py` (2 CHF, 5 bp slippage, 2 bp FX). Buys under
  `MIN_ORDER_CHF` are skipped.
- **News agents** decide only for the newest session and cannot be
  backtested, because the model already knows how past markets went.
- **Rule-based agents stay pure pandas/NumPy**, with no LLM calls.
- **Bot output is not hand-edited:** `state/paper_state.json` and
  `docs/data/*.json`. These files are large (`backtest.json` is about 4 MB),
  so pull out the part you need with Python instead of reading them whole.
- **Accounts are matched by agent key and name.** Adding one to
  `paper_lineup()` in `learning.py` opens a fresh account on the next run.
  Renaming a live agent does the same and leaves the old account running,
  so only rename when that is the intent.

## Claude API and money

- Every Claude call goes through `claude_api.call_claude` (plain `urllib`,
  no SDK). Keep it that way: no new dependencies.
- Models and rough per-token prices live in `config.py` (`NEWS_PARAMS`,
  `NEWS_OPUS_PARAMS`, `LEARNER_OPUS_PARAMS`). The weekly report uses
  `NEWS_PARAMS["model"]`.
- Live calls are billed to the `ANTHROPIC_API_KEY` secret. Don't run
  `news.py`, `midday_news.py` or `weekly_report.py` with a key set unless
  asked. Tests mock the API, and a test must never make a real call.
- Never commit or print secrets. `server/.env`, `server/ib_password.txt`,
  `ibkr_morning.env` and `ibkr_logs/` are gitignored and must stay so.

## IBKR bridge: be careful

- `ibkr_bridge.py` trades **paper accounts only** (IDs starting with "D").
  Never weaken that check, and never add a path to a live account unless
  the user explicitly asks for one.
- `--send` places orders. Don't run it yourself. Without it the bridge
  only shows the plan.
- It runs on a cloud server (`server/setup.sh`, 08:30 Swiss time every
  weekday), and each run pulls `main` first. **Anything merged to `main`
  trades the next morning**, so review changes to the bridge, order or cash
  logic with extra care (`/code-review` before merging).

## Making changes

- Work on a branch and open a PR to `main`. The "Tests" workflow runs on
  every PR, and the evening run uses whatever is merged.
- Run the full test suite before committing. Add tests next to the
  existing ones: `unittest`, synthetic data, offline and deterministic.
- Update `README.md` (including its layout table) when behaviour changes.
  It is the owner's manual.
- Match the surrounding code: a module docstring that says in plain words
  what the file does, `from __future__ import annotations`, and comments
  that explain why.
- Write commit messages, dashboard text and explanations in plain English
  without jargon. A commit has a one-line summary of what changes for the
  user, then bullets on what and why. `git log` shows the style.
