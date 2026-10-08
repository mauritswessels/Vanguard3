"""Agent 5 - "The News Analyst" (reads the news with Claude).

Every evening, on the latest completed session only, it builds a brief of
headlines (per market and on politics / the economy), the five stocks'
latest quarterly results and recent price moves, then asks Claude for
target weights with a short reason per market (see ``news.py``).

* Buys a market whose target is above zero and that it does not hold,
  sized to the target weight.
* Sells a held market whose target drops to zero.
* Leaves other holdings alone, to keep trading costs down.

Sessions replayed while catching up after a missed run are skipped: the
news it can read is today's, so it only decides for the newest session.
Without ``ANTHROPIC_API_KEY`` (or when the news or the call fails) it does
nothing that day and says why on the dashboard.

The reasons shown are the model's own stated reasons, not a guaranteed
account of how it reached its answer.
"""

from __future__ import annotations

import logging
import math

import pandas as pd

import config
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal

logger = logging.getLogger("vanguard3.news")


class NewsAgent(BaseAgent):
    name = "News Analyst"
    style = "Claude reads headlines, politics and quarterly results each evening"

    def __init__(self, params: dict | None = None):
        super().__init__({**config.NEWS_PARAMS, **(params or {})})
        self.targets: dict[str, dict] = {}
        self.view = ""
        self.status = "Waiting for its first evening"
        self.decided: str | None = None
        self.calls = 0
        self.tokens = {"input": 0, "output": 0}
        self.headline_count = 0
        # Swappable for tests: brief(market_lines) and decide(brief, ...).
        import news
        self.build_brief = news.build_brief
        self.decide = news.ask_claude

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        c = bars["Close"]
        return pd.DataFrame({"close": c,
                             "ret5": c / c.shift(5) - 1,
                             "ret20": c / c.shift(20) - 1,
                             "vs200": c / ind.sma(c, 200) - 1},
                            index=bars.index)

    def _price_line(self, t: str, date: pd.Timestamp) -> str:
        r = self.row(t, date)
        if r is None:
            return "price history incomplete"
        return (f"close {r.close:.2f} USD, 1 week {r.ret5:+.1%}, "
                f"1 month {r.ret20:+.1%}, vs 200-day average {r.vs200:+.1%}")

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        if date != self.market.calendar[-1]:
            return []                       # catching up: no news for the past
        if self.market.source == "synthetic":
            self.status = "Test prices: real news would not match them"
            return []
        prices = self.market.close_chf(date)
        equity = portfolio.equity(prices)
        holdings = {t: p.quantity * float(prices[t]) / equity
                    for t, p in portfolio.positions.items()}
        p = self.params
        try:
            brief = self.build_brief({t: self._price_line(t, date)
                                      for t in self.indicators})
            self.headline_count = len(brief["macro"]) + sum(
                len(e["news"]) for e in brief["markets"].values())
            if self.headline_count == 0:
                raise RuntimeError("no headlines could be loaded")
            decision = self.decide(brief, holdings, portfolio.cash / equity,
                                   p["model"], p["max_weight"], p["max_total"])
        except Exception as exc:
            self.status = (
                "Waiting for an Anthropic API key (no decision made)"
                if "ANTHROPIC_API_KEY" in str(exc)
                else f"No decision today: {str(exc)[:160]}")
            logger.warning("%s: %s", self.name, self.status)
            return []

        self.targets, self.view = decision["targets"], decision["market_view"]
        self.decided = date.strftime("%Y-%m-%d")
        self.calls += 1
        usage = decision.get("usage", {})
        self.tokens["input"] += int(usage.get("input_tokens", 0))
        self.tokens["output"] += int(usage.get("output_tokens", 0))
        self.status = f"Decided with {decision.get('model', p['model'])}"

        signals = []
        for t, tgt in self.targets.items():
            held = portfolio.has_position(t)
            reason = tgt["reason"] or "No reason given"
            if held and tgt["weight"] <= 0:
                signals.append(Signal(t, Action.SELL, reason))
            elif not held and tgt["weight"] >= p["min_weight"]:
                signals.append(Signal(t, Action.BUY, reason,
                                      score=tgt["weight"]))
        return signals

    def position_size(self, signal, date, equity, unit_cost_chf) -> int:
        w = self.targets.get(signal.ticker, {}).get("weight", 0.0)
        return int(math.floor(equity * w / unit_cost_chf))

    # -- explaining ----------------------------------------------------------
    def watch(self, date, portfolio):
        items = []
        for t in self.indicators:
            tgt = self.targets.get(t)
            held = portfolio.has_position(t)
            if not tgt:
                items.append({"ticker": t, "held": held, "progress": None,
                              "ready": False, "note": "No decision yet"})
                continue
            w = tgt["weight"]
            note = (f"Target {w:.0%} of the account. " if w else "Target 0%. ") \
                + (tgt["reason"] or "")
            items.append({"ticker": t, "held": held,
                          "progress": None if held else round(
                              min(1.0, w / self.params["max_weight"]), 3),
                          "ready": (not held) and w >= self.params["min_weight"],
                          "note": note})
        items.sort(key=lambda i: (not i["held"], -(i["progress"] or 0)))
        return items

    def summary(self) -> dict:
        p = self.params
        cost = (self.tokens["input"] * p["usd_per_m_input"]
                + self.tokens["output"] * p["usd_per_m_output"]) / 1e6
        return {"kind": "news", "model": p["model"], "status": self.status,
                "decided": self.decided, "market_view": self.view,
                "calls": self.calls, "headlines": self.headline_count,
                "tokens": self.tokens, "est_cost_usd": round(cost, 2)}

    # -- persistence ---------------------------------------------------------
    def get_state(self) -> dict:
        return {"targets": self.targets, "view": self.view,
                "status": self.status, "decided": self.decided,
                "calls": self.calls, "tokens": self.tokens,
                "headlines": self.headline_count}

    def set_state(self, state: dict) -> None:
        self.targets = state.get("targets", {})
        self.view = state.get("view", "")
        self.status = state.get("status", self.status)
        self.decided = state.get("decided")
        self.calls = state.get("calls", 0)
        self.tokens = state.get("tokens", {"input": 0, "output": 0})
        self.headline_count = state.get("headlines", 0)
