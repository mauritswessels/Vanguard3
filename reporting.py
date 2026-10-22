"""Scoreboard and dashboard exports shared by every entry point.

``dashboard_payload`` turns a finished (or in-progress) ``Simulator`` into
the JSON the static dashboard in ``docs/`` reads. Keeping the export in one
place means backtests, walk-forward studies and the daily paper-trading job
all produce the same shape of data.

Accounts join the live race on different days, so a return since each
account's own start is not a fair ranking: one that joined after a fall
skipped it. ``same_days`` therefore measures every account against each
yardstick over exactly the sessions both have been trading.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from engine.portfolio import Portfolio
from engine import grading, journal
from engine.simulator import Simulator
from models import agent_key


def scoreboard(portfolios: list[Portfolio]) -> pd.DataFrame:
    """Rank portfolios by final equity with key risk metrics."""
    rows = []
    for pf in portfolios:
        s = pf.performance()
        rows.append({
            "Agent": pf.name,
            "Final CHF": s["final_equity_chf"],
            "Return %": 100 * s["total_return"],
            "Sharpe": s["sharpe"],
            "Sortino": s["sortino"],
            "Max DD %": 100 * s["max_drawdown"],
            "Vol %": 100 * s["volatility"],
            "Trades": s["trades"],
            "Win %": 100 * s["win_rate"],
            "Costs CHF": s["commissions_chf"] + s["slippage_fx_chf"],
            "Open pos": s["open_positions"],
        })
    board = pd.DataFrame(rows).sort_values("Final CHF", ascending=False)
    board.insert(0, "Rank", range(1, len(board) + 1))
    return board.set_index("Rank")


def print_scoreboard(sim: Simulator, heading: str) -> None:
    curve = sim.accounts[0].portfolio.equity_curve.index
    board = scoreboard([a.portfolio for a in sim.accounts])
    print()
    print("=" * 100)
    print(f" {heading}  |  {curve[0].date()} -> {curve[-1].date()}"
          f"  |  {len(curve)} sessions  |  data: {sim.market.source}"
          f"  |  start {config.INITIAL_CAPITAL_CHF:,.0f} CHF each")
    print("=" * 100)
    with pd.option_context("display.width", 140,
                           "display.float_format", "{:,.2f}".format):
        print(board.to_string())
    print("-" * 100)
    for acc in sim.accounts:
        print(f" {acc.agent.name:<22} {acc.agent.style}")
    print(f" Costs: {config.COMMISSION_PER_TRADE_CHF:.2f} CHF/fill, "
          f"{config.SLIPPAGE_BPS:g} bp slippage, "
          f"{config.FX_CONVERSION_BPS:g} bp FX spread. Fills at next open.")
    if sim.market.source == "synthetic":
        print(" NOTE: synthetic data - results validate the engine, "
              "not the strategies.")


#: Yardsticks every account is compared with over the same days, by
#: dashboard id: buy-and-hold SPY and an equal share of every market.
YARDSTICKS = ("benchmark", "equal_weight")


def same_days(acc, ref, last: pd.Timestamp) -> dict | None:
    """``acc`` against the yardstick account ``ref`` over the sessions both
    have been trading: from the close of the later join date to ``last``.

    Both returns are counted from that close, so neither side gets credit
    for days the other was not in the race. ``None`` for the yardstick
    itself, or while either has not joined.
    """
    if ref is None or ref is acc or acc.joined is None or ref.joined is None:
        return None
    since = max(acc.joined, ref.joined)
    mine = acc.portfolio.equity_curve.loc[since:last]
    theirs = ref.portfolio.equity_curve.loc[since:last]
    days = mine.index.intersection(theirs.index)
    if len(days) == 0:
        return None
    a = float(mine[days[-1]] / mine[days[0]] - 1)
    b = float(theirs[days[-1]] / theirs[days[0]] - 1)
    return {"name": ref.agent.name, "from": _day(days[0]),
            "to": _day(days[-1]), "days": len(days) - 1,
            "return": a, "yardstick_return": b, "difference": a - b}


def _day(d: pd.Timestamp | None) -> str | None:
    return d.strftime("%Y-%m-%d") if d is not None else None


def dashboard_payload(sim: Simulator, mode: str, start: pd.Timestamp,
                      extra: dict | None = None) -> dict:
    """Everything the dashboard needs to draw one view (backtest or paper)."""
    market, last = sim.market, sim.last_date
    prices_chf = market.close_chf(last)
    refs = {}
    for acc in sim.accounts:
        refs.setdefault(agent_key(acc.agent), acc)
    refs = {y: refs.get(y) for y in YARDSTICKS}
    agents, graded = [], []
    for acc in sim.accounts:
        pf = acc.portfolio
        positions = []
        for t, pos in sorted(pf.positions.items()):
            value = pos.quantity * float(prices_chf[t])
            positions.append({
                "ticker": t,
                "quantity": pos.quantity,
                "entry_date": pos.entry_date.strftime("%Y-%m-%d"),
                "avg_cost_chf": pos.avg_cost_chf,
                "price_chf": float(prices_chf[t]),
                "value_chf": value,
                "pnl_chf": value - pos.cost_basis_chf,
                "pnl_pct": value / pos.cost_basis_chf - 1,
                "stop": acc.agent.get_state().get("stops", {}).get(t),
            })
        key = agent_key(acc.agent)
        twin = "(fixed)" in acc.agent.name
        aid = key + ("-fixed" if twin else "")
        rows = journal.fills(pf, acc.activity)
        trips = journal.round_trips(
            rows, pf.equity_curve, pf.positions, prices_chf, pf.initial_cash,
            last, [e for e in pf.events if e["kind"] == "split"]
        ) if mode == "paper" else []
        calls = grading.grade_fills(rows, market, last)
        graded.append((aid, acc.agent.name, calls))
        agents.append({
            "id": aid,
            "key": key,
            "learning": acc.agent.learning,
            "fixed_twin": twin,
            "learning_log": acc.agent.learning_log[-24:],
            "name": acc.agent.name,
            "style": acc.agent.style,
            "benchmark": acc.agent.benchmark,
            "params": acc.agent.params,
            # First session it could trade; the days before are not its own.
            "joined": _day(acc.joined),
            # Against each yardstick over the days both were trading.
            "same_days": {y: same_days(acc, ref, last)
                          for y, ref in refs.items()},
            "stats": pf.performance(),
            "equity": [[d.strftime("%Y-%m-%d"), round(v, 2)]
                       for d, v in pf.equity_curve.items()],
            "cash_chf": pf.cash,
            "positions": positions,
            # Every fill with the decision behind it (journal.py); the
            # 5-year replay keeps the latest 300 to stay small.
            "trades": _slim_trades(rows, last) if mode == "paper"
            else rows[-300:],
            # Positions from first buy to last sell (paper only).
            "trips": [_by_reference(t, rows) for t in trips],
            # Dividends received and share splits.
            "events": pf.events,
            # Every fill graded against SPY 5 and 20 trading days later
            # (engine/grading.py).
            "report_card": grading.report_card(calls),
            "activity": [_slim_day(day) for day in acc.activity[-ACTIVITY_DAYS:]],
            "pending_orders": acc.broker.pending_to_list(),
            # What each rule is waiting for at the last close.
            "watch": acc.agent.watch(last, pf),
            # Daily learner only: what it has learned so far.
            "ai": acc.agent.summary() if hasattr(acc.agent, "summary")
            else None,
            # Team Manager only: whom it backs and why.
            "team": acc.agent.team_view() if hasattr(acc.agent, "team_view")
            else None,
            # Daily closeness to a buy, per ticker (only the near misses).
            "scans": _scans(acc.agent, market.calendar, start, last)
            if mode == "paper" else [],
        })

    window = market.close_panel.loc[start:last]
    prices = {t: [[d.strftime("%Y-%m-%d"), float(f"{v:.6g}")]
                  for d, v in window[t].dropna().items()]
              for t in market.tickers}
    fx = {c: [[d.strftime("%Y-%m-%d"), float(f"{v:.6g}")]
              for d, v in market.fx_close.loc[start:last, c].items()]
          for c in market.fx_close.columns if c != config.BASE_CURRENCY}
    payload = {
        "mode": mode,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "data_source": market.source,
        "start": start.strftime("%Y-%m-%d"),
        "last": last.strftime("%Y-%m-%d"),
        "base_currency": config.BASE_CURRENCY,
        "initial_capital_chf": config.INITIAL_CAPITAL_CHF,
        "costs": {"commission_chf": config.COMMISSION_PER_TRADE_CHF,
                  "slippage_bps": config.SLIPPAGE_BPS,
                  "fx_bps": config.FX_CONVERSION_BPS},
        "currencies": market.currencies,
        # The yardsticks of ``same_days``, with the day each joined.
        "yardsticks": {y: {"name": ref.agent.name, "joined": _day(ref.joined)}
                       if ref is not None else None
                       for y, ref in refs.items()},
        "groups": {t: journal.asset_group(t) for t in market.tickers},
        "agents": agents,
        # All accounts' report cards side by side.
        "report_cards": grading.summary(graded, last),
        "prices": prices,
        "fx": fx,
    }
    if extra:
        payload.update(extra)
    return payload


# The dashboard file grows with every run; these keep it small. The full
# history stays in the saved state (state/paper_state.json).

#: Latest days of each agent's activity in the dashboard file (the agent
#: desk shows 40).
ACTIVITY_DAYS = 60
#: Trades older than this many days keep their decision without the
#: details (headlines, model scores); the reason and rule check stay.
DETAIL_DAYS = 90


def _slim_day(day: dict) -> dict:
    """An activity day with only what the dashboard's feed shows of each
    signal (the full decision is in the trades)."""
    keep = ("ticker", "action", "reason", "ordered", "note")
    return {**day, "signals": [{k: s[k] for k in keep if k in s}
                               for s in day.get("signals", [])]}


def _slim_trades(rows: list[dict], last: pd.Timestamp) -> list[dict]:
    old = (last - pd.Timedelta(days=DETAIL_DAYS)).strftime("%Y-%m-%d")
    return [{**r, "decision": {k: v for k, v in r["decision"].items()
                               if k != "details"}}
            if r["decision"] and r["date"] < old else r for r in rows]


def _by_reference(trip: dict, rows: list[dict]) -> dict:
    """A round trip naming the fills whose decisions opened and closed it
    instead of repeating them (the dashboard looks them up)."""
    sells = [i for i in trip["fills"] if rows[i]["side"] == "SELL"]
    out = {k: v for k, v in trip.items() if k not in ("entry", "exit")}
    out["entry_fill"] = trip["fills"][0]
    out["exit_fill"] = sells[-1] if sells else None
    return out


def _scans(agent, calendar, start, last, floor: float = 0.75,
           top: int = 12) -> list:
    """``[[date, {ticker: progress}]]``: each day's ``top`` tickers closest
    to the agent's buy rule, if at least ``floor`` of the way there. Uses
    the agent's current settings."""
    out = []
    for d in calendar[(calendar >= start) & (calendar <= last)]:
        day = {}
        for t in agent.indicators:
            check = agent.entry_check(t, d)
            if check and check["progress"] >= floor:
                day[t] = round(check["progress"], 2)
        best = sorted(day.items(), key=lambda kv: -kv[1])[:top]
        out.append([d.strftime("%Y-%m-%d"), dict(best)])
    return out


def write_json(payload: dict, path: Path) -> None:
    """Write strict JSON (NaN/inf become null) atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(payload), separators=(",", ":"),
                              allow_nan=False))
    tmp.replace(path)


def _clean(obj):
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else round(obj, 6)
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar
        return _clean(obj.item())
    return obj
