"""How the agents learn: a monthly review of their own settings.

On the first trading day of every month, each learning agent replays its
strategy over the last ``LOOKBACK_YEARS`` of prices for every setting in its
grid (including the settings it is using now). It switches only when a
different setting has a clearly better Sharpe ratio, so it does not flip
back and forth on noise. Every review is logged, switch or not, and shown on
the dashboard.

Each learning agent runs next to an identical "fixed" twin that never
changes its settings, so the dashboard shows whether learning actually
helps. Pure NumPy/pandas; no LLM calls.
"""

from __future__ import annotations

import itertools
import logging
import math

import pandas as pd

import config
from engine import metrics
from engine.simulator import Simulator, build_accounts
from models import agent_key, make_agent

logger = logging.getLogger("vanguard3.learning")

LOOKBACK_YEARS = 3       # history each review looks at
MIN_TRADES = 10          # settings that barely trade cannot be judged
SWITCH_MARGIN = 0.10     # Sharpe improvement needed to change settings

#: Settings each strategy may choose from. Every combination is replayed.
GRIDS = {
    "trend": {
        ("ema_fast", "ema_slow"): [(10, 30), (20, 50), (50, 200)],
        "adx_threshold": [20.0, 25.0, 30.0],
    },
    "reversion": {
        "rsi_entry": [30.0, 35.0, 40.0],
        "bb_std": [1.5, 2.0],
        "quality_sma": [0, 200],
    },
    "volatility": {
        ("donchian_entry", "donchian_exit"): [(20, 10), (40, 20), (55, 20)],
        "atr_stop_mult": [2.5, 3.5, 4.5],
    },
}

#: Safety rules tried on top of the best core settings at every review
#: (see ``BaseAgent.guard``); 0 means off.
SAFETY_GRID = {
    "market_filter": [0, 200],
    "stop_loss_pct": [0.0, 0.12],
    "max_corr": [0.0, 0.8],
}


def expand(grid: dict) -> list[dict]:
    """All parameter combinations of a grid as flat dicts."""
    keys, values = zip(*grid.items())
    combos = []
    for choice in itertools.product(*values):
        params = {}
        for k, v in zip(keys, choice):
            if isinstance(k, tuple):
                params.update(dict(zip(k, v)))
            else:
                params[k] = v
        combos.append(params)
    return combos


def evaluate(key: str, params: dict, market, start: pd.Timestamp,
             end: pd.Timestamp) -> tuple[float, int]:
    """Sharpe ratio and number of fills of one setting over a window."""
    agent = make_agent(key, params)
    sim = Simulator(market, build_accounts(market, [agent]))
    cal = market.calendar
    sim.run(cal[(cal >= start) & (cal <= end)])
    pf = sim.accounts[0].portfolio
    eq = pd.concat([pd.Series([pf.initial_cash]),
                    pf.equity_curve.reset_index(drop=True)])
    return metrics.sharpe_ratio(metrics.daily_returns(eq)), len(pf.trades)


def retune(agent, market, as_of: pd.Timestamp) -> dict:
    """Monthly review: maybe switch ``agent`` to better settings.

    Uses only data up to ``as_of`` (the last completed session).
    """
    key = agent_key(agent)
    safety_now = {k: agent.params.get(k, v[0]) for k, v in SAFETY_GRID.items()}
    # Step 1: the strategy's own settings, keeping today's safety rules.
    candidates = [{**c, **safety_now} for c in expand(GRIDS[key])]
    current = {k: agent.params[k] for k in candidates[0]}
    if current not in candidates:
        candidates.append(current)
    start = as_of - pd.DateOffset(years=LOOKBACK_YEARS)

    scores = {}

    def score(params: dict) -> None:
        sharpe, trades = evaluate(key, params, market, start, as_of)
        if trades >= MIN_TRADES and math.isfinite(sharpe):
            scores[_label(params)] = (sharpe, params)

    for params in candidates:
        score(params)
    # Step 2: every mix of safety rules on top of the best of step 1.
    if scores:
        core = max(scores.values(), key=lambda s: s[0])[1]
        for safety in expand(SAFETY_GRID):
            params = {**core, **safety}
            if params not in candidates:
                candidates.append(params)
                score(params)

    now = scores.get(_label(current))
    best = max(scores.values(), key=lambda s: s[0]) if scores else None
    switch = (best is not None and best[1] != current
              and (now is None or best[0] >= now[0] + SWITCH_MARGIN))
    if switch:
        agent.params.update(best[1])
        agent.prepare(market)

    entry = {
        "date": as_of.strftime("%Y-%m-%d"),
        "switched": switch,
        "old": current,
        "new": best[1] if switch else current,
        "sharpe_old": now[0] if now else None,
        "sharpe_best": best[0] if best else None,
        "tested": len(candidates),
    }
    agent.learning_log.append(entry)
    outcome = f"switched to {_label(best[1])}" if switch else "kept settings"
    logger.info("%s review %s: %s", agent.name, entry["date"], outcome)
    return entry


def _label(params: dict) -> str:
    return ", ".join(f"{k}={params[k]}" for k in sorted(params))


def paper_lineup(market) -> list:
    """Live lineup: each strategy as a learner plus its fixed twin."""
    agents = []
    for key in ("trend", "reversion", "volatility"):
        learner = make_agent(key, learning=True)
        agents.append(learner)
        agents.append(make_agent(key, name=f"{learner.name} (fixed)"))
    # Learns every day by itself (reinforcement learning, see learner_agent).
    agents.append(make_agent("learner"))
    # The same learner, with Claude Opus approving its picks each evening.
    agents.append(make_agent("learner_opus"))
    # Reads the news with Claude each evening (needs ANTHROPIC_API_KEY).
    agents.append(make_agent("news"))
    # The same, on a stronger model: is a smarter AI a better trader?
    agents.append(make_agent("news_opus"))
    if config.BENCHMARK_TICKER in market.bars:
        agents.append(make_agent("benchmark"))
    # An equal share of every watched market: the wider yardstick.
    agents.append(make_agent("equal_weight"))
    # Backs the agents with the best recent results (goes after them).
    agents.append(make_agent("manager"))
    # Random picks: shows how far luck alone gets you.
    agents.append(make_agent("monkey"))
    return agents
