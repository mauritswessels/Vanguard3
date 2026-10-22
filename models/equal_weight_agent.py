"""Passive benchmark: an equal share of every watched market, bought once.

Buy & Hold SPY is a narrow yardstick: the agents trade US, Swiss and
euro-area shares and funds, all in CHF, so part of any gap to SPY is just
"the US against Europe and Switzerland". This yardstick holds the whole
watchlist instead: on its first evening it splits the account into equal
shares, one per watched market, buys each at the next open and never sells.

Bought once and held, not rebalanced every month:

* It is the same kind of yardstick as Buy & Hold SPY: one round of fills,
  then nothing, so it pays its costs once and has no timing of its own.
* With a flat 2 CHF a fill and holdings of about 930 CHF, a monthly
  rebalance of some 100 markets would cost around 2.5% a year in fees and
  slippage, so the yardstick would mostly measure its own costs. It would
  also sell the winners and buy the losers every month, which is a
  strategy of its own (a mild Bargain Hunter), not a yardstick.
* The weights drift only slowly: a market that doubles goes from about 1%
  of the account to about 2%. Over the months and years this race runs it
  still answers "what did the average watched market do?".

Shares are whole, so each holding is as close to an equal share as whole
shares allow: the number of shares is rounded to the nearest, as long as
the cash lasts. A market whose single share costs more than about twice an
equal share is left out (Givaudan, near 4,000 CHF a share, against about
930 CHF). Dividends are paid into cash and stay there, as for Buy & Hold SPY.
All buys are paid at the next open, so on top of the usual cash buffer it
keeps a small ``cushion`` back (``EQUAL_WEIGHT_PARAMS``): when the markets
open higher than they closed, the last orders can still be paid.

Any market it does not hold yet (closed for a holiday on its first evening,
or an order the cash could not cover) is bought on a later evening with an
equal share, as far as its free cash allows. It runs as an ordinary agent,
so it pays the same costs and fills at the same opens as everyone else.
"""

from __future__ import annotations

import math

import pandas as pd

import config
from engine.portfolio import Portfolio
from models.base_agent import Action, BaseAgent, Signal


class EqualWeightAgent(BaseAgent):
    name = "Buy & Hold All Markets"
    style = ("Passive benchmark: an equal share of every watched market, "
             "bought once, never sold")
    benchmark = True

    def __init__(self, params: dict | None = None):
        super().__init__({**config.EQUAL_WEIGHT_PARAMS, **(params or {})})
        #: Shares to buy per market, worked out by ``calculate_signals``.
        self._plan: dict[str, int] = {}

    def compute_indicators(self, bars: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"close": bars["Close"]})

    def kept(self) -> float:
        """Share of the cash never planned for: the buffer and cushion."""
        return config.CASH_BUFFER_PCT + self.params["cushion"]

    def equal_share(self, date: pd.Timestamp, portfolio: Portfolio) -> float:
        """CHF for the shares of one market: the account split evenly over
        every watched market, less the cash kept back and the fee."""
        equity = portfolio.equity(self.market.close_chf(date))
        return (equity * (1.0 - self.kept()) / len(self.indicators)
                - portfolio.costs.commission_chf)

    def plan(self, date: pd.Timestamp, portfolio: Portfolio) -> dict[str, int]:
        """Whole shares to buy of each market not held yet that has a price.

        Each gets the rounded-down number of shares first. Then, biggest
        shortfall first, one more share wherever that brings the holding
        nearer to an equal share, while the free cash lasts.
        """
        costs, fee = portfolio.costs, portfolio.costs.commission_chf
        share = self.equal_share(date, portfolio)
        units = {}
        for t in sorted(self.indicators):
            if portfolio.has_position(t) or self.row(t, date) is None:
                continue
            units[t] = costs.buy_price_chf(*self._quote(t, date))
        qty = {t: max(int(share // u), 0) for t, u in units.items()}
        spent = sum(q * units[t] + fee for t, q in qty.items() if q)
        budget = portfolio.cash * (1.0 - self.kept())
        short = sorted(((share - qty[t] * u, t) for t, u in units.items()),
                       reverse=True)
        for gap, t in short:
            extra = units[t] + (0.0 if qty[t] else fee)
            if gap > units[t] / 2 and spent + extra <= budget:
                qty[t] += 1
                spent += extra
        return {t: q for t, q in qty.items() if q > 0}

    def calculate_signals(self, date: pd.Timestamp,
                          portfolio: Portfolio) -> list[Signal]:
        self._plan = self.plan(date, portfolio)
        return [Signal(t, Action.BUY, "Equal share of every market, "
                                      "bought once")
                for t in self._plan]

    def position_size(self, signal, date, equity, unit_cost_chf) -> int:
        return self._plan.get(signal.ticker, 0)

    def watch(self, date, portfolio):
        share = self.equal_share(date, portfolio)
        items = []
        for t in sorted(self.indicators):
            if portfolio.has_position(t):
                items.append({"ticker": t, "held": True, "progress": None,
                              "ready": False,
                              "note": "Holds it for good and never sells"})
                continue
            close, fx, _ = self._quote(t, date)
            dear = math.isfinite(close) and close * fx > 2 * share
            items.append({"ticker": t, "held": False, "progress": None,
                          "ready": not dear,
                          "note": "Left out: one share costs more than "
                                  "twice an equal share" if dear
                          else "Buys an equal share once it has a price "
                               "and the cash"})
        items.sort(key=lambda i: not i["held"])
        return items
