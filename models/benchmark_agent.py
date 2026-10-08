"""Passive benchmark: buy one ETF on the first day and hold it forever.

Running the benchmark as an ordinary agent means it pays the same costs,
fills at the same opens and is scored with the same code as the real
competitors, so the comparison is fair.
"""

from __future__ import annotations

import math

import pandas as pd

import config
from engine.portfolio import Portfolio
from models.base_agent import Action, BaseAgent, Signal


class BuyHoldAgent(BaseAgent):
    style = "Passive benchmark: buy once, never sell"

    def __init__(self, ticker: str = config.BENCHMARK_TICKER):
        super().__init__({"ticker": ticker,
                          "position_pct": 1.0 - config.CASH_BUFFER_PCT})
        self.name = f"Buy & Hold {ticker}"
        self.ticker = ticker

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close": bars["Close"]})

    def prepare(self, market) -> None:
        self.market = market
        self.indicators = {self.ticker: self.compute_indicators(
            market.bars[self.ticker])}
        self._index_rows()

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        if portfolio.positions or self.row(self.ticker, date) is None:
            return []
        return [Signal(self.ticker, Action.BUY, "Initial benchmark buy")]

    def position_size(self, signal, date, equity, unit_cost_chf) -> int:
        spend = (equity * self.params["position_pct"]
                 - config.COMMISSION_PER_TRADE_CHF)
        return max(int(math.floor(spend / unit_cost_chf)), 0)

    def watch(self, date, portfolio):
        held = portfolio.has_position(self.ticker)
        return [{"ticker": self.ticker, "held": held, "progress": None,
                 "ready": not held,
                 "note": "Holds it for good and never sells" if held
                 else "Buys it once at the next open"}]
