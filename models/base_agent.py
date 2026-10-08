"""Abstract base class shared by every trading agent.

Lifecycle, once per trading day after the close:

1. ``prepare(market)``          - compute causal indicators (vectorised).
2. ``calculate_signals(date)``  - pure rule-set -> list of ``Signal``.
3. ``execute_trade(signals)``   - size positions, submit ``Order``s.

In a backtest ``prepare`` runs once over the full history (indicators are
causal, so row *t* never sees the future). In live trading it runs each
evening on the freshly downloaded history; the code path is identical.
Agents are pure Python/NumPy: no LLM or network calls at decision time.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd

import config
from data_manager import MarketData
from engine.broker import BaseBroker, Order
from engine.portfolio import Portfolio


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Signal:
    """A trading intention produced by an agent's rule-set."""

    ticker: str
    action: Action
    reason: str
    score: float = 0.0             # ranks competing buys (higher first)
    stop_price: float | None = None  # in trading currency, if relevant


class BaseAgent(ABC):
    """Common plumbing: indicator cache, sizing and order submission."""

    #: Short display name used on the scoreboard.
    name: str = "Base"
    #: One-line description of the strategy family.
    style: str = ""

    def __init__(self, params: dict):
        self.params = dict(params)
        #: Learning agents re-tune their own parameters every month.
        self.learning = False
        #: One entry per monthly review (see learning.py).
        self.learning_log: list[dict] = []
        self.market: MarketData | None = None
        self.indicators: dict[str, pd.DataFrame] = {}

    # -- step 1 --------------------------------------------------------------
    def prepare(self, market: MarketData) -> None:
        """Compute indicators for every ticker in ``market``."""
        self.market = market
        self.indicators = {t: self.compute_indicators(market.bars[t])
                           for t in market.tickers}
        self._index_rows()

    def _index_rows(self) -> None:
        """Pre-build a date -> row lookup; rows with any NaN map to None."""
        self._rows = {}
        for t, frame in self.indicators.items():
            complete = frame.notna().all(axis=1).to_numpy()
            self._rows[t] = {
                d: (r if ok else None)
                for d, r, ok in zip(frame.index,
                                    frame.itertuples(index=False), complete)}

    @abstractmethod
    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Return ``bars`` joined with this strategy's indicator columns."""

    # -- step 2 --------------------------------------------------------------
    @abstractmethod
    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        """Apply the rule-set to data up to ``date`` and emit signals."""

    # -- step 3 --------------------------------------------------------------
    def execute_trade(self, signals: list[Signal], date: pd.Timestamp,
                      portfolio: Portfolio, broker: BaseBroker
                      ) -> list[Order]:
        """Turn signals into sized orders and submit them to the broker.

        Exits are always full liquidations. Entries are sized by
        ``position_size`` and constrained by a cash budget that includes
        the estimated proceeds of today's exits, so the account can never
        be over-committed. The broker re-checks cash at fill time.
        """
        costs = portfolio.costs
        orders: list[Order] = []
        budget = portfolio.cash * (1.0 - config.CASH_BUFFER_PCT)

        for sig in signals:
            if (sig.action is Action.SELL
                    and portfolio.has_position(sig.ticker)):
                qty = portfolio.quantity(sig.ticker)
                close, fx, ccy = self._quote(sig.ticker, date)
                budget += (qty * costs.sell_price_chf(close, fx, ccy)
                           - costs.commission_chf)
                orders.append(Order(sig.ticker, "SELL", qty, date,
                                    sig.reason))

        prices_chf = self.market.close_chf(date)
        equity = portfolio.equity(prices_chf)
        buys = sorted((s for s in signals if s.action is Action.BUY
                       and not portfolio.has_position(s.ticker)),
                      key=lambda s: s.score, reverse=True)
        for sig in buys:
            close, fx, ccy = self._quote(sig.ticker, date)
            unit = costs.buy_price_chf(close, fx, ccy)
            qty = self.position_size(sig, date, equity, unit)
            qty = min(qty, int(max(budget - costs.commission_chf, 0) // unit))
            if qty <= 0:
                continue
            budget -= qty * unit + costs.commission_chf
            orders.append(Order(sig.ticker, "BUY", qty, date, sig.reason))

        for order in orders:
            broker.submit(order)
        return orders

    def position_size(self, signal: Signal, date: pd.Timestamp,
                      equity: float, unit_cost_chf: float) -> int:
        """Default sizing: a fixed fraction of equity per position."""
        target = equity * self.params["position_pct"]
        return int(math.floor(target / unit_cost_chf))

    # -- explaining (dashboard only, never used to trade) --------------------
    def entry_check(self, ticker: str, date: pd.Timestamp) -> dict | None:
        """How close ``ticker`` is to this agent's buy rule on ``date``.

        Returns ``{"progress": 0..1, "ready": bool, "note": str}`` built from
        the same indicator values ``calculate_signals`` reads, or ``None``
        while the indicators are still warming up.
        """
        return None

    def exit_check(self, ticker: str, date: pd.Timestamp,
                   portfolio: Portfolio) -> str | None:
        """Plain-English sell rule for a held ticker, with today's values."""
        return None

    def watch(self, date: pd.Timestamp, portfolio: Portfolio) -> list[dict]:
        """Every watched ticker with what the agent is waiting for.

        Held tickers come first, then the closest candidates to a buy.
        """
        items = []
        for t in self.indicators:
            if portfolio.has_position(t):
                items.append({"ticker": t, "held": True, "progress": None,
                              "ready": False,
                              "note": self.exit_check(t, date, portfolio)
                              or "Holding"})
                continue
            check = self.entry_check(t, date)
            if check is None:
                check = {"progress": None, "ready": False,
                         "note": "Not enough price history yet"}
            items.append({"ticker": t, "held": False, **check})
        items.sort(key=lambda i: (not i["held"], -(i["progress"] or 0)))
        return items

    def decision_details(self, signal: Signal, date: pd.Timestamp) -> dict:
        """Extra facts the agent itself used for ``signal`` (journal only).

        Called right after ``calculate_signals`` on the decision date, so it
        can only see what the agent saw. Agents without extra facts add none.
        """
        return {}

    # -- helpers -------------------------------------------------------------
    def get_state(self) -> dict:
        """Strategy memory that must survive between daily runs."""
        return {}

    def set_state(self, state: dict) -> None:
        """Restore memory saved by ``get_state``."""

    def row(self, ticker: str, date: pd.Timestamp):
        """Indicator row for ``ticker`` on ``date``.

        Returns ``None`` if the ticker did not trade that day or any
        indicator is still warming up, so rules never act on NaNs.
        """
        rows = self._rows.get(ticker)
        return rows.get(date) if rows is not None else None

    def _quote(self, ticker: str, date: pd.Timestamp):
        close = float(self.market.close_panel.at[date, ticker])
        fx = self.market.fx_rate(ticker, date, "Close")
        return close, fx, self.market.currencies[ticker]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.params})"


def clamp01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def rule_check(parts: list[tuple[bool, float, str]], ready_note: str) -> dict:
    """Combine ``(met, closeness 0..1, what is missing)`` rule parts."""
    ready = all(met for met, _, _ in parts)
    progress = 1.0 if ready else sum(
        1.0 if met else clamp01(c) for met, c, _ in parts) / len(parts)
    missing = [why for met, _, why in parts if not met]
    note = ready_note if ready else "Waiting for " + "; ".join(missing)
    return {"progress": round(progress, 3), "ready": ready, "note": note}
