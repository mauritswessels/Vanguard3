"""Broker-grade portfolio accounting in CHF.

The ``Portfolio`` is the single source of truth for an agent's account: cash,
open positions, every fill, and the daily equity curve. It applies the same
cost components a real Interactive Brokers account would charge:

* a flat commission per fill (``COMMISSION_PER_TRADE_CHF``),
* slippage, modelled as an adverse move of the execution price,
* an FX conversion spread when the asset is not priced in CHF.

When moving to live trading, real fills from IBKR are recorded through
``record_fill`` with the broker's actual prices and commissions, so the same
accounting and metrics apply unchanged.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import asdict, dataclass

import pandas as pd

import config
from engine import metrics


class InsufficientFundsError(RuntimeError):
    """Raised when a buy would push the cash balance below zero."""


@dataclass(frozen=True)
class CostModel:
    """Transaction cost assumptions used to simulate fills."""

    commission_chf: float = config.COMMISSION_PER_TRADE_CHF
    slippage_bps: float = config.SLIPPAGE_BPS
    fx_bps: float = config.FX_CONVERSION_BPS

    @property
    def slippage(self) -> float:
        return self.slippage_bps / 10_000.0

    def fx_spread(self, currency: str) -> float:
        if currency == config.BASE_CURRENCY:
            return 0.0
        return self.fx_bps / 10_000.0

    def buy_price_chf(self, market_price: float, fx_rate: float,
                      currency: str) -> float:
        """All-in CHF cost of one share, excluding the flat commission."""
        return (market_price * (1 + self.slippage)
                * fx_rate * (1 + self.fx_spread(currency)))

    def sell_price_chf(self, market_price: float, fx_rate: float,
                       currency: str) -> float:
        """Net CHF received for one share, excluding the flat commission."""
        return (market_price * (1 - self.slippage)
                * fx_rate * (1 - self.fx_spread(currency)))


@dataclass
class Position:
    """An open long position."""

    ticker: str
    currency: str
    quantity: int
    cost_basis_chf: float          # total CHF paid, including all costs
    entry_date: pd.Timestamp

    @property
    def avg_cost_chf(self) -> float:
        return self.cost_basis_chf / self.quantity


@dataclass
class TradeRecord:
    """One executed fill, as it would appear on a broker statement."""

    date: pd.Timestamp
    ticker: str
    side: str                      # "BUY" or "SELL"
    quantity: int
    market_price: float            # reference price in trading currency
    exec_price: float              # price after slippage, trading currency
    fx_rate: float                 # CHF per unit of trading currency
    gross_chf: float               # quantity * exec price * fx (after spread)
    commission_chf: float
    slippage_chf: float            # cost attributable to slippage
    fx_cost_chf: float             # cost attributable to the FX spread
    cash_flow_chf: float           # signed change in cash
    realized_pnl_chf: float        # net P&L on sells, 0 on buys
    reason: str = ""


class Portfolio:
    """Cash, positions, trade log and equity curve for one agent."""

    def __init__(self, name: str,
                 initial_cash: float = config.INITIAL_CAPITAL_CHF,
                 cost_model: CostModel | None = None):
        self.name = name
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.costs = cost_model or CostModel()
        self.positions: dict[str, Position] = {}
        self.trades: list[TradeRecord] = []
        self._equity: dict[pd.Timestamp, float] = {}

    # -- queries -------------------------------------------------------------
    def has_position(self, ticker: str) -> bool:
        return ticker in self.positions

    def quantity(self, ticker: str) -> int:
        pos = self.positions.get(ticker)
        return pos.quantity if pos else 0

    def market_value(self, prices_chf: pd.Series) -> float:
        """Value of all open positions at the given CHF prices."""
        return float(sum(p.quantity * prices_chf[t]
                         for t, p in self.positions.items()))

    def equity(self, prices_chf: pd.Series) -> float:
        return self.cash + self.market_value(prices_chf)

    def max_affordable_qty(self, market_price: float, fx_rate: float,
                           currency: str, budget_chf: float | None = None
                           ) -> int:
        """Largest whole-share quantity purchasable with cash (or budget)."""
        budget = self.cash if budget_chf is None else min(budget_chf,
                                                          self.cash)
        unit = self.costs.buy_price_chf(market_price, fx_rate, currency)
        spendable = budget - self.costs.commission_chf
        if spendable <= 0 or unit <= 0:
            return 0
        return int(math.floor(spendable / unit))

    # -- execution -----------------------------------------------------------
    def buy(self, date: pd.Timestamp, ticker: str, currency: str,
            quantity: int, market_price: float, fx_rate: float,
            reason: str = "") -> TradeRecord:
        """Simulate a buy fill, charging slippage, FX spread and commission."""
        _validate(quantity, market_price, fx_rate)
        quantity = int(quantity)
        c = self.costs
        exec_price = market_price * (1 + c.slippage)
        gross = quantity * c.buy_price_chf(market_price, fx_rate, currency)
        slippage_cost = quantity * market_price * c.slippage * fx_rate
        fx_cost = quantity * exec_price * fx_rate * c.fx_spread(currency)
        return self.record_fill(TradeRecord(
            date=date, ticker=ticker, side="BUY", quantity=quantity,
            market_price=market_price, exec_price=exec_price,
            fx_rate=fx_rate, gross_chf=gross,
            commission_chf=c.commission_chf, slippage_chf=slippage_cost,
            fx_cost_chf=fx_cost, cash_flow_chf=-(gross + c.commission_chf),
            realized_pnl_chf=0.0, reason=reason,
        ), currency)

    def sell(self, date: pd.Timestamp, ticker: str, quantity: int,
             market_price: float, fx_rate: float,
             reason: str = "") -> TradeRecord:
        """Simulate a sell fill of an existing long position."""
        _validate(quantity, market_price, fx_rate)
        quantity = int(quantity)
        pos = self.positions.get(ticker)
        if pos is None or quantity > pos.quantity:
            raise ValueError(f"{self.name}: cannot sell {quantity} {ticker}, "
                             f"holding {self.quantity(ticker)} (no shorts)")
        c = self.costs
        exec_price = market_price * (1 - c.slippage)
        gross = quantity * c.sell_price_chf(market_price, fx_rate,
                                            pos.currency)
        slippage_cost = quantity * market_price * c.slippage * fx_rate
        fx_cost = quantity * exec_price * fx_rate * c.fx_spread(pos.currency)
        net = gross - c.commission_chf
        realized = net - pos.avg_cost_chf * quantity
        return self.record_fill(TradeRecord(
            date=date, ticker=ticker, side="SELL", quantity=quantity,
            market_price=market_price, exec_price=exec_price,
            fx_rate=fx_rate, gross_chf=gross,
            commission_chf=c.commission_chf, slippage_chf=slippage_cost,
            fx_cost_chf=fx_cost, cash_flow_chf=net,
            realized_pnl_chf=realized, reason=reason,
        ), pos.currency)

    def record_fill(self, trade: TradeRecord, currency: str) -> TradeRecord:
        """Apply a fill to cash and positions and append it to the log.

        This is the hook a live broker adapter calls with real fills.
        """
        new_cash = self.cash + trade.cash_flow_chf
        if new_cash < -1e-6:
            raise InsufficientFundsError(
                f"{self.name}: {trade.side} {trade.quantity} {trade.ticker} "
                f"needs {-trade.cash_flow_chf:,.2f} CHF, "
                f"cash {self.cash:,.2f}")
        self.cash = new_cash

        if trade.side == "BUY":
            pos = self.positions.get(trade.ticker)
            if pos is None:
                self.positions[trade.ticker] = Position(
                    trade.ticker, currency, trade.quantity,
                    -trade.cash_flow_chf, trade.date)
            else:
                pos.quantity += trade.quantity
                pos.cost_basis_chf += -trade.cash_flow_chf
        else:
            pos = self.positions[trade.ticker]
            remaining = pos.quantity - trade.quantity
            if remaining == 0:
                del self.positions[trade.ticker]
            else:
                pos.cost_basis_chf *= remaining / pos.quantity
                pos.quantity = remaining

        self.trades.append(trade)
        return trade

    # -- valuation & reporting -----------------------------------------------
    def mark_to_market(self, date: pd.Timestamp,
                       prices_chf: pd.Series) -> float:
        """Record end-of-day equity and return it."""
        value = self.equity(prices_chf)
        self._equity[date] = value
        return value

    @property
    def equity_curve(self) -> pd.Series:
        return pd.Series(self._equity, name=self.name, dtype=float)

    def trade_log(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(t) for t in self.trades])

    # -- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-serialisable snapshot of the full account."""
        return {
            "name": self.name,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "costs": asdict(self.costs),
            "positions": [_jsonable(asdict(p))
                          for p in self.positions.values()],
            "trades": [_jsonable(asdict(t)) for t in self.trades],
            "equity": {d.strftime("%Y-%m-%d"): v
                       for d, v in self._equity.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Portfolio":
        """Rebuild an account saved with ``to_dict``."""
        pf = cls(data["name"], data["initial_cash"],
                 CostModel(**data.get("costs", {})))
        pf.cash = float(data["cash"])
        for p in data["positions"]:
            p = dict(p, entry_date=pd.Timestamp(p["entry_date"]))
            pf.positions[p["ticker"]] = Position(**p)
        pf.trades = [TradeRecord(**dict(t, date=pd.Timestamp(t["date"])))
                     for t in data["trades"]]
        pf._equity = {pd.Timestamp(d): float(v)
                      for d, v in data["equity"].items()}
        return pf

    def performance(self) -> dict[str, float]:
        """Risk/return statistics computed from the equity curve and fills."""
        stats = metrics.summarize(self.equity_curve, self.initial_cash)
        sells = [t for t in self.trades if t.side == "SELL"]
        wins = sum(1 for t in sells if t.realized_pnl_chf > 0)
        stats.update({
            "trades": len(self.trades),
            "closed_trades": len(sells),
            "win_rate": wins / len(sells) if sells else float("nan"),
            "realized_pnl_chf": sum(t.realized_pnl_chf for t in sells),
            "commissions_chf": sum(t.commission_chf for t in self.trades),
            "slippage_fx_chf": sum(t.slippage_chf + t.fx_cost_chf
                                   for t in self.trades),
            "open_positions": len(self.positions),
            "cash_chf": self.cash,
        })
        return stats


def _validate(quantity: int, price: float, fx_rate: float) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity,
                                                    numbers.Integral) \
            or quantity <= 0:
        raise ValueError(f"quantity must be a positive int, got {quantity!r}")
    if not (math.isfinite(price) and price > 0):
        raise ValueError(f"invalid price {price!r}")
    if not (math.isfinite(fx_rate) and fx_rate > 0):
        raise ValueError(f"invalid fx rate {fx_rate!r}")


def _jsonable(d: dict) -> dict:
    """Convert timestamps to ISO dates so the dict can be written as JSON."""
    return {k: (v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v)
            for k, v in d.items()}
