"""The trade journal: every fill with the decision behind it, and positions
from first buy to last sell ("round trips").

Everything here is read from what the simulation recorded; nothing is
estimated. A round trip's P&L is the sum of the portfolio's own realised
P&L on its sells (average-cost method, all fees and slippage included), so
the journal always adds up to the same numbers as the account.
"""

from __future__ import annotations

import pandas as pd

import config


def asset_group(ticker: str) -> str:
    """Region or asset class (the platform has no sector data)."""
    if ticker.endswith(".SW"):
        return "Swiss stocks"
    if ticker.split(".")[-1] in ("DE", "PA", "AS") and "." in ticker:
        return "European stocks"
    if ticker in ("TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "USO"):
        return "Bonds and commodities"
    if ticker in config._FUNDS:
        return "Stock funds (ETFs)"
    return "US stocks"


def _decisions(activity: list[dict]) -> dict[tuple, dict]:
    """(decision date, ticker, side) -> the signal as recorded that day."""
    out = {}
    for day in activity:
        for s in day.get("signals", []):
            key = (day["date"], s["ticker"], s["action"])
            if key not in out or s.get("ordered"):
                out[key] = {**s, "date": day["date"],
                            "time": day.get("time", "close")}
    return out


def fills(portfolio, activity: list[dict]) -> list[dict]:
    """Every fill, oldest first, with the decision that led to it."""
    decisions = _decisions(activity)
    decided_dates = sorted({d["date"] for d in activity})
    rows = []
    for i, t in enumerate(portfolio.trades):
        date = t.date.strftime("%Y-%m-%d")
        if t.decided is not None:
            decided = t.decided.strftime("%Y-%m-%d")
        else:                                   # fills saved before 'decided'
            earlier = [d for d in decided_dates if d < date
                       and (d, t.ticker, t.side) in decisions]
            decided = earlier[-1] if earlier else None
        rows.append({
            "id": i,
            "date": date,
            "decided": decided,
            # Orders fill at the next open; the midday check fills at once.
            "session": "midday" if decided == date else "open",
            "ticker": t.ticker, "side": t.side, "quantity": t.quantity,
            "price": t.exec_price, "market_price": t.market_price,
            "fx": t.fx_rate, "value_chf": t.gross_chf,
            "fees_chf": t.commission_chf + t.slippage_chf + t.fx_cost_chf,
            "commission_chf": t.commission_chf,
            "cash_flow_chf": t.cash_flow_chf,
            "pnl_chf": t.realized_pnl_chf if t.side == "SELL" else None,
            "reason": t.reason,
            "decision": decisions.get((decided, t.ticker, t.side))
            if decided else None,
        })
    return rows


def round_trips(rows: list[dict], equity: pd.Series, positions: dict,
                prices_chf: pd.Series, initial: float,
                last: pd.Timestamp) -> list[dict]:
    """Group fills into positions: opened by a buy from zero, closed when
    the holding is back to zero. Partial and repeated fills are combined."""
    open_, trips = {}, []
    eq = equity.sort_index()

    def equity_at(day: str | None) -> float:
        if not day:
            return initial
        before = eq.loc[:pd.Timestamp(day)]
        return float(before.iloc[-1]) if len(before) else initial

    for r in rows:
        t = r["ticker"]
        if r["side"] == "BUY":
            trip = open_.get(t)
            if trip is None:
                trip = open_[t] = {
                    "ticker": t, "entry_date": r["date"], "exit_date": None,
                    "fills": [], "qty": 0, "max_qty": 0, "bought_qty": 0,
                    "buy_value": 0.0, "cost_chf": 0.0, "sold_qty": 0,
                    "sell_value": 0.0, "proceeds_chf": 0.0, "pnl_chf": 0.0,
                    "size_pct": -r["cash_flow_chf"] / equity_at(r["decided"]),
                    "entry": r["decision"], "exit": None,
                }
            trip["qty"] += r["quantity"]
            trip["bought_qty"] += r["quantity"]
            trip["max_qty"] = max(trip["max_qty"], trip["qty"])
            trip["buy_value"] += r["quantity"] * r["price"]
            trip["cost_chf"] += -r["cash_flow_chf"]
        else:
            trip = open_.get(t)
            if trip is None:                    # cannot happen: long only
                continue
            trip["qty"] -= r["quantity"]
            trip["sold_qty"] += r["quantity"]
            trip["sell_value"] += r["quantity"] * r["price"]
            trip["proceeds_chf"] += r["cash_flow_chf"]
            trip["pnl_chf"] += r["pnl_chf"] or 0.0
            trip["exit"] = r["decision"]
            if trip["qty"] <= 0:
                trip["exit_date"] = r["date"]
                trips.append(open_.pop(t))
        trip["fills"].append(r["id"])
    trips += list(open_.values())

    out = []
    for i, tr in enumerate(sorted(trips, key=lambda x: x["entry_date"])):
        closed = tr["exit_date"] is not None
        end = pd.Timestamp(tr["exit_date"]) if closed else last
        item = {
            "id": i, "ticker": tr["ticker"],
            "status": "closed" if closed else "open",
            "entry_date": tr["entry_date"], "exit_date": tr["exit_date"],
            "quantity": tr["max_qty"],
            "entry_price": tr["buy_value"] / tr["bought_qty"],
            "exit_price": tr["sell_value"] / tr["sold_qty"]
            if tr["sold_qty"] else None,
            "cost_chf": tr["cost_chf"],
            "size_pct": tr["size_pct"],
            "holding_days": max(0, (end - pd.Timestamp(tr["entry_date"])).days),
            "fills": tr["fills"], "entry": tr["entry"], "exit": tr["exit"],
        }
        if closed:
            item["pnl_chf"] = tr["pnl_chf"]
            item["pnl_pct"] = tr["pnl_chf"] / tr["cost_chf"]
        else:
            pos = positions.get(tr["ticker"])
            value = pos.quantity * float(prices_chf[tr["ticker"]]) if pos else 0.0
            basis = pos.cost_basis_chf if pos else tr["cost_chf"]
            # Realised part (from any partial sells) plus the open part.
            item["pnl_chf"] = tr["pnl_chf"] + value - basis
            item["unrealized_chf"] = value - basis
            item["pnl_pct"] = item["pnl_chf"] / tr["cost_chf"]
            item["value_chf"] = value
        out.append(item)
    return out
