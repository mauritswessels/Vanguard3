"""The daily simulation loop, shared by backtests and live paper trading.

``Simulator.step(date)`` is one trading day for every account:

1. the broker fills yesterday's orders at today's open (with all costs),
   then the orders the midday check placed for today's close at that close,
2. the portfolio is marked to market at today's close,
3. the agent reads data up to today's close and submits new orders.

Live paper trading also pays dividends (before the open: whoever held the
share at the last close gets it) and applies share splits
(``apply_splits``). Backtests leave both out because their prices are
adjusted for them already.

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
from models.base_agent import Action, BaseAgent

STATE_VERSION = 1

#: Saved states from before 21 Oct 2026 do not say when each account
#: joined. These live accounts joined after the race had begun (found in
#: the history of state/paper_state.json); every other account of such a
#: state joined on its first session (see ``joined_before_records``).
JOINED_BEFORE_RECORDS = {
    ("manager", "Team Manager"): "2026-10-12",
    ("monkey", "Monkey"): "2026-10-12",
    ("news_opus", "News Analyst (Opus)"): "2026-10-14",
    ("learner_opus", "Opus Learner"): "2026-10-15",
}


@dataclass
class Account:
    """One competitor: a strategy with its own portfolio and broker."""

    agent: BaseAgent
    portfolio: Portfolio
    broker: SimulatedBroker
    #: Days on which the agent did something: signals, orders and fills.
    activity: list[dict] = field(default_factory=list)
    #: First session the account could trade (``None`` until then). An
    #: account added later has starting cash on the days before, and the
    #: AI Learners practise without orders until their ``live_from``, so
    #: only the days from here on are its own.
    joined: pd.Timestamp | None = None


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
        #: Pay dividends (live paper trading; see the module docstring).
        self.corporate_actions = False
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
        # The Team Manager goes last, so it sees today's decisions of the
        # agents it copies (sorted() keeps everyone else in order).
        for acc in sorted(self.accounts, key=lambda a: getattr(
                a.agent, "uses_team", False)):
            if getattr(acc.agent, "uses_team", False):
                acc.agent.team = self.accounts   # the Team Manager
            if acc.joined is None and acc.agent.trades_on(date):
                acc.joined = date
            seen = len(acc.broker.rejected)
            if self.corporate_actions:
                self._pay_dividends(acc, date)
            # Dividends paid and splits applied since the last session.
            events = [e for e in acc.portfolio.events
                      if pd.Timestamp(e["date"]) <= date
                      and (self.last_date is None
                           or pd.Timestamp(e["date"]) > self.last_date)]
            fills = acc.broker.process(date)
            # Orders placed at midday for today's close (markets whose
            # midday price was delayed), before the day is marked.
            closing = acc.broker.process_close(date)
            acc.portfolio.mark_to_market(date, prices_chf)
            signals = acc.agent.calculate_signals(date, acc.portfolio)
            orders = acc.agent.execute_trade(signals, date, acc.portfolio,
                                             acc.broker)
            if acc.portfolio.cash < -1e-6:  # defence in depth
                raise AssertionError(f"{acc.agent.name} cash went negative")
            # Orders that did not go through (replacing one is routine).
            failed = [(o, why) for o, why in acc.broker.rejected[seen:]
                      if not why.startswith("replaced")]
            if signals or fills or closing or failed or events:
                entry = _activity(
                    date, signals, orders, fills + closing,
                    decision_context(acc.agent, signals, date, acc.portfolio))
                for f in entry["fills"][len(fills):]:
                    f["at_close"] = True        # ordered at midday
                if events:
                    entry["corporate"] = [dict(e) for e in events]
                if failed:
                    entry["rejected"] = [
                        {"ticker": o.ticker, "side": o.side,
                         "quantity": o.quantity,
                         "created": o.created.strftime("%Y-%m-%d"),
                         **({"at_close": True} if o.kind == "close" else {}),
                         "why": why} for o, why in failed]
                acc.activity.append(entry)
        self.last_date = date

    def _pay_dividends(self, acc: Account, date: pd.Timestamp) -> None:
        """Dividends of the shares ``acc`` held at the last close that went
        ex-dividend since then."""
        if self.last_date is None:
            return
        for t in sorted(acc.portfolio.positions):
            acts = self.market.actions.get(t)
            if acts is None or acts.empty:
                continue
            due = acts.loc[(acts.index > self.last_date)
                           & (acts.index <= date), "dividend"]
            for day, amount in due.items():
                if amount > 0:
                    ccy = self.market.currencies[t]
                    acc.portfolio.receive_dividend(
                        day, t, float(amount), self.market.fx_rate(t, date),
                        config.DIVIDEND_TAX.get(ccy, 0.0))

    def apply_splits(self) -> list[dict]:
        """Restate every account in post-split shares for the splits since
        the last session, before any new session is simulated: Yahoo
        divides all earlier prices by a split's ratio the day it happens,
        so the new sessions' prices are all in post-split shares."""
        if self.last_date is None:
            return []
        cal = self.market.calendar
        done = []
        for t, acts in sorted(self.market.actions.items()):
            due = acts.loc[(acts.index > self.last_date)
                           & (acts.index <= cal[-1]), "split"]
            for day, ratio in due.items():
                if not ratio > 0 or ratio == 1:
                    continue
                first = cal[cal >= day][0]
                price = float(self.market.close_panel.at[first, t]
                              * self.market.fx_rate(t, first))
                for acc in self.accounts:
                    acc.portfolio.split(day, t, float(ratio), price)
                    acc.broker.split(t, float(ratio))
                    acc.agent.on_split(t, float(ratio))
                done.append({"ticker": t, "date": day.strftime("%Y-%m-%d"),
                             "ratio": float(ratio)})
        return done

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
                "joined": (acc.joined.strftime("%Y-%m-%d")
                           if acc.joined is not None else None),
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
            joined = (pd.Timestamp(a["joined"]) if a.get("joined")
                      else None if "joined" in a
                      else joined_before_records(a, agent))
            accounts.append(Account(agent, pf, broker, a["activity"], joined))
        sim = cls(market, accounts, tuner)
        if data["last_date"]:
            sim.last_date = pd.Timestamp(data["last_date"])
        return sim


def joined_before_records(saved: dict, agent: BaseAgent
                          ) -> pd.Timestamp | None:
    """Join date of an account saved before join dates were recorded: its
    first session (the dates of its equity curve), or the later date in
    ``JOINED_BEFORE_RECORDS``, and not before the agent may trade."""
    days = sorted(pd.Timestamp(d) for d in saved["portfolio"]["equity"])
    late = JOINED_BEFORE_RECORDS.get((saved["agent"], saved.get("name")))
    if late and days and days[0] <= pd.Timestamp(late) <= days[-1]:
        days = [d for d in days if d >= pd.Timestamp(late)]
    return next((d for d in days if agent.trades_on(d)), None)


def decision_context(agent, signals, date, portfolio) -> list[dict]:
    """What the agent saw for each signal, recorded on the decision date.

    ``check`` is the agent's own rule with that day's values (the same text
    the dashboard shows as "watching"); ``details`` are agent-specific facts
    such as the News Analyst's headlines. Display only: a failure here never
    stops trading.
    """
    out = []
    for s in signals:
        ctx = {}
        try:
            if s.action is Action.BUY:
                chk = agent.entry_check(s.ticker, date)
                ctx["check"] = chk["note"] if chk else None
            else:
                ctx["check"] = agent.exit_check(s.ticker, date, portfolio)
            ctx["details"] = agent.decision_details(s, date) or {}
        except Exception as exc:              # pragma: no cover - defensive
            ctx["error"] = str(exc)[:120]
        out.append(ctx)
    return out


def _activity(date, signals, orders, fills, context=None) -> dict:
    ordered = {(o.ticker, o.side) for o in orders}
    context = context or [{} for _ in signals]
    return {
        "date": date.strftime("%Y-%m-%d"),
        "signals": [{"ticker": s.ticker, "action": s.action.value,
                     "reason": s.reason,
                     "ordered": (s.ticker, s.action.value) in ordered,
                     "score": round(float(s.score), 4) if s.score else None,
                     "stop": s.stop_price, **ctx}
                    for s, ctx in zip(signals, context)],
        "orders": [{"ticker": o.ticker, "side": o.side,
                    "quantity": o.quantity,
                    **({"at_close": True} if o.kind == "close" else {})}
                   for o in orders],
        "fills": [{"ticker": f.ticker, "side": f.side,
                   "quantity": f.quantity,
                   "price": round(f.exec_price, 4),
                   "pnl_chf": round(f.realized_pnl_chf, 2)} for f in fills],
    }
