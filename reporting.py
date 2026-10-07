"""Scoreboard and dashboard exports shared by every entry point.

``dashboard_payload`` turns a finished (or in-progress) ``Simulator`` into
the JSON the static dashboard in ``docs/`` reads. Keeping the export in one
place means backtests, walk-forward studies and the daily paper-trading job
all produce the same shape of data.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from engine.portfolio import Portfolio
from engine.simulator import Simulator
from models import BuyHoldAgent, agent_key


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


def dashboard_payload(sim: Simulator, mode: str, start: pd.Timestamp,
                      extra: dict | None = None) -> dict:
    """Everything the dashboard needs to draw one view (backtest or paper)."""
    market, last = sim.market, sim.last_date
    prices_chf = market.close_chf(last)
    agents = []
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
        agents.append({
            "key": agent_key(acc.agent),
            "name": acc.agent.name,
            "style": acc.agent.style,
            "benchmark": isinstance(acc.agent, BuyHoldAgent),
            "params": acc.agent.params,
            "stats": pf.performance(),
            "equity": [[d.strftime("%Y-%m-%d"), round(v, 2)]
                       for d, v in pf.equity_curve.items()],
            "cash_chf": pf.cash,
            "positions": positions,
            "trades": [{
                "date": t.date.strftime("%Y-%m-%d"), "ticker": t.ticker,
                "side": t.side, "quantity": t.quantity,
                "price": t.exec_price, "fx": t.fx_rate,
                "value_chf": t.gross_chf,
                "pnl_chf": t.realized_pnl_chf if t.side == "SELL" else None,
                "reason": t.reason,
            } for t in pf.trades[-300:]],
            "activity": acc.activity[-120:],
            "pending_orders": acc.broker.pending_to_list(),
        })

    window = market.close_panel.loc[start:last]
    prices = {t: [[d.strftime("%Y-%m-%d"), float(f"{v:.6g}")]
                  for d, v in window[t].dropna().items()]
              for t in market.tickers}
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
        "agents": agents,
        "prices": prices,
    }
    if extra:
        payload.update(extra)
    return payload


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
