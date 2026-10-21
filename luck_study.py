"""Skill or luck: is an agent's lead real, or what random picks get anyway?

With a dozen accounts racing, one of them will lead by luck alone. This
study puts a number on that for every account, against three yardsticks:

* the Monkey (random picks under the same rules and costs), run not once
  but with hundreds of different dice over the same days, which shows how
  far luck alone gets you,
* buy-and-hold SPY, and
* an equal share of every watched market, bought once and held
  (``models/equal_weight_agent.py``). The agents trade Swiss and euro-area
  markets too, so part of any gap to SPY is "the US against Europe", not
  skill; this yardstick takes that part out.

For each account it reports the share of monkeys it beat, its average lead
a year over SPY, over the equal mix and over the typical monkey with a 95%
range, and a verdict:

* "skill": the lead is too big for luck, even allowing for the number of
  agents racing (Holm's correction: the more agents race, the bigger a lead
  must be before it counts),
* "looks like luck": the results rule out an edge of ``edge`` a year,
* "can't tell yet": anything in between, with how many weeks of results it
  would take to spot an edge of that size.

The 95% range comes from a block bootstrap: the account's own days are
resampled in runs of ``block_days``, so calm and wild spells stay together.

Two parts:

* Past prices: what can be replayed honestly, over the last ``years``
  years: the three strategies with fixed settings, their learning versions
  (settings re-picked every year from the 3 years before, as in
  ``walk_forward.py``; replaying the monthly review itself would take
  hours) and the AI Learner. The monkeys share the replay's flaw that the
  markets were picked because they are big today, so the race against them
  stays fair.
* Live: every paper account in ``state/paper_state.json``, from the first
  session it could trade (its join date), against monkeys and an equal mix
  that start with cash on the same day. The news agents, the Opus Learner
  and the Team Manager exist only here.

Usage::

    python luck_study.py                        # real prices, 300 monkeys
    python luck_study.py --source synthetic --monkeys 40

Writes ``docs/data/skill.json`` (its fields are listed in the README) for
the dashboard (Research > Skill or luck?) and prints a table. Pure
NumPy/pandas; no LLM calls.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import time
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

import config
from daily_run import last_completed_session
from data_manager import MarketData, load_market_data
from engine.simulator import Simulator, build_accounts, joined_before_records
from learning import GRIDS, LOOKBACK_YEARS
from main import setup_logging
from models import make_agent
from reporting import write_json
from walk_forward import make_folds, walk_forward_agent

logger = logging.getLogger("vanguard3.luck")

DAYS_PER_YEAR = config.TRADING_DAYS_PER_YEAR
VERDICTS = {"skill": "skill", "unclear": "can't tell yet",
            "luck": "looks like luck"}
#: The yardsticks: shown for reference, never judged.
YARDSTICKS = ("benchmark", "equal_weight", "monkey")
#: What each account is judged against: the monkeys, SPY, the equal mix.
SIDES = ("monkey", "spy", "equal_weight")
#: Strategies replayed with fixed settings and as learning versions.
REPLAYED = ("trend", "reversion", "volatility")
#: Dice of the study's monkeys (the live Monkey uses its own seed, 11).
FIRST_SEED = 1000
#: Fewer sessions say too little about day-to-day swings to estimate how
#: long it will take to tell.
MIN_SPREAD_DAYS = 5
#: Monkeys simulated together (see ``run_monkeys``).
BATCH = 20


# ---------------------------------------------------------------------------
# Statistics (pure NumPy)
# ---------------------------------------------------------------------------
def block_means(x, resamples: int, block: int,
                rng: np.random.Generator) -> np.ndarray:
    """Means of ``resamples`` circular block-bootstrap copies of ``x``.

    Each copy strings together runs of ``block`` consecutive days that
    start on random days (wrapping round at the end), so volatile spells
    and streaks survive the resampling.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    block = max(1, min(block, n))
    starts = rng.integers(0, n, size=(resamples, -(-n // block)))
    idx = (starts[:, :, None] + np.arange(block)) % n
    return x[idx.reshape(resamples, -1)[:, :n]].mean(axis=1)


def lead(diff, s: dict, rng: np.random.Generator) -> dict:
    """Average daily lead as a yearly figure, its 95% range and ``p``.

    ``p`` is the chance of a lead at least this big if the true lead were
    zero (one-sided, from the bootstrap shifted to a zero mean).
    """
    diff = np.asarray(diff, dtype=float)
    n = len(diff)
    if n < 2:
        return {"per_year": None, "low": None, "high": None, "p": None,
                "sd_day": None}
    mean = float(diff.mean())
    boot = block_means(diff, s["resamples"],
                       min(s["block_days"], max(1, n // 4)), rng)
    low, high = np.percentile(boot, [2.5, 97.5])
    p = (1 + int(np.sum(boot - mean >= mean))) / (len(boot) + 1)
    return {"per_year": mean * DAYS_PER_YEAR,
            "low": float(low) * DAYS_PER_YEAR,
            "high": float(high) * DAYS_PER_YEAR,
            "p": p, "sd_day": float(diff.std(ddof=1))}


def monkey_rank(total: float, monkeys) -> tuple[float, float]:
    """Share of monkeys beaten, and ``p``: the chance that a monkey does at
    least as well (a random-portfolio test, exact for any number of days)."""
    monkeys = np.asarray(monkeys, dtype=float)
    beat = float(np.mean(monkeys < total))
    return beat, (1 + int(np.sum(monkeys >= total))) / (len(monkeys) + 1)


def holm(pvalues: list) -> list:
    """Holm's correction for testing many agents at once.

    The smallest ``p`` is multiplied by the number of agents tested, the
    next by one less, and so on (never going down), so "one of them looks
    good" no longer passes for skill. ``None`` entries are left out.
    """
    tested = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    out, worst = [None] * len(pvalues), 0.0
    for rank, (p, i) in enumerate(tested):
        worst = max(worst, min(1.0, (len(tested) - rank) * p))
        out[i] = worst
    return out


def sessions_needed(sd_day, s: dict, tests: int) -> float | None:
    """Sessions of results needed to spot a lead of ``edge`` a year.

    The usual sample-size rule: the lead must stand ``z(alpha / tests) +
    z(power)`` standard errors clear of zero, with ``alpha`` shared out
    over the agents tested (Bonferroni, the first step of Holm's rule).
    """
    if sd_day is None or not math.isfinite(sd_day) or sd_day <= 0:
        return None
    z = NormalDist().inv_cdf
    k = z(1 - s["alpha"] / max(tests, 1)) + z(s["power"])
    return (k * sd_day * DAYS_PER_YEAR / s["edge"]) ** 2


def verdict(p_adjusted, high, sessions: int, s: dict) -> str:
    """``skill``, ``luck`` or ``unclear`` (see ``VERDICTS``)."""
    if p_adjusted is None or sessions < s["min_days"]:
        return "unclear"
    if p_adjusted < s["alpha"]:
        return "skill"
    if high is not None and high < s["edge"]:
        return "luck"
    return "unclear"


# ---------------------------------------------------------------------------
# Comparing accounts with the yardsticks
# ---------------------------------------------------------------------------
def compare(rets: pd.Series, spy: pd.Series, monkeys: pd.DataFrame,
            s: dict, rng: np.random.Generator,
            mix: pd.Series | None = None) -> dict | None:
    """One account against SPY, the monkeys and the equal mix of every
    market (``mix``, when there is one), on the days it has results.

    ``rets`` are the account's daily returns; ``monkeys`` has one column of
    daily returns per monkey. Against the monkeys the lead is measured
    from the typical monkey (their average day).
    """
    days = rets.index.intersection(spy.index).intersection(monkeys.index)
    if mix is not None:
        days = days.intersection(mix.index)
    if len(days) == 0:
        return None
    r, b, m = rets.loc[days], spy.loc[days], monkeys.loc[days]
    e = mix.loc[days] if mix is not None else None
    total = float((1 + r).prod() - 1)
    crowd = (1 + m).prod().to_numpy() - 1
    beat, p = monkey_rank(total, crowd)
    vs_monkey = lead((r - m.mean(axis=1)).to_numpy(), s, rng)
    return {
        "first": days[0].strftime("%Y-%m-%d"),
        "last": days[-1].strftime("%Y-%m-%d"),
        "sessions": len(days),
        "return": total,
        "spy_return": float((1 + b).prod() - 1),
        "monkey_median": float(np.median(crowd)),
        "monkey": {"beat": beat, "p": p, "per_year": vs_monkey["per_year"],
                   "low": vs_monkey["low"], "high": vs_monkey["high"],
                   "sd_day": vs_monkey["sd_day"]},
        "spy": lead((r - b).to_numpy(), s, rng),
        "equal_weight_return": (float((1 + e).prod() - 1)
                                if e is not None else None),
        "equal_weight": (lead((r - e).to_numpy(), s, rng)
                         if e is not None else None),
    }


def judge(results: dict, s: dict, racing: list) -> int:
    """Add Holm-corrected p-values, verdicts and the sessions still needed
    to the ``racing`` entries of ``results`` (in place). Returns how many
    agents were tested together."""
    ids = [i for i in racing if results.get(i)]
    for side in SIDES:
        adjusted = holm([(results[i].get(side) or {}).get("p") for i in ids])
        for i, adj in zip(ids, adjusted):
            res, part = results[i], results[i].get(side)
            if part is None:
                continue
            part["p_adjusted"] = adj
            part["verdict"] = verdict(adj, part["high"], res["sessions"], s)
            need = (sessions_needed(part["sd_day"], s, len(ids))
                    if res["sessions"] >= MIN_SPREAD_DAYS else None)
            part["sessions_needed"] = need
            part["weeks_more"] = (None if need is None else max(
                0.0, max(need, s["min_days"]) - res["sessions"]) / 5)
    return len(ids)


def returns_frame(curves: list[pd.Series]) -> pd.DataFrame:
    """Daily returns of several equity curves, one column each."""
    frame = pd.concat(curves, axis=1, ignore_index=True)
    return frame.pct_change().iloc[1:]


def window(market: MarketData, start: pd.Timestamp,
           end: pd.Timestamp) -> MarketData:
    """The same prices cut to ``start``..``end``.

    Monkeys and buy-and-hold need no history, and a shorter frame makes
    preparing hundreds of them much faster.
    """
    bars = {t: df.loc[start:end] for t, df in market.bars.items()}
    bars = {t: df for t, df in bars.items() if not df.empty}
    return MarketData(bars=bars,
                      fx={c: df.loc[start:end] for c, df in market.fx.items()},
                      currencies={t: market.currencies[t] for t in bars},
                      source=market.source)


def run_monkeys(market: MarketData, days: pd.DatetimeIndex, count: int,
                extra: list | None = None) -> tuple[pd.DataFrame, list]:
    """``count`` monkeys with their own dice, starting with cash on
    ``days[0]``: their daily returns, and the equity curves of the
    ``extra`` agents run alongside them.

    They run in small batches and only their curves are kept: every
    account logs each day it trades, and hundreds of such logs at once
    make the run crawl.
    """
    t0 = time.time()
    # A week before the first day, so every market has a last close.
    cut = window(market, days[0] - pd.Timedelta(days=7), days[-1])
    extra = list(extra or [])
    total, curves = len(extra) + count, []
    for lo in range(0, total, BATCH):
        batch = [extra[i] if i < len(extra) else make_agent(
                     "monkey", {"seed": FIRST_SEED + i - len(extra)})
                 for i in range(lo, min(lo + BATCH, total))]
        sim = Simulator(cut, build_accounts(cut, batch))
        sim.run(days)
        curves += [a.portfolio.equity_curve for a in sim.accounts]
        del sim, batch
        gc.collect()        # free the batch now, not batches later
    logger.info("%d monkeys from %s: %.0fs", count, days[0].date(),
                time.time() - t0)
    return returns_frame(curves[len(extra):]), curves[:len(extra)]


# ---------------------------------------------------------------------------
# Part 1: past prices
# ---------------------------------------------------------------------------
def replay(market: MarketData, s: dict, keys=REPLAYED + ("learner",),
           grids: dict = GRIDS, train_years: int = LOOKBACK_YEARS) -> dict:
    """The last ``years`` years for every agent that can be replayed.

    A rule's result over five years depends a lot on the day it starts
    (started a few days apart, the Trend Follower ended anywhere between
    +22% and +59%). So each agent is replayed from ``starts`` start days
    ``start_gap`` sessions apart, all at or before the test years, every
    copy is judged on the same test years, and the middle one is shown.
    The learning versions come from the walk-forward study, whose blind
    years are the test years. The monkeys and SPY start on the earliest
    start day.
    """
    rng = np.random.default_rng(s["seed"])
    cal = market.calendar
    end = cal[-1]
    folds = make_folds(end, s["years"])
    first = cal[cal >= folds[0][0]][0]          # first day with a result
    at = cal.get_loc(first) - 1                 # the close before it
    offsets = [k * s["start_gap"] for k in range(s["starts"])]
    starts = [cal[at - o] for o in offsets]

    names, copies = {}, {}      # id -> daily returns, one per start day
    t0 = time.time()
    for start in starts:
        agents = {}
        for key in keys:
            if key in REPLAYED:
                agents[f"{key}-fixed"] = make_agent(
                    key, name=f"{make_agent(key).name} (fixed)")
            else:   # the AI Learner trades from day one (no practice mode)
                agents[key] = make_agent(
                    key, {"live_from": start.strftime("%Y-%m-%d")})
        sim = Simulator(market, build_accounts(market, list(agents.values())))
        sim.run(cal[cal >= start])
        for i, acc in zip(agents, sim.accounts):
            names[i] = acc.agent.name
            copies.setdefault(i, []).append(
                acc.portfolio.equity_curve.pct_change().iloc[1:])
    logger.info("Replayed %d agents from %d start days in %.0fs",
                len(keys), len(starts), time.time() - t0)

    base = cal.get_loc(cal[cal >= end - pd.DateOffset(
        years=s["years"] + train_years)][0])
    for key in keys:
        if key in REPLAYED and key in grids:
            names[key] = make_agent(key).name
            for o in offsets:
                wf = walk_forward_agent(market, key, grids[key],
                                        cal[base - o], folds, train_years)
                copies.setdefault(key, []).append(wf["tuned"])

    refs = [make_agent(key) for key in YARDSTICKS]
    monkeys, curves = run_monkeys(market, cal[cal >= starts[-1]],
                                  s["monkeys"], refs)
    monkeys = monkeys.loc[first:]
    for i, agent, curve in zip(YARDSTICKS, refs, curves):
        copies[i], names[i] = [curve.pct_change().iloc[1:]], agent.name

    spy = copies["benchmark"][0].loc[first:]
    mix = copies["equal_weight"][0].loc[first:]
    results = {}
    for i, series in copies.items():
        runs = sorted((compare(r.loc[first:], spy, monkeys, s, rng, mix)
                       for r in series), key=lambda r: r["return"])
        results[i] = runs[len(runs) // 2]
        if len(runs) > 1:
            results[i]["returns_by_start_day"] = [r["return"] for r in runs]
    results["benchmark"]["spy"] = None
    results["equal_weight"]["equal_weight"] = None
    tests = judge(results, s, [i for i in results if i not in YARDSTICKS])
    crowd = (1 + monkeys).prod() - 1
    return {"from": cal[at].strftime("%Y-%m-%d"),
            "last": end.strftime("%Y-%m-%d"),
            "sessions": len(cal[cal >= first]),
            "start_days": [d.strftime("%Y-%m-%d") for d in starts],
            "years": s["years"], "monkeys": s["monkeys"], "tested": tests,
            "monkey_returns": sorted(float(v) for v in crowd),
            "results": results, "names": names}


# ---------------------------------------------------------------------------
# Part 2: the live paper accounts
# ---------------------------------------------------------------------------
def account_id(account: dict) -> str:
    """Dashboard id of a saved account (``trend``, ``trend-fixed``, ...)."""
    return account["agent"] + ("-fixed" if "(fixed)" in account["name"]
                               else "")


def joined(account: dict) -> pd.Timestamp | None:
    """First session a saved account could trade (see ``Account.joined``).

    The days before are left out: it was not in the race yet (an account
    added later is filled in with its starting cash), or it was practising
    without orders. Waiting in cash after joining counts: that is a choice.
    """
    if "joined" in account:
        return pd.Timestamp(account["joined"]) if account["joined"] else None
    agent = make_agent(account["agent"], account["params"],
                       name=account.get("name"))
    return joined_before_records(account, agent)


def live(state: dict, market: MarketData, s: dict) -> dict:
    """Every paper account from the session it joined on.

    Each join date gets its own monkeys and its own equal mix of every
    market, so every account meets yardsticks that start with cash on the
    same day. SPY is the live Buy & Hold SPY account over the same days.
    """
    rng = np.random.default_rng(s["seed"] + 1)
    last = pd.Timestamp(state["last_date"])
    cal = market.calendar[market.calendar <= last]
    accounts = {}
    for a in state["accounts"]:
        equity = pd.Series({pd.Timestamp(d): float(v) for d, v in
                            a["portfolio"]["equity"].items()}).sort_index()
        accounts[account_id(a)] = (a, equity, joined(a))
    if "benchmark" not in accounts:
        raise ValueError("The paper state has no Buy & Hold SPY account")
    spy = accounts["benchmark"][1].pct_change().iloc[1:]

    crowds, mixes = {}, {}
    for since in sorted({v[2] for v in accounts.values() if v[2] is not None}):
        days = cal[cal >= since]
        if len(days) >= 2:
            crowds[since], (curve,) = run_monkeys(
                market, days, s["monkeys"], [make_agent("equal_weight")])
            mixes[since] = curve.pct_change().iloc[1:]

    results, names = {}, {}
    for i, (a, equity, since) in accounts.items():
        names[i] = a["name"]
        res = None
        if since in crowds:
            res = compare(equity.loc[since:].pct_change().iloc[1:], spy,
                          crowds[since], s, rng, mixes[since])
        if res:
            res["since"] = since.strftime("%Y-%m-%d")
        results[i] = res
    if results["benchmark"]:
        results["benchmark"]["spy"] = None
    if results.get("equal_weight"):
        results["equal_weight"]["equal_weight"] = None
    racing = [i for i, v in accounts.items() if v[0]["agent"] not in YARDSTICKS]
    tests = judge(results, s, racing)
    first = min(v[1].index[0] for v in accounts.values())
    return {"from": first.strftime("%Y-%m-%d"),
            "last": last.strftime("%Y-%m-%d"), "monkeys": s["monkeys"],
            "tested": tests, "results": results, "names": names,
            "order": list(accounts)}


# ---------------------------------------------------------------------------
# Plain words, the report and the table
# ---------------------------------------------------------------------------
#: Why an account has no replay on past prices.
NOT_REPLAYED = {
    "news": "it asks Claude, who already knows how those years turned out",
    "news_opus": "it asks Claude, who already knows how those years turned out",
    "learner_opus": "Claude reviews its picks and already knows how those "
                    "years turned out",
    "manager": "it copies the other agents, the news agents included",
}


def _signed(v: float, digits: int = 0) -> str:
    return f"{v * 100:+.{digits}f}%"


def _often(p: float) -> str:
    """How often luck alone does this well, in words."""
    if p >= 0.995:
        return "almost every time"
    return f"about {p:.0%} of the time"


def _weeks(weeks: float) -> str:
    if weeks < 1:
        return "less than a week"
    if weeks > 104:
        return f"about {weeks:,.0f} more weeks ({weeks / 52:.0f} years)"
    return f"about {weeks:.0f} more weeks"


def _years(n: int) -> str:
    return f"{n} year" if n == 1 else f"{n} years"


def _day(date: str) -> str:
    d = pd.Timestamp(date)
    return f"{d.day} {d:%b %Y}"


def summary(row: dict, history: dict | None, live_part: dict | None,
            s: dict) -> list[str]:
    """Plain sentences on one account, written from the numbers: one
    paragraph on the past prices, one on the live results."""
    h, lv, out = row["history"], row["live"], []
    edge = f"{s['edge']:.0%}"
    if row["yardstick"]:
        if h:
            out.append(f"Past {_years(history['years'])}: "
                       f"{_signed(h['return'])}, ahead of "
                       f"{h['monkey']['beat']:.0%} of the "
                       f"{history['monkeys']} monkeys.")
        if lv:
            out.append(f"Live: {_signed(lv['return'], 1)} since "
                       f"{_day(lv['since'])}, ahead of "
                       f"{lv['monkey']['beat']:.0%} of the monkeys.")
        return out or ["No results yet."]

    if h:
        m, b, n = h["monkey"], h["spy"], history["tested"]
        text = (f"Past {_years(history['years'])}: it beat {m['beat']:.0%} "
                f"of {history['monkeys']} monkeys")
        if m["verdict"] == "skill":
            text += (f"; luck does that less than 1 time in 20, even with "
                     f"{n} agents tested: skill.")
        elif m["verdict"] == "luck" and m["beat"] < 0.5:
            text += (f"; random picks did better {1 - m['beat']:.0%} of the "
                     f"time, so it shows no edge: looks like luck.")
        elif m["verdict"] == "luck":
            text += (f"; any edge over random picks is under {edge} a year: "
                     f"looks like luck.")
        elif m["beat"] >= 0.5:
            text += (f"; luck alone puts one of {n} agents this high "
                     f"{_often(m['p_adjusted'])}, so we can't tell yet.")
        else:
            text += (f", no better than most random picks, though an edge "
                     f"of {edge} a year is not ruled out yet: can't tell yet.")
        text += (f" Against SPY: {_signed(b['per_year'], 1)} a year (95% "
                 f"range {_signed(b['low'])} to {_signed(b['high'])}): "
                 f"{VERDICTS[b['verdict']]}.")
        e = h.get("equal_weight")
        if e:
            text += (f" Against an equal share of every market: "
                     f"{_signed(e['per_year'], 1)} a year: "
                     f"{VERDICTS[e['verdict']]}.")
        spread = h.get("returns_by_start_day")
        if spread:
            text += (f" Started on {len(spread)} different days, it ended "
                     f"between {_signed(spread[0])} and {_signed(spread[-1])}"
                     f"; these figures are for the middle one.")
        out.append(text)
    elif row["key"] in NOT_REPLAYED:
        out.append(f"No replay on past prices: {NOT_REPLAYED[row['key']]}.")

    if lv is None:
        out.append("Live: no decisions yet.")
        return out
    m, b, n = lv["monkey"], lv["spy"], lv["sessions"]
    if n < s["min_days"]:
        text = (f"Live: {n} sessions since {_day(lv['since'])}, too few to "
                f"judge (it takes at least {s['min_days']}); so far "
                f"{_signed(lv['return'], 1)}, ahead of {m['beat']:.0%} of "
                f"the monkeys.")
    else:
        text = (f"Live: {n} sessions since {_day(lv['since'])}, ahead of "
                f"{m['beat']:.0%} of {live_part['monkeys']} monkeys: "
                f"{VERDICTS[m['verdict']]}. Against SPY: "
                f"{_signed(b['per_year'], 1)} a year: "
                f"{VERDICTS[b['verdict']]}.")
        e = lv.get("equal_weight")
        if e:
            text += (f" Against an equal share of every market: "
                     f"{_signed(e['per_year'], 1)} a year: "
                     f"{VERDICTS[e['verdict']]}.")
    if m["verdict"] == "unclear" and m.get("weeks_more") is not None:
        text += (f" Spotting an edge of {edge} a year over random picks "
                 f"would take {_weeks(m['weeks_more'])} of results.")
    elif m["verdict"] == "unclear":
        text += " Too early to say how long it will take."
    out.append(text)
    return out


def method(s: dict) -> str:
    """Short plain-language account of the method, for skill.json."""
    return (
        f"Every account is compared with {s['monkeys']} monkeys (random "
        f"picks under the same rules and costs, each with its own dice), "
        f"with buy-and-hold SPY and with an equal share of every watched "
        f"market bought once and held, over exactly the same days: on the "
        f"last {s['years']} years of prices for the agents that can be "
        f"replayed, and live from the first session each account could "
        f"trade. A lead counts as "
        f"skill only when luck explains it less than 1 time in "
        f"{1 / s['alpha']:.0f} after allowing for the number of agents "
        f"racing (Holm's correction). It looks like luck when the results "
        f"rule out an edge of {s['edge']:.0%} a year. Anything in between: "
        f"can't tell yet. Ranges are 95% ranges from a block bootstrap of "
        f"the account's own days.")


#: What each verdict means, keyed by the label used in skill.json.
VERDICT_MEANINGS = {
    VERDICTS["skill"]: "The lead is too big for luck, even allowing for "
                       "the number of agents racing.",
    VERDICTS["unclear"]: "Neither skill nor luck can be ruled out yet.",
    VERDICTS["luck"]: "The results rule out a real edge of the size worth "
                      "having (see settings.edge).",
}


def _label(code: str | None) -> str | None:
    return VERDICTS[code] if code else None


def export_part(res: dict | None, start: str,
                is_live: bool) -> dict | None:
    """One account's results for one part (past or live), flat and with
    the same fields in both parts. Fractions: 0.1 means 10%. Weeks still
    needed only make sense live, and only while it can't tell yet."""
    if res is None:
        return None
    m, b, e = res["monkey"], res["spy"] or {}, res.get("equal_weight") or {}
    live_weeks = lambda part: (part.get("weeks_more") if is_live
                               and part.get("verdict") == "unclear" else None)
    return {
        "from": start, "to": res["last"], "days": res["sessions"],
        "return": res["return"],
        "spy_return": res["spy_return"],
        "monkey_median_return": res["monkey_median"],
        "percentile_vs_monkeys": m["beat"],
        "verdict": _label(m.get("verdict")),
        "excess_vs_monkey": m["per_year"],
        "excess_vs_monkey_low": m["low"],
        "excess_vs_monkey_high": m["high"],
        "p_vs_monkeys": m["p"],
        "p_vs_monkeys_adjusted": m.get("p_adjusted"),
        "weeks_needed": live_weeks(m),
        "verdict_vs_spy": _label(b.get("verdict")),
        "excess_vs_spy": b.get("per_year"),
        "excess_vs_spy_low": b.get("low"),
        "excess_vs_spy_high": b.get("high"),
        "p_vs_spy": b.get("p"),
        "p_vs_spy_adjusted": b.get("p_adjusted"),
        "weeks_needed_vs_spy": live_weeks(b),
        "returns_by_start_day": res.get("returns_by_start_day"),
        "equal_weight_return": res.get("equal_weight_return"),
        "verdict_vs_equal_weight": _label(e.get("verdict")),
        "excess_vs_equal_weight": e.get("per_year"),
        "excess_vs_equal_weight_low": e.get("low"),
        "excess_vs_equal_weight_high": e.get("high"),
        "p_vs_equal_weight": e.get("p"),
        "p_vs_equal_weight_adjusted": e.get("p_adjusted"),
        "weeks_needed_vs_equal_weight": live_weeks(e),
    }


def build_report(history: dict | None, live_part: dict | None, s: dict,
                 source: str) -> dict:
    """The contents of ``docs/data/skill.json`` (fields in the README):
    one entry per account, racing accounts in the live order first, the
    yardsticks last."""
    order = list(live_part["order"]) if live_part else []
    order += [i for i in (history or {}).get("results", {}) if i not in order]
    order.sort(key=lambda i: i.removesuffix("-fixed") in YARDSTICKS)
    accounts = []
    for i in order:
        h = history["results"].get(i) if history else None
        lv = live_part["results"].get(i) if live_part else None
        key = i.removesuffix("-fixed")
        row = {"id": i, "key": key, "yardstick": key in YARDSTICKS,
               "history": h, "live": lv}
        past = export_part(h, history["from"], False) if h else None
        now = export_part(lv, lv["since"], True) if lv else None
        # The headline: live once there are enough live days, else the
        # replay of past prices; never for the yardsticks.
        if row["yardstick"]:
            verdict, source_of = None, None
        elif now and now["days"] >= s["min_days"]:
            verdict, source_of = now["verdict"], "live"
        elif past:
            verdict, source_of = past["verdict"], "past prices"
        else:
            verdict, source_of = VERDICTS["unclear"], None
        accounts.append({
            "id": i, "key": key,
            "name": ((live_part or {}).get("names", {}).get(i)
                     or history["names"][i]),
            "fixed_twin": i.endswith("-fixed"),
            "yardstick": row["yardstick"],
            "verdict": verdict, "verdict_from": source_of,
            "summary": summary(row, history, live_part, s),
            "past": past, "live": now,
        })

    def meta(part, extra):
        return {"from": part["from"], "to": part["last"],
                "monkeys": part["monkeys"],
                "agents_tested": part["tested"], **extra} if part else None

    last = (live_part or history)["last"]
    return {"generated_utc": pd.Timestamp.now(tz="UTC").isoformat(
                timespec="seconds"),
            "as_of": last, "data_source": source, "method": method(s),
            "verdict_meanings": VERDICT_MEANINGS, "settings": s,
            "past": meta(history, history and {
                "years": history["years"], "days": history["sessions"],
                "start_days": history["start_days"],
                "monkey_returns": history["monkey_returns"]}),
            "live": meta(live_part, {}),
            "accounts": accounts}


def run(source: str, s: dict, state_path: Path | None,
        seed: int = config.SYNTHETIC_SEED,
        today: pd.Timestamp | None = None, **replay_kw) -> dict:
    """Load prices, run both parts and return the report."""
    # Only finished sessions: during the day Yahoo also sends today's bar.
    today = today or last_completed_session()
    data_start = (today - pd.DateOffset(years=s["years"] + LOOKBACK_YEARS)
                  - pd.Timedelta(days=config.WARMUP_DAYS
                                 + 2 * s["starts"] * s["start_gap"]))
    market = load_market_data(source, data_start, today, seed=seed,
                              strict={config.BENCHMARK_TICKER})
    history = replay(market, s, **replay_kw)
    state = (json.loads(state_path.read_text())
             if state_path and state_path.exists() else None)
    # Live accounts traded real prices: made-up prices (the fallback when
    # the download fails) would make the monkeys meaningless.
    if state and market.source == "synthetic" and source != "synthetic":
        logger.warning("No real prices: the live part is left out")
        state = None
    live_part = live(state, market, s) if state else None
    return build_report(history, live_part, s, market.source)


def print_report(report: dict) -> None:
    h, lv, s = report["past"], report["live"], report["settings"]

    def beat(part):
        return f"{part['percentile_vs_monkeys']:.0%}" if part else "-"

    live_days = f"{lv['from']} -> {lv['to']}" if lv else "none"
    print()
    print("=" * 112)
    print(f" SKILL OR LUCK  |  past {h['years']} years {h['from']} -> "
          f"{h['to']}, {h['agents_tested']} agents tested  |  live "
          f"{live_days}  |  {s['monkeys']} monkeys  |  "
          f"data: {report['data_source']}")
    print("=" * 112)
    print(f" {'Agent':<29}{'Past: beat':>11}  {'verdict':<16}{'vs SPY':>8}  "
          f"{'verdict':<16}{'Live: days':>10}{'beat':>6}  "
          f"{'weeks to tell':>13}")
    for acc in report["accounts"]:
        past, now = acc["past"], acc["live"]
        spy = (past or {}).get("excess_vs_spy")
        weeks = (now or {}).get("weeks_needed")
        print(f" {acc['name']:<29}{beat(past):>11}  "
              f"{(past or {}).get('verdict') or '':<16}"
              f"{_signed(spy, 1) if spy is not None else '':>8}  "
              f"{(past or {}).get('verdict_vs_spy') or '':<16}"
              f"{now['days'] if now else '-':>10}"
              f"{beat(now) if now else '':>6}  "
              f"{f'{weeks:,.0f}' if weeks is not None else '':>13}")
    print(f" Beat = share of the {s['monkeys']} monkeys (random picks, same "
          f"rules and costs) it did better than. vs SPY = average lead a "
          f"year.")
    print(f" Weeks to tell = live weeks still needed to spot an edge of "
          f"{s['edge']:.0%} a year over random picks.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=config.DATA_SOURCE,
                        choices=["auto", "yfinance", "synthetic"])
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("--out", type=Path,
                        default=config.DASHBOARD_DATA_DIR / "skill.json")
    parser.add_argument("--monkeys", type=int,
                        default=config.LUCK_PARAMS["monkeys"])
    parser.add_argument("--years", type=int,
                        default=config.LUCK_PARAMS["years"])
    parser.add_argument("--seed", type=int, default=config.SYNTHETIC_SEED,
                        help="seed for synthetic data")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    s = {**config.LUCK_PARAMS, "monkeys": args.monkeys, "years": args.years}
    report = run(args.source, s, args.state, seed=args.seed)
    write_json(report, args.out)
    print_report(report)
    print(f" Written to {args.out}")


if __name__ == "__main__":
    main()
