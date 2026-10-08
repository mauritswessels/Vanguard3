"""Agent 4 - "The AI Learner" (reinforcement learning, learns every day).

A small, transparent reinforcement-learning agent, the Python twin of the
one in the 3D research lab (``docs/lab/js/sim/agent.js``):

* State:   10 price features per ticker (momentum, trend, RSI, volatility,
           drawdown ...), scaled to roughly -3..3, plus "do I hold it".
* Model:   one linear score per action, ``Q(s, a) = w_a . phi(s)``, for
           SELL / HOLD / BUY, shared by every ticker.
* Reward:  the ticker's next-day return while held (in %), minus a small
           penalty for every change of position.
* Learning: one Q-learning update per ticker after every close, using what
           actually happened since the previous decision. Before its first
           day it pre-trains on the previous ``pretrain_years`` of prices.

Until ``live_from`` it runs in shadow mode: it decides and learns every day
but places no orders. Exploration (random actions with probability
``epsilon``) is seeded by date and ticker, so a rerun gives the same result.

Explanations are exact for this model: each feature's share of a score is
``w_a,i * phi_i``. They describe how the model scores, not why markets move.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd

import config
from engine.portfolio import Portfolio
from models import indicators as ind
from models.base_agent import Action, BaseAgent, Signal

ACTIONS = ["SELL", "HOLD", "BUY"]
SELL, HOLD, BUY = range(3)

#: (column, label, centre, scale): z = (raw - centre) / scale, clipped to 3.
FEATURES = [
    ("ret1", "1-day return", 0.0, 0.015),
    ("ret5", "5-day momentum", 0.0, 0.035),
    ("ret20", "20-day momentum", 0.0, 0.07),
    ("ema_gap", "price vs 20-day average", 0.0, 0.03),
    ("trend", "20- vs 50-day trend", 0.0, 0.04),
    ("rsi", "RSI", 50.0, 20.0),
    ("vol", "20-day volatility", 0.015, 0.01),
    ("vol_ratio", "volatility vs 100-day", 0.0, 0.3),
    ("dd60", "drop from 60-day high", -0.05, 0.05),
    ("z20", "distance from 20-day mean", 0.0, 1.2),
]
N_FEAT = len(FEATURES)
DIM = N_FEAT + 2            # features + holding flag + bias


class LearnerAgent(BaseAgent):
    name = "AI Learner"
    style = "Reinforcement learning that updates itself after every close"

    def __init__(self, params: dict | None = None):
        super().__init__({**config.LEARNER_PARAMS, **(params or {})})
        self.w: np.ndarray | None = None      # (3, DIM) weights
        self.epsilon = self.params["epsilon"]
        self.updates = 0
        self.days_learned = 0
        self.pretrain: dict = {}
        self.shadow: dict[str, int] = {}      # position the model chose
        self.memory: dict[str, dict] = {}     # yesterday's decision per ticker
        self.td_recent: list[float] = []
        self.last_decisions: dict[str, dict] = {}

    # -- features ------------------------------------------------------------
    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        c = bars["Close"]
        r1 = np.log(c / c.shift(1))
        ema20, ema50 = ind.ema(c, 20), ind.ema(c, 50)
        vol20 = r1.rolling(20).std()
        sma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
        raw = pd.DataFrame({
            "ret1": r1,
            "ret5": np.log(c / c.shift(5)),
            "ret20": np.log(c / c.shift(20)),
            "ema_gap": c / ema20 - 1,
            "trend": ema20 / ema50 - 1,
            "rsi": ind.rsi(c, 14),
            "vol": vol20,
            "vol_ratio": vol20 / r1.rolling(100).std() - 1,
            "dd60": c / c.rolling(60).max() - 1,
            "z20": (c - sma20) / sd20,
        }, index=bars.index)
        out = pd.DataFrame(index=bars.index)
        out["close"] = c
        for col, _, centre, scale in FEATURES:
            out[col] = ((raw[col] - centre) / scale).clip(-3, 3)
        return out

    def _z(self, ticker: str, date: pd.Timestamp) -> np.ndarray | None:
        r = self.row(ticker, date)
        if r is None:
            return None
        return np.array([getattr(r, col) for col, *_ in FEATURES])

    @staticmethod
    def _phi(z: np.ndarray, held: int) -> np.ndarray:
        return np.concatenate([z, [1.0 if held else -1.0, 1.0]])

    # -- the model -----------------------------------------------------------
    def _q(self, phi: np.ndarray) -> np.ndarray:
        return self.w @ phi

    def _update(self, phi, a, reward, phi_next) -> float:
        p = self.params
        target = reward + p["gamma"] * float(np.max(self._q(phi_next)))
        td = float(np.clip(target - self.w[a] @ phi, -5, 5))
        self.w[a] = np.clip(self.w[a] + p["lr"] * td * phi, -4, 4)
        self.updates += 1
        return td

    def _act(self, phi, rng: random.Random, epsilon: float) -> tuple[int, bool]:
        if rng.random() < epsilon:
            return rng.randrange(3), True
        return int(np.argmax(self._q(phi))), False

    def _reward(self, ret: float, pos: int, changed: bool) -> float:
        return pos * ret * 100 - (self.params["trade_cost"] if changed else 0)

    @staticmethod
    def _next_pos(a: int, pos: int) -> int:
        return 1 if a == BUY else 0 if a == SELL else pos

    def _pretrain(self, until: pd.Timestamp) -> None:
        """Practise on the years before ``until`` so day one is not random."""
        p = self.params
        rng = random.Random(p["seed"])
        self.w = np.array([[rng.uniform(-0.01, 0.01) for _ in range(DIM)]
                           for _ in ACTIONS])
        start = until - pd.DateOffset(years=p["pretrain_years"])
        series = {}
        for t, frame in self.indicators.items():
            f = frame.loc[(frame.index >= start) & (frame.index < until)].dropna()
            if len(f) > 1:
                series[t] = (f[[c for c, *_ in FEATURES]].to_numpy(),
                             np.log(f["close"]).diff().shift(-1).to_numpy())
        epochs = p["pretrain_epochs"]
        for e in range(epochs):
            eps = 0.5 * (1 - e / epochs) + p["epsilon"] * e / epochs
            for t in sorted(series):
                z, ret = series[t]
                pos = 0
                for i in range(len(z) - 1):
                    phi = self._phi(z[i], pos)
                    a, _ = self._act(phi, rng, eps)
                    new = self._next_pos(a, pos)
                    reward = self._reward(ret[i], new, new != pos)
                    self._update(phi, a, reward, self._phi(z[i + 1], new))
                    pos = new
        days = {d for f in self.indicators.values()
                for d in f.index[(f.index >= start) & (f.index < until)]}
        self.pretrain = {"from": start.strftime("%Y-%m-%d"),
                         "to": (until - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                         "sessions": len(days), "epochs": epochs,
                         "updates": self.updates}

    # -- daily step ----------------------------------------------------------
    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        if self.w is None:
            self._pretrain(date)

        # 1. Learn from what happened since yesterday's decisions.
        tds = []
        for t, m in list(self.memory.items()):
            z = self._z(t, date)
            if z is None:
                continue
            close = float(self.indicators[t].at[date, "close"])
            ret = math.log(close / m["close"])
            reward = self._reward(ret, m["pos"], m["pos"] != m["prev"])
            tds.append(abs(self._update(np.array(m["phi"]), m["a"], reward,
                                        self._phi(z, m["pos"]))))
        if tds:
            self.days_learned += 1
            self.td_recent = (self.td_recent + [float(np.mean(tds))])[-20:]

        # 2. Decide for today.
        live = date >= pd.Timestamp(self.params["live_from"])
        self.memory, self.last_decisions, signals = {}, {}, []
        for t in self.indicators:
            z = self._z(t, date)
            if z is None:
                continue
            held = int(portfolio.has_position(t)) if live else self.shadow.get(t, 0)
            phi = self._phi(z, held)
            rng = random.Random(f"{self.params['seed']}|{date.date()}|{t}")
            a, explored = self._act(phi, rng, self.epsilon)
            new = self._next_pos(a, held)
            self.shadow[t] = new
            self.memory[t] = {"phi": phi.tolist(), "a": a, "pos": new,
                              "prev": held,
                              "close": float(self.indicators[t].at[date, "close"])}
            q = self._q(phi)
            self.last_decisions[t] = {"action": ACTIONS[a], "explored": explored,
                                      "q": [round(float(v), 4) for v in q]}
            if not live or new == held:
                continue
            why = self._reason(phi, a, explored)
            if a == BUY:
                signals.append(Signal(t, Action.BUY, why,
                                      score=float(q[BUY] - q[HOLD])))
            elif a == SELL:
                signals.append(Signal(t, Action.SELL, why))
        return signals

    def execute_trade(self, signals, date, portfolio, broker):
        # Respect the position cap: keep the highest-scoring buys only.
        room = self.params["max_positions"] - len(portfolio.positions) + sum(
            1 for s in signals if s.action is Action.SELL)
        buys = sorted((s for s in signals if s.action is Action.BUY),
                      key=lambda s: s.score, reverse=True)[:max(room, 0)]
        keep = [s for s in signals if s.action is Action.SELL] + buys
        return super().execute_trade(keep, date, portfolio, broker)

    # -- explaining ----------------------------------------------------------
    def _contributions(self, phi: np.ndarray, a: int) -> list[tuple[str, float]]:
        avg = self.w[:, :N_FEAT].mean(axis=0)
        parts = [(FEATURES[i][1], float((self.w[a, i] - avg[i]) * phi[i]))
                 for i in range(N_FEAT)]
        return sorted(parts, key=lambda x: -abs(x[1]))

    def _reason(self, phi, a, explored) -> str:
        if explored:
            return f"Exploring: tried {ACTIONS[a]} at random to learn"
        name, c = self._contributions(phi, a)[0]
        return (f"Model score favours {ACTIONS[a]}; biggest factor: {name} "
                f"({'for' if c > 0 else 'against'})")

    def _probs(self, phi) -> np.ndarray:
        q = self._q(phi)
        e = np.exp((q - q.max()) / 0.5)
        return e / e.sum()

    def entry_check(self, ticker, date):
        z = self._z(ticker, date)
        if z is None or self.w is None:
            return None
        phi = self._phi(z, 0)
        probs = self._probs(phi)
        best = int(np.argmax(probs))
        ready = best == BUY
        name, c = self._contributions(phi, BUY)[0]
        lean = "for" if c > 0 else "against"
        note = (f"Model favours BUY ({probs[BUY]:.0%} of its score)" if ready
                else f"Model says stay out; BUY gets {probs[BUY]:.0%} "
                     f"of its score")
        return {"progress": round(float(probs[BUY] / probs[best]), 3),
                "ready": ready,
                "note": f"{note}. Biggest factor: {name} ({lean})"}

    def exit_check(self, ticker, date, portfolio):
        z = self._z(ticker, date)
        if z is None or self.w is None:
            return None
        probs = self._probs(self._phi(z, 1))
        best = int(np.argmax(probs))
        if best == SELL:
            return "Model now favours SELL"
        return (f"Model says keep holding; SELL gets {probs[SELL]:.0%} "
                f"of its score. Sells once SELL scores highest")

    def summary(self) -> dict:
        """Learning facts for the dashboard."""
        return {"live_from": self.params["live_from"],
                "days_learned": self.days_learned, "updates": self.updates,
                "epsilon": self.epsilon, "pretrain": self.pretrain,
                "td_recent": self.td_recent[-10:],
                "weights": {a: dict(zip([f[1] for f in FEATURES],
                                        np.round(self.w[i, :N_FEAT], 3).tolist()))
                            for i, a in enumerate(ACTIONS)}
                if self.w is not None else None}

    # -- persistence ---------------------------------------------------------
    def get_state(self) -> dict:
        return {"w": self.w.tolist() if self.w is not None else None,
                "epsilon": self.epsilon, "updates": self.updates,
                "days_learned": self.days_learned, "pretrain": self.pretrain,
                "shadow": self.shadow, "memory": self.memory,
                "td_recent": self.td_recent}

    def set_state(self, state: dict) -> None:
        self.w = np.array(state["w"]) if state.get("w") is not None else None
        self.epsilon = state.get("epsilon", self.params["epsilon"])
        self.updates = state.get("updates", 0)
        self.days_learned = state.get("days_learned", 0)
        self.pretrain = state.get("pretrain", {})
        self.shadow = {t: int(v) for t, v in state.get("shadow", {}).items()}
        self.memory = state.get("memory", {})
        self.td_recent = state.get("td_recent", [])
