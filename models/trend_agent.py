"""Agent 1 - "The Trend Follower" (momentum / trend).

Rules (long-only, evaluated at the daily close):

* Entry: EMA(fast) above EMA(slow) **and** ADX above the threshold **and**
  +DI above -DI, i.e. an established, strong up-trend.
* Exit:  EMA(fast) crosses back below EMA(slow).

Entries are ranked by ADX so the strongest trends get capital first.
"""

from __future__ import annotations

import pandas as pd

import config
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal


class TrendAgent(BaseAgent):
    name = "Trend Follower"
    style = "EMA 20/50 cross filtered by ADX trend strength"

    def __init__(self, params: dict | None = None):
        super().__init__({**config.TREND_PARAMS, **(params or {})})

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = pd.DataFrame(index=bars.index)
        out["close"] = bars["Close"]
        out["ema_fast"] = ind.ema(bars["Close"], p["ema_fast"])
        out["ema_slow"] = ind.ema(bars["Close"], p["ema_slow"])
        return out.join(ind.adx(bars["High"], bars["Low"], bars["Close"],
                                p["adx_period"]))

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        threshold = self.params["adx_threshold"]
        signals = []
        for ticker in self.indicators:
            r = self.row(ticker, date)
            if r is None:
                continue
            if portfolio.has_position(ticker):
                if r.ema_fast < r.ema_slow:
                    signals.append(Signal(ticker, Action.SELL,
                                          "EMA fast crossed below slow"))
            elif (r.ema_fast > r.ema_slow and r.adx > threshold
                  and r.plus_di > r.minus_di):
                signals.append(Signal(
                    ticker, Action.BUY,
                    f"Up-trend, ADX {r.adx:.1f}", score=float(r.adx)))
        return signals
