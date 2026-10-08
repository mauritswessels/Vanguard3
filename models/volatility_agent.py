"""Agent 3 - "The Volatility Protected" (breakout, risk managed).

Rules (long-only, evaluated at the daily close):

* Entry: close breaks above the Donchian upper band (highest high of the
  previous ``donchian_entry`` days).
* Risk:  initial stop at ``close - atr_stop_mult * ATR``. The stop trails
  upward each day by the same rule and never moves down, so it widens in
  volatile markets and tightens in calm ones.
* Exit:  close at or below the trailing stop, or below the Donchian lower
  band of the previous ``donchian_exit`` days.
* Size:  volatility-based - the share count is chosen so that hitting the
  initial stop loses ``risk_per_trade_pct`` of equity, capped at
  ``max_position_pct`` of equity per position.
"""

from __future__ import annotations

import math

import pandas as pd

import config
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal, rule_check


class VolatilityAgent(BaseAgent):
    name = "Volatility Protected"
    style = "Donchian breakout with ATR trailing stops and risk sizing"

    def __init__(self, params: dict | None = None):
        super().__init__({**config.VOLATILITY_PARAMS, **(params or {})})
        # Trailing stop per held ticker, in trading currency.
        self.stops: dict[str, float] = {}

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = pd.DataFrame(index=bars.index)
        out["close"] = bars["Close"]
        out["atr"] = ind.atr(bars["High"], bars["Low"], bars["Close"],
                             p["atr_period"])
        entry = ind.donchian(bars["High"], bars["Low"], p["donchian_entry"])
        exit_ = ind.donchian(bars["High"], bars["Low"], p["donchian_exit"])
        out["entry_upper"] = entry["dc_upper"]
        out["exit_lower"] = exit_["dc_lower"]
        return out

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        mult = self.params["atr_stop_mult"]
        signals = []
        for ticker in self.indicators:
            r = self.row(ticker, date)
            if r is None:
                continue
            trail = r.close - mult * r.atr
            if portfolio.has_position(ticker):
                stop = self.stops.get(ticker, trail)
                if r.close <= stop:
                    signals.append(Signal(ticker, Action.SELL,
                                          f"ATR stop hit at {stop:.2f}"))
                elif r.close < r.exit_lower:
                    signals.append(Signal(ticker, Action.SELL,
                                          "Broke Donchian exit channel"))
                else:
                    self.stops[ticker] = max(stop, trail)
                continue

            self.stops.pop(ticker, None)
            if r.close > r.entry_upper:
                self.stops[ticker] = trail
                signals.append(Signal(
                    ticker, Action.BUY, "Donchian breakout",
                    score=float((r.close - r.entry_upper) / r.atr),
                    stop_price=float(trail)))
        return signals

    def get_state(self) -> dict:
        return {"stops": dict(self.stops)}

    def set_state(self, state: dict) -> None:
        self.stops = {t: float(s) for t, s in state.get("stops", {}).items()}

    def position_size(self, signal: Signal, date: pd.Timestamp,
                      equity: float, unit_cost_chf: float) -> int:
        """Risk a fixed fraction of equity on the distance to the stop."""
        p = self.params
        close, fx, _ = self._quote(signal.ticker, date)
        stop_distance_chf = (close - signal.stop_price) * fx
        if not stop_distance_chf > 0:
            return 0
        risk_qty = equity * p["risk_per_trade_pct"] / stop_distance_chf
        cap_qty = equity * p["max_position_pct"] / unit_cost_chf
        return int(math.floor(min(risk_qty, cap_qty)))

    def entry_check(self, ticker, date):
        r = self.row(ticker, date)
        if r is None:
            return None
        n = self.params["donchian_entry"]
        below = r.entry_upper / r.close - 1
        return rule_check([
            (r.close > r.entry_upper, 1 - below / 0.10,
             f"a close above the {n}-day high {r.entry_upper:.2f} "
             f"(now {below:.1%} below)"),
        ], f"Breakout above the {n}-day high")

    def exit_check(self, ticker, date, portfolio):
        r = self.row(ticker, date)
        if r is None:
            return None
        stop = self.stops.get(ticker)
        if stop is not None and r.close <= stop:
            return "Stop hit: selling at the next open"
        if r.close < r.exit_lower:
            return "Broke its exit channel: selling at the next open"
        text = (f"Also sells under the {self.params['donchian_exit']}-day "
                f"low {r.exit_lower:.2f}")
        if stop is None:
            return text
        return (f"Trailing stop at {stop:.2f}, {1 - stop / r.close:.1%} "
                f"below the price. " + text)
