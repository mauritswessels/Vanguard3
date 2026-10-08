"""The daily simulation loop, shared by backtests and live paper trading.

``Simulator.step(date)`` is one trading day for every account:

1. the broker fills yesterday's orders at today's open (with all costs),
2. the portfolio is marked to market at today's close,
3. the agent reads data up to today's close and submits new orders.

A backtest calls ``step`` for every historical date in one go. The daily
paper-trading job restores the simulator from JSON, calls ``step`` only for
the sessions that are new since the last run, and saves it again. Because
both paths run the same code, the paper results are directly comparable
with the backtests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config
from data_manager import MarketData
from engine.broker import SimulatedBroker
from engine.portfolio import Portfolio
from models import agent_key, make_agent
from models.base_agent import BaseAgent

STATE_VERSION = 1


@dataclass
class Account:
    """One competitor: a strategy with its own portfolio and broker."""

    agent: BaseAgent
    portfolio: Portfolio
    broker: SimulatedBroker
    #: Days on which the agent did something: signals, orders and fills.
    activity: list[dict] = field(default_factory=list)


def build_accounts(market: MarketData,
                   agents: list[BaseAgent]) -> list[Account]:
    accounts = []
    for agent in agents:
        pf = Portfolio(agent.name, config.INITIAL_CAPITAL_CHF)
        accounts.append(Account(agent, pf, SimulatedBroker(pf, market)))
    return accounts


class Simulator:
    """Runs any number of accounts over the same market data."""

    def __init__(self, market: MarketData, accounts: list[Account],
                 tuner=None):
        """``tuner(agent, market, as_of)`` is called for every learning agent
        on the first session of each new month, before that day's fills."""
        self.market = market
        self.accounts = accounts
        self.tuner = tuner
        self.last_date: pd.Timestamp | None = None
        for acc in accounts:
            acc.agent.prepare(market)

    def step(self, date: pd.Timestamp) -> None:
        if self.last_date is not None and date <= self.last_date:
            raise ValueError(f"{date.date()} already simulated")
        if (self.tuner is not None and self.last_date is not None
                and date.month != self.last_date.month):
            for acc in self.accounts:
                if acc.agent.learning:
                    self.tuner(acc.agent, self.market, self.last_date)
        prices_chf = self.market.close_chf(date)
        for acc in self.accounts:
            fills = acc.broker.process(date)
            acc.portfolio.mark_to_market(date, prices_chf)
            signals = acc.agent.calculate_signals(date, acc.portfolio)
            orders = acc.agent.execute_trade(signals, date, acc.portfolio,
                                             acc.broker)
            if acc.portfolio.cash < -1e-6:  # defence in depth
                raise AssertionError(f"{acc.agent.name} cash went negative")
            if signals or fills:
                acc.activity.append(_activity(date, signals, orders, fills))
        self.last_date = date

    def add_account(self, agent: BaseAgent, since: pd.Timestamp) -> None:
        """Join a new competitor mid-run with untouched starting cash.

        Its equity curve is back-filled with the starting capital for the
        sessions it missed, so every account shares the same dates.
        """
        agent.prepare(self.market)
        acc = build_accounts(self.market, [agent])[0]
        if self.last_date is not None:
            cal = self.market.calendar
            for d in cal[(cal >= since) & (cal <= self.last_date)]:
                acc.portfolio._equity[d] = acc.portfolio.initial_cash
        self.accounts.append(acc)

    def run(self, dates) -> None:
        for date in dates:
            self.step(date)

    # -- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "last_date": (self.last_date.strftime("%Y-%m-%d")
                          if self.last_date is not None else None),
            "accounts": [{
                "agent": agent_key(acc.agent),
                "name": acc.agent.name,
                "learning": acc.agent.learning,
                "learning_log": acc.agent.learning_log,
                "params": acc.agent.params,
                "agent_state": acc.agent.get_state(),
                "portfolio": acc.portfolio.to_dict(),
                "pending_orders": acc.broker.pending_to_list(),
                "activity": acc.activity,
            } for acc in self.accounts],
        }

    @classmethod
    def from_dict(cls, data: dict, market: MarketData,
                  tuner=None) -> "Simulator":
        if data.get("version") != STATE_VERSION:
            raise ValueError(
                f"Unsupported state version {data.get('version')}")
        accounts = []
        for a in data["accounts"]:
            agent = make_agent(a["agent"], a["params"],
                               learning=a.get("learning", False),
                               name=a.get("name"))
            agent.learning_log = a.get("learning_log", [])
            agent.set_state(a["agent_state"])
            pf = Portfolio.from_dict(a["portfolio"])
            broker = SimulatedBroker(pf, market)
            broker.load_pending(a["pending_orders"])
            accounts.append(Account(agent, pf, broker, a["activity"]))
        sim = cls(market, accounts, tuner)
        if data["last_date"]:
            sim.last_date = pd.Timestamp(data["last_date"])
        return sim


def _activity(date, signals, orders, fills) -> dict:
    ordered = {(o.ticker, o.side) for o in orders}
    return {
        "date": date.strftime("%Y-%m-%d"),
        "signals": [{"ticker": s.ticker, "action": s.action.value,
                     "reason": s.reason,
                     "ordered": (s.ticker, s.action.value) in ordered}
                    for s in signals],
        "orders": [{"ticker": o.ticker, "side": o.side,
                    "quantity": o.quantity} for o in orders],
        "fills": [{"ticker": f.ticker, "side": f.side,
                   "quantity": f.quantity,
                   "price": round(f.exec_price, 4),
                   "pnl_chf": round(f.realized_pnl_chf, 2)} for f in fills],
    }
