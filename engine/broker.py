"""Order routing: the seam between agents and the market.

Agents never touch prices or cash directly when trading; they submit
``Order`` objects to a broker. ``SimulatedBroker`` fills them against
historical data. A future ``IBKRBroker`` would implement the same two
methods with ``ib_insync`` (placing market-on-open orders and passing real
fills to ``Portfolio.record_fill``).

Timing model (no look-ahead): agents decide after the close of day *t* using
data up to *t*; orders are filled at the **open of day t+1**.

The midday check (``midday_news.py``) can also place a **market-on-close**
order (``kind="close"``) for a market whose midday price is about 15
minutes old: it fills at that same day's closing price in the evening run
(``process_close``), never at an open or on a later day.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

import pandas as pd

from data_manager import MarketData
from engine.portfolio import Portfolio, TradeRecord

logger = logging.getLogger(__name__)

#: Calendar days an order may wait for its market to open before it expires.
MAX_WAIT_DAYS = 7


@dataclass(frozen=True)
class Order:
    """An order for whole shares (long-only).

    ``kind`` is ``"open"`` (fills at the next session's open, the usual
    case) or ``"close"`` (fills at the closing price of the day it was
    placed, or not at all).
    """

    ticker: str
    side: str                      # "BUY" or "SELL"
    quantity: int
    created: pd.Timestamp
    reason: str = ""
    kind: str = "open"

    def __post_init__(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"invalid side {self.side!r}")
        if self.kind not in ("open", "close"):
            raise ValueError(f"invalid kind {self.kind!r}")
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
        # A new decision on a market replaces an older order still waiting
        # there (its market has had no session since).
        for o in [o for o in self.pending if o.ticker == order.ticker
                  and o.created < order.created]:
            self.pending.remove(o)
            self._reject(o, "replaced by a newer order")
        self.pending.append(order)

    def process(self, date: pd.Timestamp) -> list[TradeRecord]:
        self._tidy(date)
        # Orders submitted today are only eligible from tomorrow's open.
        # An order for a market with no session today (a local holiday)
        # waits for that market's next open instead of expiring. Orders at
        # the close are left for ``process_close``.
        opens = self.market.open_panel.loc[date]
        ready = lambda o: (o.kind == "open" and o.created < date
                           and math.isfinite(opens.get(o.ticker, math.nan)))
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

    def process_close(self, date: pd.Timestamp) -> list[TradeRecord]:
        """Fill the orders placed for the close of ``date`` at that day's
        closing price, after the open fills and before the day is marked.

        A close order only ever fills at the close of the day it was
        placed: if its market has no session that day (a holiday), or that
        day has passed, it lapses with a reason.
        """
        ready = lambda o: o.kind == "close" and o.created <= date
        due = [o for o in self.pending if ready(o)]
        self.pending = [o for o in self.pending if not ready(o)]
        due.sort(key=lambda o: o.side != "SELL")   # proceeds fund the buys
        fills = []
        for order in due:
            if order.created < date:
                self._reject(order, "the day it was ordered for had passed")
                continue
            price = self._session_close(order.ticker, date)
            if not math.isfinite(price):
                self._reject(order, "its market was closed that day")
                continue
            fill = self.fill_at(order, date, price,
                                self.market.fx_rate(order.ticker, date))
            if fill is not None:
                fills.append(fill)
        return fills

    def _session_close(self, ticker: str, date: pd.Timestamp) -> float:
        """Closing price of ``ticker``'s own session on ``date``, or NaN when
        it had none (``close_panel`` carries the last close over holidays)."""
        bars = self.market.bars.get(ticker)
        if bars is None or date not in bars.index:
            return math.nan
        return float(bars.at[date, "Close"])

    def _tidy(self, date: pd.Timestamp) -> None:
        """Drop waiting orders that are out of date: one replaced by a newer
        decision on the same market (``submit`` does this too; saved states
        from before it did may still hold such pairs), or one still unfilled
        after ``MAX_WAIT_DAYS`` (longer than any market holiday)."""
        newest: dict[str, pd.Timestamp] = {}
        for o in self.pending:
            newest[o.ticker] = max(newest.get(o.ticker, o.created), o.created)
        keep = []
        for o in self.pending:
            if o.created < newest[o.ticker]:
                self._reject(o, "replaced by a newer order")
            elif (date - o.created).days > MAX_WAIT_DAYS:
                self._reject(o, "expired")
            else:
                keep.append(o)
        self.pending = keep

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
            return pf.sell(date, order.ticker, qty, price, fx, order.reason,
                           decided=order.created)

        currency = self.market.currencies[order.ticker]
        affordable = pf.max_affordable_qty(price, fx, currency)
        qty = min(order.quantity, affordable)
        if qty <= 0:
            return self._reject(order, "insufficient cash")
        return pf.buy(date, order.ticker, currency, qty, price, fx,
                      order.reason, decided=order.created)

    def split(self, ticker: str, ratio: float) -> None:
        """Restate waiting orders on ``ticker`` in post-split shares."""
        self.pending = [
            replace(o, quantity=max(1, int(round(o.quantity * ratio))))
            if o.ticker == ticker else o
            for o in self.pending]

    # -- persistence ---------------------------------------------------------
    def pending_to_list(self) -> list[dict]:
        return [{"ticker": o.ticker, "side": o.side, "quantity": o.quantity,
                 "created": o.created.strftime("%Y-%m-%d"),
                 "reason": o.reason, "kind": o.kind} for o in self.pending]

    def load_pending(self, orders: list[dict]) -> None:
        # States saved before orders had a kind hold open orders only.
        self.pending = [Order(o["ticker"], o["side"], int(o["quantity"]),
                              pd.Timestamp(o["created"]), o.get("reason", ""),
                              o.get("kind", "open"))
                        for o in orders]

    def _reject(self, order: Order, why: str):
        # Replacing an order is routine; anything else means an order the
        # agent wanted did not go through.
        log = logger.debug if why.startswith("replaced") else logger.warning
        log("%s: %s %s %s not filled: %s", self.portfolio.name, order.side,
            order.quantity, order.ticker, why)
        self.rejected.append((order, why))
        return None
