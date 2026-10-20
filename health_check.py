"""Checks that the paper accounts are up to date, for the alert emails.

Run by the GitHub workflows after each run::

    python health_check.py --out health.md

Writes a short list of problems to ``--out`` (and nothing if all is well).
The workflow then opens or updates a GitHub issue, which GitHub emails to
the repository owner. It looks for:

* accounts that are behind the latest finished trading session (a run that
  failed, or a scheduled run GitHub never started),
* a News Analyst or the Opus Learner that could not make its latest
  decision,
* orders that did not go through in the latest session (not enough cash,
  or their market did not open for a week),
* with ``--midday``: a News Analyst whose midday check failed today.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

import config
from daily_run import last_completed_session
from models import CLAUDE_KEYS

logger = logging.getLogger("vanguard3.health")


def latest_session(now: pd.Timestamp | None = None,
                   sessions: list[pd.Timestamp] | None = None
                   ) -> pd.Timestamp:
    """Latest finished trading session.

    ``sessions`` are recent dates the benchmark traded, which skips market
    holidays; without them every weekday counts as a session.
    """
    cutoff = last_completed_session(now)
    if sessions:
        done = [d for d in sessions if d <= cutoff]
        if done:
            return max(done)
    while cutoff.weekday() >= 5:
        cutoff -= pd.Timedelta(days=1)
    return cutoff


def recent_sessions() -> list[pd.Timestamp] | None:
    """Days SPY traded in the last two weeks (None if Yahoo fails)."""
    try:
        import yfinance as yf
        bars = yf.Ticker(config.BENCHMARK_TICKER).history(period="14d")
        return [pd.Timestamp(d.date()) for d in bars.index]
    except Exception as exc:  # the check must never crash the workflow
        logger.warning("Could not load the trading calendar: %s", exc)
        return None


#: Why an order did not go through, in plain words.
WHY = {"insufficient cash": "there was not enough cash",
       "expired": "its market did not open for a week",
       "no position": "there was nothing left to sell",
       "no session": "its market was closed"}


def problems(state: dict | None, expected: pd.Timestamp,
             today: pd.Timestamp | None = None,
             midday: bool = False) -> list[str]:
    """Plain-English problems with the saved paper accounts. ``midday``
    checks the midday run instead of the evening's orders."""
    if not state:
        return ["The paper accounts could not be found."]
    out = []
    last = pd.Timestamp(state["last_date"])
    if last < expected:
        out.append(f"The accounts were last updated for {last:%a %d %b}, but "
                   f"the latest finished trading day is {expected:%a %d %b}. "
                   "The evening run failed or did not start (or Yahoo had no "
                   "European prices for that day yet; on a European holiday "
                   "that is normal). The next successful run catches up.")
    for acc in state["accounts"]:
        name = acc.get("name", acc["agent"])
        s = acc["agent_state"]
        if acc["agent"] in CLAUDE_KEYS and s.get("decided") != state["last_date"]:
            out.append(f"The {acc.get('name', 'News Analyst')} made no decision for "
                       f"{last:%a %d %b}: {s.get('status', 'no reason given')}")
        if midday:
            m = s.get("midday") or {}
            day = (today or pd.Timestamp.now(tz="UTC")).strftime("%Y-%m-%d")
            if m.get("time", "").startswith(day) and not m.get("ok", True):
                out.append(f"The {name}'s midday check failed: "
                           f"{m.get('status', 'no reason given')}")
            continue
        for entry in acc.get("activity", []):
            if entry["date"] != state["last_date"]:
                continue
            for r in entry.get("rejected", []):
                out.append(
                    f"{name}: the order to {r['side'].lower()} {r['quantity']} "
                    f"{r['ticker']} (from {pd.Timestamp(r['created']):%a %d %b}) "
                    f"did not go through: {WHY.get(r['why'], r['why'])}.")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("--out", type=Path, default=Path("health.md"))
    parser.add_argument("--midday", action="store_true",
                        help="check the midday run instead of the evening's "
                             "orders")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    state = (json.loads(args.state.read_text())
             if args.state.exists() else None)
    found = problems(state, latest_session(sessions=recent_sessions()),
                     midday=args.midday)
    if found:
        args.out.write_text("".join(f"- {p}\n" for p in found))
        logger.warning("Problems found:\n%s", "\n".join(found))
    else:
        args.out.unlink(missing_ok=True)
        logger.info("All accounts are up to date")


if __name__ == "__main__":
    main()
