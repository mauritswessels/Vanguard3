"""Report cards: was each trade a good call, judged against SPY?

Every fill, buy or sell, is graded by what its market did next compared
with SPY (the S&P 500 fund every account races):

* a buy was right if the market then beat SPY,
* a sell was right if the market then did worse than SPY.

The "edge" is that gap (0.02 = 2 percentage points; above zero = right).
Each fill is graded twice, at the close 5 and 20 trading days after the day
it filled. The market and SPY are measured over the same stretch, in the
market's own currency (FX moves do not count), from:

* the open of the fill day, for an order filled at the open (the usual
  case: decided after one close, filled at the next open);
* the close of the fill day, for a midday trade (decided and filled during
  the same session), because the agent had already seen that morning.

Prices come from the adjusted price panel (dividends and splits included),
so a split or a dividend never looks like a gain or a loss. A fill counts as
"pending" until its window has passed, and only prices up to the day of the
card are used. Trades in SPY itself are not graded: SPY cannot beat itself.

Returns need years to tell skill from luck (see ``luck_study.py``); grading
every call gives many more data points a week.
"""

from __future__ import annotations

import math
import statistics

import pandas as pd

import config

#: Trading days after the fill day at which each call is graded.
HORIZONS = (5, 20)
#: Latest graded calls listed in each card.
RECENT_CALLS = 20


def grade_fills(fills, market, as_of: pd.Timestamp) -> list[dict]:
    """Grade every fill up to ``as_of``, oldest first.

    ``fills`` are mappings with ``date`` (the fill day), ``ticker``,
    ``side`` and optionally ``decided`` (the session whose data the decision
    used) and ``id``, as in ``journal.fills``. Each call comes back with
    ``edge_5`` / ``edge_20`` once that window has passed, and with
    ``pending`` while the first one has not.
    """
    as_of = pd.Timestamp(as_of)
    cal = market.calendar[market.calendar <= as_of]
    opens, closes = market.open_panel, market.close_panel
    bench = config.BENCHMARK_TICKER
    calls = []
    for f in fills:
        day = pd.Timestamp(f["date"])
        if day > as_of:
            continue                      # has not happened yet as of then
        decided = f.get("decided")
        call = {"date": day.strftime("%Y-%m-%d"), "ticker": f["ticker"],
                "side": f["side"],
                "decided": (pd.Timestamp(decided).strftime("%Y-%m-%d")
                            if decided is not None else None)}
        if f.get("id") is not None:
            call["fill"] = f["id"]
        calls.append(call)
        t = f["ticker"]
        # A market that failed to download today has no column.
        if t == bench or day not in cal or t not in closes or bench not in closes:
            continue
        i = cal.get_loc(day)
        if i + HORIZONS[0] >= len(cal):
            call["pending"] = True
        start = _start(opens, closes, day, t, bench,
                       midday=call["decided"] == call["date"])
        sign = 1 if f["side"] == "BUY" else -1
        for h in HORIZONS:
            if i + h >= len(cal):
                continue
            later = cal[i + h]
            move = float(closes.at[later, t]) / start[0] - 1
            spy = float(closes.at[later, bench]) / start[1] - 1
            edge = (move - spy) * sign
            if math.isfinite(edge):
                call[f"edge_{h}"] = round(edge, 4)
    return calls


def _start(opens, closes, day, ticker, bench, midday: bool) -> tuple:
    """Prices (market, SPY) the grading window starts from."""
    m, b = float(opens.at[day, ticker]), float(opens.at[day, bench])
    if midday or not math.isfinite(m):
        return float(closes.at[day, ticker]), float(closes.at[day, bench])
    if not math.isfinite(b):
        # SPY had no session that day (a US holiday): its price all day was
        # the last close, which the forward-filled close panel holds.
        b = float(closes.at[day, bench])
    return m, b


def stats(calls: list[dict]) -> dict:
    """Count, hit rate and average / median edge at each horizon."""
    out = {}
    for h in HORIZONS:
        edges = [c[f"edge_{h}"] for c in calls if f"edge_{h}" in c]
        out[f"graded_{h}"] = len(edges)
        out[f"hit_rate_{h}"] = (round(sum(e > 0 for e in edges) / len(edges), 3)
                                if edges else None)
        out[f"avg_edge_{h}"] = (round(sum(edges) / len(edges), 4)
                                if edges else None)
        out[f"median_edge_{h}"] = (round(statistics.median(edges), 4)
                                   if edges else None)
    return out


def report_card(calls: list[dict]) -> dict:
    """One account's card: its numbers, split by buys and sells, and its
    latest graded calls (oldest first)."""
    graded = [c for c in calls if f"edge_{HORIZONS[0]}" in c]
    return {"calls": len(calls),
            "pending": sum(1 for c in calls if c.get("pending")),
            **stats(calls),
            "by_side": {s.lower(): stats([c for c in calls if c["side"] == s])
                        for s in ("BUY", "SELL")},
            "recent": [{k: v for k, v in c.items() if k != "pending"}
                       for c in graded[-RECENT_CALLS:]]}


def summary(accounts, as_of) -> dict:
    """All accounts side by side, best average 5-day edge first, plus every
    graded call of every account pooled. ``accounts`` holds ``(id, name,
    calls)`` per account, ``calls`` as from :func:`grade_fills`."""
    keep = [f"{k}_{h}" for h in HORIZONS
            for k in ("graded", "hit_rate", "avg_edge")]
    rows = []
    for aid, name, calls in accounts:
        numbers = stats(calls)
        rows.append({"id": aid, "name": name, **{k: numbers[k] for k in keep}})
    first = f"avg_edge_{HORIZONS[0]}"
    rows.sort(key=lambda r: (r[first] is None, -(r[first] or 0)))
    return {"as_of": pd.Timestamp(as_of).strftime("%Y-%m-%d"),
            "horizons": list(HORIZONS),
            "benchmark": config.BENCHMARK_TICKER,
            "accounts": rows,
            "pooled": stats([c for _, _, calls in accounts for c in calls])}
