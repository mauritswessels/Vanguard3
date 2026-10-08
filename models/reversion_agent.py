"""Agent 2 - "The Bargain Hunter" (mean reversion / value).

Rules (long-only, evaluated at the daily close):

* Quality filter: close above its long-term SMA (default 200 days), so we
  only buy dips in assets that are healthy over the long run.
* Entry: RSI below the entry level (default 30) **and** close below the
  lower Bollinger Band - a deep, statistically stretched sell-off.
* Exit:  close recovers to the middle band (the 20-day mean), or a time
  stop fires after ``max_holding_days`` trading days.

Entries are ranked by how oversold they are (lowest RSI first).
"""

from __future__ import annotations

import pandas as pd

import config
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal, rule_check


class ReversionAgent(BaseAgent):
    name = "Bargain Hunter"
    style = "Oversold RSI below the lower Bollinger Band, exit at the mean"

    def __init__(self, params: dict | None = None):
        super().__init__({**config.REVERSION_PARAMS, **(params or {})})

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = pd.DataFrame(index=bars.index)
        out["close"] = bars["Close"]
        out["rsi"] = ind.rsi(bars["Close"], p["rsi_period"])
        # quality_sma = 0 disables the long-term trend filter.
        out["sma_quality"] = (ind.sma(bars["Close"], p["quality_sma"])
                              if p["quality_sma"] else 0.0)
        return out.join(ind.bollinger_bands(bars["Close"], p["bb_period"],
                                            p["bb_std"]))

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        p = self.params
        signals = []
        for ticker, frame in self.indicators.items():
            r = self.row(ticker, date)
            if r is None:
                continue
            if portfolio.has_position(ticker):
                entry = portfolio.positions[ticker].entry_date
                held_days = len(frame.loc[entry:date]) - 1
                if r.close >= r.bb_mid:
                    signals.append(Signal(ticker, Action.SELL,
                                          "Reverted to 20-day mean"))
                elif held_days >= p["max_holding_days"]:
                    signals.append(Signal(ticker, Action.SELL,
                                          f"Time stop after {held_days}d"))
            elif (r.rsi < p["rsi_entry"] and r.close < r.bb_lower
                  and r.close > r.sma_quality):
                signals.append(Signal(
                    ticker, Action.BUY, f"Oversold, RSI {r.rsi:.1f}",
                    score=float(p["rsi_entry"] - r.rsi)))
        return signals

    def entry_check(self, ticker, date):
        r = self.row(ticker, date)
        if r is None:
            return None
        p = self.params
        above_band = r.close / r.bb_lower - 1
        parts = [
            (r.rsi < p["rsi_entry"], 1 - (r.rsi - p["rsi_entry"]) / 20,
             f"a sell-off, RSI below {p['rsi_entry']:g} (now {r.rsi:.0f})"),
            (r.close < r.bb_lower, 1 - above_band / 0.06,
             f"a close under the lower band {r.bb_lower:.2f} "
             f"(now {above_band:.1%} above it)"),
        ]
        if p["quality_sma"]:
            parts.append((r.close > r.sma_quality,
                          1 - (1 - r.close / r.sma_quality) / 0.03,
                          f"price back above its {p['quality_sma']}-day "
                          f"average"))
        return rule_check(parts, f"Oversold: RSI {r.rsi:.0f} and below "
                                 f"the lower band")

    def exit_check(self, ticker, date, portfolio):
        r = self.row(ticker, date)
        if r is None:
            return None
        p = self.params
        entry = portfolio.positions[ticker].entry_date
        held = len(self.indicators[ticker].loc[entry:date]) - 1
        if r.close >= r.bb_mid:
            return "Back at its average: selling at the next open"
        if held >= p["max_holding_days"]:
            return f"Time stop after {held} days: selling at the next open"
        return (f"Sells at the 20-day average {r.bb_mid:.2f} "
                f"({r.bb_mid / r.close - 1:.1%} away) or after "
                f"{p['max_holding_days']} days (day {held} now)")
