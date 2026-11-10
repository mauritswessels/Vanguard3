"""The owner's own mix: a watch-only line next to the race.

The owner holds a handful of shares and funds with real money. This file
works out what that mix has done since the race began, so the website can
draw it next to the agents: the same number of shares of each holding
(``config.OWNER_MIX``), valued in CHF at every close and scaled so it is
worth 100,000 CHF at the close the race started from, like every account.

It is only a line on a chart, not an account:

* nothing is bought or sold, so there are no costs and no timing; it shows
  how the mix itself moved, not what the owner paid or earned;
* the shares are scaled, so the website shows the mix and never the
  owner's real amounts;
* no agent sees it and it is not in the rankings, the Team Manager or the
  IBKR copy, so the race is unchanged.

Prices come from the same place as the agents' (Yahoo, Stooq as backup),
converted to CHF the same way. A holding without prices is left out and
named under ``missing``, so the website can say so instead of showing a
wrong line. Writes ``docs/data/mix.json``; the evening run calls it after
the accounts are advanced.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

import config
from data_manager import MarketData, load_market_data

logger = logging.getLogger(__name__)

OUT_FILE = config.DASHBOARD_DATA_DIR / "mix.json"


def build(market: MarketData, mix: dict = config.OWNER_MIX,
          capital: float = config.INITIAL_CAPITAL_CHF) -> dict | None:
    """The mix's daily value in CHF from ``mix["start"]``, scaled to
    ``capital`` at that close, plus each holding's share and return.
    ``None`` when no holding has a price on the start day yet."""
    start = pd.Timestamp(mix["start"])
    cal = market.calendar
    days = cal[cal >= start]
    if not len(days):
        return None
    # The base is the start close itself, or the last close before it
    # when the start was a holiday for every holding.
    base_day = cal[cal <= start].max() if (cal <= start).any() else days[0]
    held = {t: h for t, h in mix["holdings"].items()
            if t in market.bars
            and pd.notna(market.close_panel.at[base_day, t])}
    missing = [t for t in mix["holdings"] if t not in held]
    if not held:
        return None

    def value(day: pd.Timestamp, t: str) -> float:
        return (held[t][0] * float(market.close_panel.at[day, t])
                * market.fx_rate(t, day))

    base = {t: value(base_day, t) for t in held}
    scale = capital / sum(base.values())
    span = [base_day] + [d for d in days if d > base_day]
    equity = [[d.strftime("%Y-%m-%d"),
               round(scale * sum(value(d, t) for t in held), 2)]
              for d in span]
    last = span[-1]
    now = {t: value(last, t) for t in held}
    total_now = sum(now.values())
    holdings = [{
        "ticker": t,
        "name": held[t][2],
        "currency": held[t][1],
        "weight_start": round(base[t] / sum(base.values()), 4),
        "weight_now": round(now[t] / total_now, 4),
        # In CHF, so currency moves are included.
        "return": round(now[t] / base[t] - 1, 4),
    } for t in held]
    holdings.sort(key=lambda h: -h["weight_start"])
    return {
        "name": mix["name"],
        "start": base_day.strftime("%Y-%m-%d"),
        "last": last.strftime("%Y-%m-%d"),
        "capital_chf": capital,
        "holdings": holdings,
        "missing": missing,
        "equity": equity,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default="yfinance",
                    help="yfinance (default), auto or synthetic")
    ap.add_argument("--out", type=Path, default=OUT_FILE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    mix = config.OWNER_MIX
    watchlist = {t: h[1] for t, h in mix["holdings"].items()}
    start = pd.Timestamp(mix["start"]) - pd.Timedelta(days=10)
    end = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    # No cache: a few small downloads, always fresh.
    market = load_market_data(args.source, start, end, watchlist=watchlist,
                              cache_dir=None)
    out = build(market, mix)
    if out is None:
        logger.warning("No prices for the owner's mix yet; nothing written")
        return 0
    out["generated_utc"] = pd.Timestamp.now(tz="UTC").isoformat(
        timespec="seconds")
    out["data_source"] = market.source
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    logger.info("Owner's mix: %s, %d days, %s missing",
                f"{out['equity'][-1][1]:,.0f} CHF", len(out["equity"]),
                ", ".join(out["missing"]) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
