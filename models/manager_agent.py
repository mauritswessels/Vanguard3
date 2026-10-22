"""Agent 6 - "The Team Manager" (picks agents, not markets).

It never studies a chart itself. It owns a share of what the other agents
own, and each month it decides whom to back:

* Until the team has ``min_history`` sessions of results, it backs every
  racing agent equally (learning agents, AI Learner, News Analyst; fixed
  twins and yardsticks are left out).
* After that, on the first session of each month, it backs the ``top_n``
  agents with the best return over the last ``lookback`` sessions, in
  equal shares. Each agent counts only from the day it joined the race;
  one with fewer than ``min_history`` days of its own is too new to judge
  and waits for a later month.

Every evening, after the other agents have decided, it works out the mix
of holdings that gives (the agents' holdings once their new orders fill x
its shares) and trades towards it, but only where a market is more than
``band`` of the account away from its target, to keep fees down. Its orders
fill at the same open as theirs, so it follows them without a day's delay.
"""

from __future__ import annotations

import math

import pandas as pd

import config
from engine.broker import Order
from engine.portfolio import Portfolio
from models.base_agent import Action, BaseAgent, Signal


def holdings_after_orders(acc) -> dict[str, int]:
    """Shares ``acc`` will hold once its waiting orders fill."""
    qty = {t: pos.quantity for t, pos in acc.portfolio.positions.items()}
    for o in acc.broker.pending:
        change = o.quantity if o.side == "BUY" else -o.quantity
        qty[o.ticker] = max(qty.get(o.ticker, 0) + change, 0)
    return {t: q for t, q in qty.items() if q > 0}


def own_days(acc, date: pd.Timestamp) -> pd.Series:
    """``acc``'s account value up to ``date``, from the day it joined (none
    before it could trade)."""
    curve = acc.portfolio.equity_curve.loc[:date]
    if acc.joined is None:
        return curve.iloc[:0]
    return curve.loc[acc.joined:]


class ManagerAgent(BaseAgent):
    name = "Team Manager"
    style = "Backs the agents with the best recent results"
    #: The simulator hands it the list of accounts each session.
    uses_team = True

    def __init__(self, params: dict | None = None):
        super().__init__({**config.MANAGER_PARAMS, **(params or {})})
        self.team: list = []
        self.backing: dict[str, float] = {}   # agent name -> share
        self.chosen: str | None = None        # date of the latest choice
        self.why = "Not started yet"
        self._targets: dict[str, float] = {}

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close": bars["Close"]})

    def _racers(self) -> list:
        return [a for a in self.team if a.agent is not self
                and not a.agent.benchmark
                and "(fixed)" not in a.agent.name
                and not getattr(a.agent, "uses_team", False)]

    def choose(self, date: pd.Timestamp) -> None:
        """Pick whom to back, from results up to ``date`` only."""
        racers = self._racers()
        if not racers:
            return
        p = self.params
        # Each agent is judged on its own days only: an account that joined
        # late has its starting cash filled in for the days before, which
        # are not its results.
        curves = {a.agent.name: own_days(a, date) for a in racers}
        ready = {k: c for k, c in curves.items()
                 if len(c) >= p["min_history"]}
        if not ready:
            days = max(len(c) for c in curves.values())
            self.backing = {n: 1 / len(racers) for n in curves}
            self.why = (f"Backs all {len(racers)} agents equally until there "
                        f"are {p['min_history']} days of results "
                        f"({days} so far)")
        else:
            # The same days for everyone it compares.
            n = min(p["lookback"], min(len(c) for c in ready.values()) - 1)
            score = {k: float(c.iloc[-1] / c.iloc[-1 - n] - 1)
                     for k, c in ready.items()}
            best = sorted(score, key=lambda k: -score[k])[:p["top_n"]]
            self.backing = {k: 1 / len(best) for k in best}
            new = sorted(set(curves) - set(ready))
            self.why = (f"Backs the {len(best)} best agents of the last {n} "
                        "days: " + ", ".join(f"{k} {score[k]:+.1%}"
                                             for k in best)
                        + (f" (too new to judge yet: {', '.join(new)})"
                           if new else ""))
        self.chosen = date.strftime("%Y-%m-%d")

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        new_month = (self.chosen is None
                     or pd.Timestamp(self.chosen).month != date.month)
        # While it backs everyone equally, an agent that joins the race is
        # backed from its first day, not from the next month.
        everyone = {a.agent.name for a in self._racers()}
        joined = (self.why.startswith("Backs all")
                  and set(self.backing) != everyone)
        if new_month or not self.backing or joined:
            self.choose(date)
        prices = self.market.close_chf(date)
        by_name = {a.agent.name: a for a in self.team}
        targets: dict[str, float] = {}
        for name, share in self.backing.items():
            acc = by_name.get(name)
            if acc is None:
                continue
            eq = acc.portfolio.equity(prices)
            for t, qty in holdings_after_orders(acc).items():
                w = qty * float(prices[t]) / eq
                targets[t] = targets.get(t, 0.0) + share * w
        cap = 1 - config.CASH_BUFFER_PCT
        total = sum(targets.values())
        if total > cap:
            targets = {t: w * cap / total for t, w in targets.items()}
        self._targets = targets

        equity = portfolio.equity(prices)
        signals = []
        for t in sorted(set(targets) | set(portfolio.positions)):
            if not math.isfinite(float(prices.get(t, math.nan))):
                continue
            now = (portfolio.quantity(t) * float(prices[t]) / equity
                   if portfolio.has_position(t) else 0.0)
            gap = targets.get(t, 0.0) - now
            if abs(gap) <= self.params["band"] and targets.get(t, 0.0) > 0:
                continue
            if gap > self.params["band"]:
                signals.append(Signal(t, Action.BUY,
                                      f"Team target {targets[t]:.1%} "
                                      f"(holds {now:.1%})", score=gap))
            elif gap < 0 and (targets.get(t, 0.0) == 0
                              or -gap > self.params["band"]):
                signals.append(Signal(t, Action.SELL,
                                      f"Team target {targets.get(t, 0):.1%} "
                                      f"(holds {now:.1%})", score=gap))
        return signals

    def execute_trade(self, signals, date, portfolio, broker):
        """Trade each signal towards its target weight (partial trades)."""
        costs = portfolio.costs
        prices = self.market.close_chf(date)
        equity = portfolio.equity(prices)
        waiting = self.waiting_buys(broker, date, costs)
        budget = (portfolio.cash * (1 - config.CASH_BUFFER_PCT)
                  - sum(waiting.values()))
        orders = []
        for sig in (s for s in signals if s.action is Action.SELL):
            close, fx, ccy = self._quote(sig.ticker, date)
            held = portfolio.quantity(sig.ticker)
            keep = int(self._targets.get(sig.ticker, 0.0) * equity
                       // costs.sell_price_chf(close, fx, ccy))
            qty = held - min(keep, held)
            if qty > 0:
                budget += (qty * costs.sell_price_chf(close, fx, ccy)
                           - costs.commission_chf)
                orders.append(Order(sig.ticker, "SELL", qty, date,
                                    sig.reason))
        buys = sorted((s for s in signals if s.action is Action.BUY),
                      key=lambda s: -s.score)
        for sig in buys:
            close, fx, ccy = self._quote(sig.ticker, date)
            unit = costs.buy_price_chf(close, fx, ccy)
            budget += waiting.pop(sig.ticker, 0.0)   # replaced by this one
            qty = int(sig.score * equity // unit)
            qty = min(qty, int(max(budget - costs.commission_chf, 0) // unit))
            if qty <= 0 or qty * unit < config.MIN_ORDER_CHF:
                continue
            budget -= qty * unit + costs.commission_chf
            orders.append(Order(sig.ticker, "BUY", qty, date, sig.reason))
        for order in orders:
            broker.submit(order)
        return orders

    def watch(self, date, portfolio):
        prices = self.market.close_chf(date)
        equity = portfolio.equity(prices)
        items = []
        for t, w in sorted(self._targets.items(), key=lambda kv: -kv[1]):
            held = portfolio.has_position(t)
            now = (portfolio.quantity(t) * float(prices[t]) / equity
                   if held else 0.0)
            items.append({"ticker": t, "held": held, "progress": None,
                          "ready": False,
                          "note": f"Team target {w:.1%}, holds {now:.1%}"})
        return items

    def team_view(self) -> dict:
        return {"backing": self.backing, "chosen": self.chosen,
                "why": self.why}

    def get_state(self) -> dict:
        return {"backing": self.backing, "chosen": self.chosen,
                "why": self.why}

    def set_state(self, state: dict) -> None:
        self.backing = state.get("backing", {})
        self.chosen = state.get("chosen")
        self.why = state.get("why", self.why)
