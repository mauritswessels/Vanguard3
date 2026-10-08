"""Order routing: the seam between agents and the market.

Agents never touch prices or cash directly when trading; they submit
``Order`` objects to a broker. ``SimulatedBroker`` fills them against
historical data. A future ``IBKRBroker`` would implement the same two
methods with ``ib_insync`` (placing market-on-open orders and passing real
fills to ``Portfolio.record_fill``).

Timing model (no look-ahead): agents decide after the close of day *t* using
data up to *t*; orders are filled at the **open of day t+1**.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from data_manager import MarketData
from engine.portfolio import Portfolio, TradeRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Order:
    """A market-on-open order for whole shares (long-only)."""

    ticker: str
    side: str                      # "BUY" or "SELL"
    quantity: int
    created: pd.Timestamp
    reason: str = ""

    def __post_init__(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"invalid side {self.side!r}")
        if int(self.quantity) != self.quantity or self.quantity <= 0:
            raise ValueError(f"invalid quantity {self.quantity!r}")


class BaseBroker(ABC):
    """Interface shared by simulated and live brokers."""

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    @abstractmethod
    def submit(self, order: Order) -> None:
        """Queue an order for execution at the next session open."""

    @abstractmethod
    def process(self, date: pd.Timestamp) -> list[TradeRecord]:
        """Execute queued orders for the session on ``date``."""


class SimulatedBroker(BaseBroker):
    """Fills queued orders at the next available open with full costs."""

    def __init__(self, portfolio: Portfolio, market: MarketData):
        super().__init__(portfolio)
        self.market = market
        self.pending: list[Order] = []
        self.rejected: list[tuple[Order, str]] = []

    def submit(self, order: Order) -> None:
        self.pending.append(order)

    def process(self, date: pd.Timestamp) -> list[TradeRecord]:
        # Orders submitted today are only eligible from tomorrow's open.
        # An order for a market with no session today (a local holiday)
        # waits for that market's next open instead of expiring.
        opens = self.market.open_panel.loc[date]
        ready = lambda o: o.created < date and math.isfinite(opens.get(o.ticker, math.nan))
        eligible = [o for o in self.pending if ready(o)]
        self.pending = [o for o in self.pending if not ready(o)]
        # Sells first so their proceeds can fund same-session buys.
        eligible.sort(key=lambda o: o.side != "SELL")

        fills = []
        for order in eligible:
            fill = self._execute(order, date)
            if fill is not None:
                fills.append(fill)
        return fills

    def _execute(self, order: Order, date: pd.Timestamp):
        price = self.market.open_panel.at[date, order.ticker]
        if not math.isfinite(price):
            # Market closed for this ticker: DAY order expires unfilled.
            return self._reject(order, "no session")
        fx = self.market.fx_rate(order.ticker, date, "Open")
        return self.fill_at(order, date, price, fx)

    def fill_at(self, order: Order, date: pd.Timestamp, price: float,
                fx: float):
        """Fill ``order`` at a given price (the midday check uses this with
        a live quote); same costs and cash checks as an open fill."""
        pf = self.portfolio

        if order.side == "SELL":
            qty = min(order.quantity, pf.quantity(order.ticker))
            if qty <= 0:
                return self._reject(order, "no position")
            return pf.sell(date, order.ticker, qty, price, fx, order.reason)

        currency = self.market.currencies[order.ticker]
        affordable = pf.max_affordable_qty(price, fx, currency)
        qty = min(order.quantity, affordable)
        if qty <= 0:
            return self._reject(order, "insufficient cash")
        return pf.buy(date, order.ticker, currency, qty, price, fx,
                      order.reason)

    # -- persistence ---------------------------------------------------------
    def pending_to_list(self) -> list[dict]:
        return [{"ticker": o.ticker, "side": o.side, "quantity": o.quantity,
                 "created": o.created.strftime("%Y-%m-%d"),
                 "reason": o.reason} for o in self.pending]

    def load_pending(self, orders: list[dict]) -> None:
        self.pending = [Order(o["ticker"], o["side"], int(o["quantity"]),
                              pd.Timestamp(o["created"]), o.get("reason", ""))
                        for o in orders]

    def _reject(self, order: Order, why: str):
        logger.debug("%s rejected %s %s: %s", self.portfolio.name,
                     order.side, order.ticker, why)
        self.rejected.append((order, why))
        return None
