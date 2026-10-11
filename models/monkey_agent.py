"""Yardstick: "The Monkey" picks markets at random.

It plays by the same rules as the real agents (10 positions of 10% each,
the same fees, fills at the next open) but chooses by dice roll:

* Each evening every holding has a 1 in ``avg_hold_days`` chance of being
  sold, so a position lasts about a month on average.
* Free slots are filled with markets picked at random.

With nine accounts in the race, one will lead by luck alone. An agent only
shows skill if it keeps beating the monkey over many weeks.

The dice are seeded by the date, so a replayed day makes the same picks
and nothing needs to be saved between runs.
"""

from __future__ import annotations

import random

import pandas as pd

import config
from engine.portfolio import Portfolio
from models.base_agent import Action, BaseAgent, Signal


class MonkeyAgent(BaseAgent):
    name = "Monkey"
    style = "Random picks under the same rules and costs: the luck yardstick"
    benchmark = True

    def __init__(self, params: dict | None = None):
        super().__init__({**config.MONKEY_PARAMS, **(params or {})})

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close": bars["Close"]})

    def _dice(self, date: pd.Timestamp, what: str = "") -> random.Random:
        return random.Random(f"{self.params['seed']}|{date:%Y-%m-%d}|{what}")

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        p = self.params
        signals = []
        for ticker in sorted(portfolio.positions):
            if (self.row(ticker, date) is not None
                    and self._dice(date, ticker).random()
                    < 1 / p["avg_hold_days"]):
                signals.append(Signal(ticker, Action.SELL, "Dice said sell"))
        room = p["max_positions"] - len(portfolio.positions) + len(signals)
        pool = sorted(t for t in self.indicators
                      if not portfolio.has_position(t)
                      and self.row(t, date) is not None)
        for ticker in self._dice(date).sample(pool, max(min(room, len(pool)),
                                                        0)):
            signals.append(Signal(ticker, Action.BUY, "Picked at random"))
        return signals

    def watch(self, date, portfolio):
        chance = 1 / self.params["avg_hold_days"]
        return [{"ticker": t, "held": True, "progress": None, "ready": False,
                 "note": f"Holds it until the dice say sell "
                         f"({chance:.0%} chance each evening)"}
                for t in sorted(portfolio.positions)]
