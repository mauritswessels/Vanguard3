"""Midday news check: the news agents read the news again during the day.

Runs on weekdays at 14:37 UTC (GitHub Actions, see
``.github/workflows/midday-news.yml``), when New York has been open for a
while and the European exchanges are still open::

    python midday_news.py            # add --dry-run to save nothing

What it does, for each news agent's account (the News Analyst and its Opus
twin) only:

1. fills last evening's orders at this morning's open (by midday they
   would have filled already),
2. reads today's headlines with live prices (Finnhub real-time for US
   markets when ``FINNHUB_API_KEY`` is set; Yahoo, about 15 minutes
   delayed, for the rest and as the backup),
3. asks Claude whether anything has changed enough to act on,
4. trades those changes, with the same costs as every other fill:

   * a market with a real-time price (Finnhub) fills at once at that price;
   * a market open now whose price is delayed (Yahoo: all Swiss and
     European markets, and US ones without Finnhub) gets a market-on-close
     order instead, which the evening run fills at that day's official
     close (a real order cannot trade at a price 15 minutes old);
   * a market that is closed right now is left for the evening check.

Everything is simulated: no broker is contacted and no real order is
placed. The other accounts are not touched; the evening run carries on as
usual and fills, marks and decides for everyone after the close.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import pandas as pd

import config
import finnhub_feed
from daily_run import last_completed_session, load_for_state
from engine.broker import Order
from engine.simulator import Simulator, _activity, decision_context
from main import setup_logging
from models import NEWS_KEYS, agent_key
from models.base_agent import Action
from reporting import dashboard_payload, write_json

logger = logging.getLogger("vanguard3.midday")

#: A market whose newest quote is older than this is treated as closed now.
LIVE_MINUTES = 45

#: A price this far from the last close (as a ratio) most likely means a
#: share split today: that market is left for the evening run, which
#: restates the holdings in post-split shares first.
SPLIT_LIKE = (0.6, 1.6)


def intraday_quotes(symbols: list[str], now: pd.Timestamp) -> dict:
    """Today's open and latest price per symbol, from 5-minute Yahoo bars.

    Returns ``{symbol: {"open", "last", "time", "live", "realtime"}}``.
    ``open`` is ``None`` when the market has not traded today (not open
    yet, or a holiday); ``live`` says whether it is trading right now.
    Yahoo's prices are about 15 minutes old, so ``realtime`` is False.
    """
    import yfinance as yf
    raw = yf.download(symbols, period="1d", interval="5m", group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    out = {}
    for s in symbols:
        try:
            df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Open", "Close"])
        except KeyError:
            continue
        if df.empty:
            continue
        idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
        idx = idx.tz_convert("UTC")
        today = df[idx.normalize() == now.normalize()]
        if today.empty:
            out[s] = {"open": None, "last": float(df["Close"].iloc[-1]),
                      "time": None, "live": False, "realtime": False}
            continue
        t_last = idx[idx.normalize() == now.normalize()][-1]
        out[s] = {"open": float(today["Open"].iloc[0]),
                  "last": float(today["Close"].iloc[-1]),
                  "time": t_last.isoformat(),
                  "live": now - t_last <= pd.Timedelta(minutes=LIVE_MINUTES),
                  "realtime": False}
    return out


def _line(agent, t: str, last: pd.Timestamp, q: dict | None) -> str:
    """One market's price line for the brief, with today's move if any."""
    history = agent._price_line(t, last)
    if not q or q.get("open") is None:
        return "not trading today so far; up to the last close: " + history
    prev = float(agent.market.close_panel.at[last, t])
    move = q["last"] / prev - 1 if prev else 0.0
    state = ("market closed now" if not q["live"] else
             "market open now, real-time price" if q.get("realtime") else
             "market open now, price about 15 minutes old")
    return (f"now {q['last']:.2f} {agent.market.currencies[t]} "
            f"({move:+.1%} today, {state}); up to the last close: {history}")


def midday_check(sim: Simulator, now: pd.Timestamp, quotes: dict,
                 fx_now: dict[str, float], key: str = "news",
                 fx_open: dict[str, float] | None = None) -> dict:
    """Run one news agent's midday check on a restored simulator.

    ``quotes`` comes from :func:`intraday_quotes` (and Finnhub, whose
    quotes are marked ``realtime``); ``fx_now`` maps a currency to the CHF
    value of one unit right now, ``fx_open`` the same at today's first
    price (for last evening's orders, which filled this morning); ``key``
    picks the agent (``"news"`` or ``"news_opus"``).
    """
    acc = next((a for a in sim.accounts if agent_key(a.agent) == key), None)
    if acc is None:
        return {"ok": False, "status": f"No {key} account yet"}
    agent, pf, broker = acc.agent, acc.portfolio, acc.broker
    market, last = sim.market, sim.last_date
    day = now.tz_convert("UTC").tz_localize(None).normalize()
    if day <= last:
        raise ValueError("the midday check is for a session after the last close")

    def fx(t: str) -> float:
        ccy = market.currencies[t]
        if ccy == config.BASE_CURRENCY:
            return 1.0
        return fx_now.get(ccy) or market.fx_rate(t, last, "Close")

    def fx_morning(t: str) -> float:
        # Last evening's orders filled this morning: at the morning's rate,
        # as the evening run fills its orders at the day's opening rate.
        ccy = market.currencies[t]
        return (fx_open or {}).get(ccy) or fx(t)

    def jumped(t: str) -> bool:
        q, close = quotes.get(t) or {}, market.close_panel.at[last, t]
        move = (q.get("last") or math.nan) / close
        return math.isfinite(move) and not SPLIT_LIKE[0] <= move <= SPLIT_LIKE[1]

    def opened(t: str) -> bool:
        return (quotes.get(t) or {}).get("open") is not None and not jumped(t)

    def live(t: str) -> bool:
        return bool((quotes.get(t) or {}).get("live")) and not jumped(t)

    def realtime(t: str) -> bool:
        return live(t) and bool(quotes[t].get("realtime"))

    # 1. Last evening's orders filled at this morning's open (minus any
    #    replaced by a newer one or waiting too long, as in the evening).
    #    Close orders from an earlier check today (a manual re-run) give
    #    way to this one's decisions.
    broker._tidy(day)
    for o in [o for o in broker.pending if o.kind == "close"]:
        broker.pending.remove(o)
        broker._reject(o, "replaced by a newer order")
    fills = []
    due = sorted((o for o in broker.pending if opened(o.ticker)),
                 key=lambda o: o.side != "SELL")
    broker.pending = [o for o in broker.pending if not opened(o.ticker)]
    for o in due:
        f = broker.fill_at(o, day, quotes[o.ticker]["open"],
                           fx_morning(o.ticker))
        if f is not None:
            fills.append(f)
    opening = list(fills)

    # 2. The account at live prices.
    def price(t: str) -> float:
        q = quotes.get(t)
        if opened(t) and math.isfinite(q["last"]):
            return q["last"]
        return float(market.close_panel.at[last, t])

    equity = pf.cash + sum(p.quantity * price(t) * fx(t)
                           for t, p in pf.positions.items())
    holdings = {t: p.quantity * price(t) * fx(t) / equity
                for t, p in pf.positions.items()}
    before = ", ".join(f"{t} {v['weight']:.0%}"
                       for t, v in agent.targets.items() if v["weight"] > 0)
    note = (
        f"MIDDAY CHECK, {now.strftime('%H:%M')} UTC. Prices are live (some about "
        "15 minutes old). A change in a market with a real-time price fills "
        "at once; in one whose price is about 15 minutes old it fills at "
        "today's closing price; in a closed market it waits for this "
        "evening's check.\n"
        f"Your targets from the last evening check: {before or 'none'}.\n"
        "Keep those targets unless today's news or price moves give a clear "
        "reason to change. Reply in the same JSON format, listing every "
        "market you want to hold.")
    lines = {t: _line(agent, t, last, quotes.get(t)) for t in agent.indicators}

    # 3. Ask Claude. The evening status stays; the midday one is separate.
    evening_status = agent.status
    ok = agent.consult(lines, holdings, pf.cash / equity, note)
    status = (f"Checked with {agent.model_used}" if ok else
              agent.status.replace("No decision today", "Midday check failed"))
    agent.status = evening_status

    # 4. Trade the changes in markets that are open now: at once where the
    #    price is real-time, at today's close where it is delayed.
    signals = agent.target_signals(pf) if ok else []
    orders, waiting, at_close = [], [], []
    costs = pf.costs
    # Estimated proceeds of sells at the close; only buys at the same close
    # can use them (those fill after the sells).
    proceeds = 0.0
    for sig in (s for s in signals if s.action is Action.SELL):
        t = sig.ticker
        if not live(t):
            waiting.append(t)
            continue
        if not realtime(t):
            qty = pf.quantity(t)
            o = Order(t, "SELL", qty, day, sig.reason, kind="close")
            broker.submit(o)
            proceeds += (qty * costs.sell_price_chf(price(t), fx(t),
                                                    market.currencies[t])
                         - costs.commission_chf)
            orders.append(o)
            at_close.append(t)
            continue
        o = Order(t, "SELL", pf.quantity(t), day, sig.reason)
        f = broker.fill_at(o, day, price(t), fx(t))
        if f is not None:
            orders.append(o)
            fills.append(f)
    # Cash promised to orders still waiting for their market stays theirs.
    promised = agent.waiting_buys(broker, last, costs)
    budget = pf.cash * (1.0 - config.CASH_BUFFER_PCT) - sum(promised.values())
    buys = sorted((s for s in signals if s.action is Action.BUY),
                  key=lambda s: s.score, reverse=True)
    for sig in buys:
        t = sig.ticker
        if not live(t):
            waiting.append(t)
            continue
        budget += promised.pop(t, 0.0)        # this order replaces it
        closing = not realtime(t)
        unit = costs.buy_price_chf(price(t), fx(t), market.currencies[t])
        qty = agent.position_size(sig, day, equity, unit)
        free = budget + (proceeds if closing else 0.0)
        qty = min(qty, int(max(free - costs.commission_chf, 0) // unit))
        if qty <= 0 or qty * unit < config.MIN_ORDER_CHF:
            continue
        if closing:
            # Cash is checked again at the close; until then it is promised.
            o = Order(t, "BUY", qty, day, sig.reason, kind="close")
            broker.submit(o)
            cost = qty * unit + costs.commission_chf
            used = min(cost, proceeds)
            proceeds -= used
            budget -= cost - used
            orders.append(o)
            at_close.append(t)
            continue
        o = Order(t, "BUY", qty, day, sig.reason)
        f = broker.fill_at(o, day, price(t), fx(t))
        if f is not None:
            budget -= f.gross_chf + f.commission_chf
            orders.append(o)
            fills.append(f)

    if signals or fills:
        entry = _activity(day, signals, orders, fills,
                          decision_context(agent, signals, day, pf))
        entry["time"] = "midday"
        for f in entry["fills"][:len(opening)]:
            f["at_open"] = True               # last evening's orders
        for s in entry["signals"]:
            if s["ticker"] in waiting:
                s["note"] = "market closed now, left for the evening"
            elif s["ticker"] in at_close:
                s["note"] = ("price about 15 minutes old: ordered for "
                             "today's close")
        acc.activity.append(entry)

    agent.midday = {
        "time": now.tz_convert("UTC").isoformat(timespec="minutes"),
        "ok": ok, "status": status, "view": agent.view if ok else "",
        "opening_fills": len(opening), "trades": len(orders) - len(at_close),
        "at_close": at_close, "waiting": waiting,
    }
    logger.info("Midday: %s; %d opening fill(s), %d trade(s) at once, "
                "%d ordered for the close, %d left for the evening", status,
                len(opening), len(orders) - len(at_close), len(at_close),
                len(waiting))
    return agent.midday


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, default=config.PAPER_STATE_FILE)
    parser.add_argument("--dashboard", type=Path,
                        default=config.DASHBOARD_DATA_DIR / "paper.json")
    parser.add_argument("--start", default=config.PAPER_START_DATE)
    parser.add_argument("--dry-run", action="store_true",
                        help="run the check but save nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    now = pd.Timestamp.now(tz="UTC")
    ny = now.tz_convert("America/New_York")
    cutoff = last_completed_session(now)
    if ny.weekday() >= 5 or cutoff.date() == ny.date():
        logger.info("Not a trading day, or New York has closed: the evening "
                    "run takes it from here")
        return
    if not args.state.exists():
        logger.info("No paper accounts yet")
        return
    saved = json.loads(args.state.read_text())
    start = pd.Timestamp(args.start)
    market = load_for_state(saved, "yfinance", start, cutoff)
    if saved.get("last_date") != market.calendar[-1].strftime("%Y-%m-%d"):
        logger.warning("The evening run has not caught up (state at %s, last "
                       "session %s): skipping the midday check",
                       saved.get("last_date"), market.calendar[-1].date())
        return
    sim = Simulator.from_dict(saved, market)

    currencies = sorted(set(market.currencies.values()) - {config.BASE_CURRENCY})
    fx_symbols = {c: config.FX_TICKERS[c] for c in currencies}
    try:
        quotes = intraday_quotes(market.tickers + list(fx_symbols.values()),
                                 now)
    except Exception as exc:
        logger.warning("Yahoo live prices failed: %s", exc)
        quotes = {}
    source = "Yahoo (about 15 minutes delayed)"
    if finnhub_feed.api_key():
        # Real-time US prices from Finnhub; Yahoo stays the backup.
        us = [t for t in market.tickers if t in config._US_STOCKS
              or t in config._FUNDS]
        live_us = finnhub_feed.quotes(us, now, LIVE_MINUTES)
        quotes.update({t: {**q, "realtime": True} for t, q in live_us.items()})
        logger.info("Finnhub real-time prices for %d of %d US markets",
                    len(live_us), len(us))
        if live_us:
            source = (f"Finnhub real-time for {len(live_us)} US markets, "
                      "Yahoo (about 15 minutes delayed) for the rest")
    if not any(q["live"] for t, q in quotes.items() if t in market.currencies):
        logger.warning("No market is trading right now: skipping")
        return
    fx_now = {c: quotes[s]["last"] for c, s in fx_symbols.items()
              if s in quotes}
    fx_open = {c: quotes[s]["open"] for c, s in fx_symbols.items()
               if s in quotes and quotes[s]["open"]}
    logger.info("Live quotes for %d markets, %d trading now",
                len(quotes), sum(q["live"] for q in quotes.values()))

    for key in NEWS_KEYS:
        result = midday_check(sim, now, quotes, fx_now, key, fx_open)
        result["prices"] = source
        print(key, json.dumps(result, indent=2))
    if args.dry_run:
        logger.info("Dry run: nothing saved")
        return
    write_json(sim.to_dict(), args.state)
    # The evening run's prices of the IBKR stand-in funds stay.
    old = json.loads(args.dashboard.read_text()) if args.dashboard.exists() else {}
    write_json(dashboard_payload(sim, "paper", start, {
        "status": "live", "stand_ins": old.get("stand_ins", {})}),
        args.dashboard)


if __name__ == "__main__":
    main()
