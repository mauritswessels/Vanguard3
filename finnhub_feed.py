"""Finnhub (finnhub.io): real-time US prices and company news.

Used only when the ``FINNHUB_API_KEY`` repository secret is set:

* the midday check takes live US prices from here (Yahoo's are about 15
  minutes behind, and stay the backup),
* the News Analyst's brief adds each US company's latest news.

The free plan allows about 60 requests a minute, so calls are spaced out.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

logger = logging.getLogger("vanguard3.finnhub")

BASE = "https://finnhub.io/api/v1/"
#: Seconds between requests, to stay under the free plan's limit.
SPACING = 1.05
_last_call = 0.0


def api_key() -> str | None:
    return os.environ.get("FINNHUB_API_KEY") or None


def _get(path: str, **params) -> object:
    global _last_call
    key = api_key()
    if not key:
        raise RuntimeError("FINNHUB_API_KEY is not set")
    wait = _last_call + SPACING - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    url = BASE + path + "?" + urllib.parse.urlencode({**params, "token": key})
    req = urllib.request.Request(url, headers={"User-Agent": "vanguard3"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def parse_quote(raw: dict, now: pd.Timestamp, live_minutes: int) -> dict | None:
    """Finnhub's quote (c = current, o = today's open, t = time) in the
    same shape as ``midday_news.intraday_quotes``."""
    if not raw or not raw.get("c") or not raw.get("t"):
        return None
    when = pd.Timestamp(int(raw["t"]), unit="s", tz="UTC")
    if when.normalize() != now.normalize() or not raw.get("o"):
        return {"open": None, "last": float(raw["c"]), "time": None,
                "live": False}
    return {"open": float(raw["o"]), "last": float(raw["c"]),
            "time": when.isoformat(),
            "live": now - when <= pd.Timedelta(minutes=live_minutes)}


def quotes(tickers: list[str], now: pd.Timestamp,
           live_minutes: int) -> dict[str, dict]:
    """Live quotes for US tickers; a ticker that fails is left out."""
    out = {}
    for t in tickers:
        try:
            q = parse_quote(_get("quote", symbol=t), now, live_minutes)
        except Exception as exc:
            logger.warning("Finnhub quote for %s failed: %s", t, exc)
            continue
        if q is not None:
            out[t] = q
    return out


def company_news(ticker: str, limit: int = 3, days: int = 2) -> list[str]:
    """Latest headlines for a US company ("date · source · title")."""
    today = pd.Timestamp.now(tz="UTC")
    raw = _get("company-news", symbol=ticker,
               **{"from": (today - pd.Timedelta(days=days)).strftime("%Y-%m-%d"),
                  "to": today.strftime("%Y-%m-%d")})
    items = sorted((i for i in raw or [] if i.get("headline")),
                   key=lambda i: i.get("datetime", 0), reverse=True)
    out = []
    for i in items[:limit]:
        when = pd.Timestamp(int(i.get("datetime", 0)), unit="s").strftime("%d %b")
        out.append(f"{when} · {i.get('source', 'Finnhub')} · "
                   f"{i['headline'].strip()}"[:220])
    return out
