"""Agent 5 - "The News Analyst" (reads the news with Claude).

Every evening, on the latest completed session only, it builds a brief of
headlines (per market and on politics / the economy), each stock's
latest quarterly results and recent price moves, then asks Claude for
target weights with a short reason per market (see ``news.py``), and the
chance each market beats SPY over the next 5 trading days, which its
report card checks for calibration (``engine/grading.py``).

* Buys a market whose target is above zero and that it does not hold,
  sized to the target weight.
* Sells a held market whose target drops to zero.
* Leaves other holdings alone, to keep trading costs down.

A second, shorter check runs around midday (``midday_news.py``): it may
change targets, and those trades fill at once at the live price.

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
from engine import grading
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal

logger = logging.getLogger("vanguard3.news")


class NewsAgent(BaseAgent):
    name = "News Analyst"
    style = ("Claude reads headlines, politics and quarterly results each "
             "evening, and again at midday")

    defaults = config.NEWS_PARAMS

    def __init__(self, params: dict | None = None):
        super().__init__({**self.defaults, **(params or {})})
        self.targets: dict[str, dict] = {}
        self.view = ""
        self.status = "Waiting for its first evening"
        self.decided: str | None = None
        self.calls = 0
        self.tokens = {"input": 0, "output": 0}
        self.headline_count = 0
        self.model_used = self.params["model"]
        #: What it read per market in the latest check (not saved).
        self.read: dict[str, dict] = {}
        #: The latest midday check: time (UTC), what happened, trades made.
        self.midday: dict | None = None
        #: How its past trades turned out (see ``report_card``).
        self.card: dict | None = None
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
        ccy = self.market.currencies[t]
        return (f"close {r.close:.2f} {ccy}, 1 week {r.ret5:+.1%}, "
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
        lines = {t: self._price_line(t, date) for t in self.indicators}
        self.card = self.report_card(portfolio.trades, date)
        if not self.consult(lines, holdings, portfolio.cash / equity):
            return []
        self.decided = date.strftime("%Y-%m-%d")
        self.status = f"Decided with {self.model_used}"
        return self.target_signals(portfolio)

    def consult(self, lines: dict[str, str], holdings: dict[str, float],
                cash_pct: float, note: str = "") -> bool:
        """Read the news and ask Claude; on success store the new targets.

        On failure (no key, no news, a bad reply) the old targets stay and
        ``status`` says why.
        """
        p = self.params
        try:
            brief = self.build_brief(lines)
            self.headline_count = len(brief["macro"]) + sum(
                len(e["news"]) for e in brief["markets"].values())
            if self.headline_count == 0:
                raise RuntimeError("no headlines could be loaded")
            note = "\n\n".join(x for x in (self.memory_text(), note) if x)
            extra = {"note": note} if note else {}
            decision = self.decide(brief, holdings, cash_pct, p["model"],
                                   p["max_weight"], p["max_total"], **extra)
        except Exception as exc:
            self.status = (
                "Waiting for an Anthropic API key (no decision made)"
                if "ANTHROPIC_API_KEY" in str(exc)
                else f"No decision today: {str(exc)[:160]}")
            logger.warning("%s: %s", self.name, self.status)
            return False

        self.targets, self.view = decision["targets"], decision["market_view"]
        self.read = {t: {"news": e.get("news", [])[:6], "results": e.get("results")}
                     for t, e in brief["markets"].items()}
        self.calls += 1
        usage = decision.get("usage", {})
        self.tokens["input"] += int(usage.get("input_tokens", 0))
        self.tokens["output"] += int(usage.get("output_tokens", 0))
        self.model_used = decision.get("model", p["model"])
        return True

    def target_signals(self, portfolio: Portfolio) -> list[Signal]:
        """Buy new targets, sell held markets whose target is 0."""
        signals = []
        for t, tgt in self.targets.items():
            held = portfolio.has_position(t)
            reason = tgt["reason"] or "No reason given"
            if held and tgt["weight"] <= 0:
                signals.append(Signal(t, Action.SELL, reason))
            elif not held and tgt["weight"] >= self.params["min_weight"]:
                signals.append(Signal(t, Action.BUY, reason,
                                      score=tgt["weight"]))
        return signals

    def decision_details(self, signal, date) -> dict:
        tgt = self.targets.get(signal.ticker, {})
        seen = self.read.get(signal.ticker, {})
        return {"target_weight": tgt.get("weight"),
                # Its stated chance this market beats SPY over the next 5
                # trading days; the report card checks it (calibration).
                "probability": tgt.get("probability"),
                "market_view": self.view,
                "headlines": seen.get("news", []),
                "quarterly": seen.get("results"),
                "model": self.model_used}

    def position_size(self, signal, date, equity, unit_cost_chf) -> int:
        w = self.targets.get(signal.ticker, {}).get("weight", 0.0)
        return int(math.floor(equity * w / unit_cost_chf))

    # -- report card and memory ---------------------------------------------
    HORIZONS = grading.HORIZONS   # trading days after a trade when it is graded

    def report_card(self, trades, date: pd.Timestamp) -> dict:
        """Grade every past trade against the S&P 500 (SPY).

        A buy was right if the market then beat SPY; a sell was right if it
        then lagged SPY. Each trade is graded after 5 and after 20 trading
        days by the shared grader (``engine.grading``), the same one every
        account's report card uses. Uses only prices up to ``date``.
        """
        fills = [{"date": t.date, "ticker": t.ticker, "side": t.side,
                  "decided": getattr(t, "decided", None)} for t in trades]
        calls = grading.grade_fills(fills, self.market, date)
        keep = ("date", "ticker", "side") + tuple(
            f"edge_{h}" for h in self.HORIZONS)
        card = {"calls": [{k: c[k] for k in keep if k in c}
                          for c in calls[-40:]]}
        numbers = grading.stats(calls)
        for h in self.HORIZONS:
            for k in ("graded", "hit_rate", "avg_edge"):
                card[f"{k}_{h}"] = numbers[f"{k}_{h}"]
        return card

    def memory_text(self) -> str:
        """Its own track record, put in front of every brief."""
        card = self.card or {}
        graded = [c for c in card.get("calls", []) if "edge_5" in c][-15:]
        if not graded:
            return ""
        lines = []
        for c in graded:
            verb = "bought" if c["side"] == "BUY" else "sold"
            grade = "right" if c["edge_5"] > 0 else "wrong"
            later = (f"; after 20 days {c['edge_20']:+.1%}"
                     if "edge_20" in c else "")
            lines.append(f"- {c['date']} {verb} {c['ticker']}: after 5 "
                         f"trading days {c['edge_5']:+.1%} vs SPY ({grade})"
                         f"{later}")
        rate = card.get("hit_rate_5")
        head = (f"YOUR TRACK RECORD so far: {rate:.0%} of "
                f"{card['graded_5']} graded trades were right after 5 trading "
                "days (a buy is right if the market then beat SPY, a sell if "
                "it lagged SPY). Your most recent graded trades:")
        return (head + "\n" + "\n".join(lines) + "\nLearn from this: "
                "notice which kinds of calls worked and which did not, and "
                "adjust. Do not chase or avoid a market only because of one "
                "past result.")

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
                "tokens": self.tokens, "est_cost_usd": round(cost, 2),
                "midday": self.midday, "report_card": self.card}

    # -- persistence ---------------------------------------------------------
    def get_state(self) -> dict:
        return {"targets": self.targets, "view": self.view,
                "status": self.status, "decided": self.decided,
                "calls": self.calls, "tokens": self.tokens,
                "headlines": self.headline_count, "midday": self.midday,
                "card": self.card}

    def set_state(self, state: dict) -> None:
        self.targets = state.get("targets", {})
        self.view = state.get("view", "")
        self.status = state.get("status", self.status)
        self.decided = state.get("decided")
        self.calls = state.get("calls", 0)
        self.tokens = state.get("tokens", {"input": 0, "output": 0})
        self.headline_count = state.get("headlines", 0)
        self.midday = state.get("midday")
        self.card = state.get("card")


class OpusNewsAgent(NewsAgent):
    """The News Analyst on Claude Opus: same news, rules and limits, only the
    model differs, so the race shows what a stronger model is worth."""

    name = "News Analyst (Opus)"
    style = ("The News Analyst's twin on Claude Opus, a stronger model: "
             "same news, same rules")
    defaults = config.NEWS_OPUS_PARAMS
