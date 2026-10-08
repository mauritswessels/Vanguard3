/* Vanguard3 metrics: the one place the dashboard computes performance and
   risk numbers. Every view (leaderboard, risk, performance, agent vs agent,
   overview) calls these functions on the same data, so a number can never
   differ between two parts of the page.

   Inputs are the paper.json written by reporting.py: per account the daily
   equity curve (closing values), every fill (with fees and the portfolio's
   own realised P&L), positions grouped into round trips ("trips"), current
   positions and cash. Nothing here invents or smooths data.

   The return, volatility, Sharpe and drawdown formulas match
   engine/metrics.py exactly (risk-free 0.5% a year, 252 trading days,
   sample standard deviation); for "All time" they give the same values as
   the Python scoreboard. Works in the browser (window.V3Metrics) and in
   Node (for checks). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.V3Metrics = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const RF = 0.005, PERIODS = 252;
  /** Below this many daily returns, volatility and Sharpe are not shown. */
  const MIN_RETURNS = 20;
  /** Risk warning thresholds (shown on the page next to each warning). */
  const LIMITS = { concentration: 0.25, drawdown: -0.10, volMultiple: 1.5, lowCash: 0.02 };

  const DAY = 864e5;
  const iso = ms => new Date(ms).toISOString().slice(0, 10);
  const addDays = (s, n) => iso(Date.parse(s + "T00:00:00Z") + n * DAY);
  const inRange = (date, r) => (!r.from || date >= r.from) && (!r.to || date <= r.to);
  const sum = xs => xs.reduce((a, b) => a + b, 0);
  const mean = xs => xs.length ? sum(xs) / xs.length : NaN;
  function std(xs) {                       // sample standard deviation (ddof 1)
    if (xs.length < 2) return NaN;
    const m = mean(xs);
    return Math.sqrt(sum(xs.map(x => (x - m) ** 2)) / (xs.length - 1));
  }

  // ---------- time ranges ----------
  const RANGES = [
    ["today", "Today"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All time"], ["custom", "Custom"],
  ];

  /** {from, to, label}: inclusive ISO dates, null = open-ended. "Today" is
   *  the latest session; values are recorded once per trading day, so the
   *  last 24 hours and today are the same window. */
  function range(kind, d, custom) {
    const last = d.last;
    switch (kind) {
      case "today": return { kind, from: last, to: null, label: "the latest session" };
      case "7d": return { kind, from: addDays(last, -6), to: null, label: "the last 7 days" };
      case "30d": return { kind, from: addDays(last, -29), to: null, label: "the last 30 days" };
      case "custom": {
        const from = custom && custom.from || null, to = custom && custom.to || null;
        return { kind, from, to: to && to < last ? to : null,
          label: `${from || "launch"} to ${to && to < last ? to : "now"}` };
      }
      default: return { kind: "all", from: null, to: null, label: "all time" };
    }
  }
  const toLatest = r => !r.to;

  // ---------- equity windows ----------
  /** The curve inside the range plus its base: the last close before the
   *  range starts (no look-ahead), or the starting capital. */
  function windowOf(a, d, r) {
    const before = r.from ? a.equity.filter(p => p[0] < r.from) : [];
    const pts = a.equity.filter(p => inRange(p[0], r));
    const base = before.length ? before[before.length - 1] : null;
    return { base: base ? base[1] : d.initial_capital_chf, baseDate: base ? base[0] : null, pts };
  }

  function returnsOf(w) {
    const vals = [w.base, ...w.pts.map(p => p[1])], out = [];
    for (let i = 1; i < vals.length; i++) out.push(vals[i] / vals[i - 1] - 1);
    return out;
  }

  function sharpe(rets) {
    if (rets.length < 2) return NaN;
    const ex = rets.map(r => r - RF / PERIODS), s = std(ex);
    return !isFinite(s) || s < 1e-12 ? NaN : mean(ex) / s * Math.sqrt(PERIODS);
  }

  function drawdowns(vals) {
    let peak = -Infinity;
    return vals.map(v => { peak = Math.max(peak, v); return v / peak - 1; });
  }

  // ---------- the book right now (last close) ----------
  function book(a) {
    const invested = sum(a.positions.map(p => p.value_chf));
    const value = a.cash_chf + invested;
    const weights = a.positions.map(p => p.value_chf / value);
    const top = a.positions.slice().sort((x, y) => y.value_chf - x.value_chf)[0] || null;
    return {
      value, cash: a.cash_chf, invested,
      cashPct: a.cash_chf / value,
      exposure: invested / value,                        // long only: gross = net = long
      open: a.positions.length,
      largest: top ? { ticker: top.ticker, pct: top.value_chf / value } : null,
      // 1 / sum of squared weights: how many equal positions the book is worth.
      effective: weights.length ? 1 / sum(weights.map(w => w * w)) : null,
      unrealized: sum(a.positions.map(p => p.pnl_chf)),
    };
  }

  /** Share of the account invested at each close: cash at a close is the
   *  starting cash plus every fill up to that day (fills happen before the
   *  close), the rest of the equity is positions. */
  function exposureSeries(a, d, r) {
    const fills = a.trades.slice().sort((x, y) => x.date < y.date ? -1 : 1);
    let i = 0, cash = d.initial_capital_chf;
    return a.equity.filter(p => !r.to || p[0] <= r.to).map(([date, eq]) => {
      while (i < fills.length && fills[i].date <= date) cash += fills[i++].cash_flow_chf;
      return [date, Math.max(0, 1 - cash / eq)];
    }).filter(p => inRange(p[0], r));
  }

  // ---------- trips (positions from first buy to last sell) ----------
  const tripsClosedIn = (a, r) => (a.trips || []).filter(t => t.status === "closed" && inRange(t.exit_date, r));
  /** Positions that were open at some point inside the range. */
  const tripsTouching = (a, r) => (a.trips || []).filter(t =>
    (!r.to || t.entry_date <= r.to) && (t.status === "open" || !r.from || t.exit_date >= r.from));

  function tradeStats(closed) {
    const wins = closed.filter(t => t.pnl_chf > 0), losses = closed.filter(t => t.pnl_chf < 0);
    const gw = sum(wins.map(t => t.pnl_chf)), gl = -sum(losses.map(t => t.pnl_chf));
    const best = closed.slice().sort((x, y) => y.pnl_chf - x.pnl_chf);
    return {
      closed: closed.length,
      winRate: closed.length ? wins.length / closed.length : NaN,
      avgWin: wins.length ? gw / wins.length : NaN,
      avgWinPct: wins.length ? mean(wins.map(t => t.pnl_pct)) : NaN,
      avgLoss: losses.length ? -gl / losses.length : NaN,
      avgLossPct: losses.length ? mean(losses.map(t => t.pnl_pct)) : NaN,
      profitFactor: losses.length ? gw / gl : (wins.length ? Infinity : NaN),
      largestGain: wins.length ? best[0] : null,
      largestLoss: losses.length ? best[best.length - 1] : null,
      avgHoldDays: closed.length ? mean(closed.map(t => t.holding_days)) : NaN,
    };
  }

  // ---------- everything for one account ----------
  function stats(a, d, r) {
    const w = windowOf(a, d, r), rets = returnsOf(w);
    const vals = [w.base, ...w.pts.map(p => p[1])];
    const end = vals[vals.length - 1], dd = drawdowns(vals);
    const fills = a.trades.filter(t => inRange(t.date, r));
    const b = book(a), trips = tripsTouching(a, r);
    const exp = exposureSeries(a, d, r);
    const days = w.pts.length ? Math.max(1, (Date.parse(w.pts[w.pts.length - 1][0]) - Date.parse(w.baseDate || w.pts[0][0])) / DAY) : 0;
    const enough = rets.length >= MIN_RETURNS;
    const vol = rets.length > 1 ? std(rets) * Math.sqrt(PERIODS) : NaN;
    return {
      id: a.id, name: a.name, key: a.key,
      start: w.base, startDate: w.baseDate, value: end,
      ret: end / w.base - 1, pnl: end - w.base,
      realized: sum(fills.filter(t => t.side === "SELL").map(t => t.pnl_chf)),
      // Open positions are only valued at the latest close.
      unrealized: toLatest(r) ? b.unrealized : null,
      fees: sum(fills.map(t => t.fees_chf)),
      fills: fills.length, buys: fills.filter(t => t.side === "BUY").length,
      sells: fills.filter(t => t.side === "SELL").length,
      returns: rets.length, enough,
      vol, sharpe: sharpe(rets),
      maxDD: Math.min(...dd), curDD: dd[dd.length - 1],
      ...tradeStats(tripsClosedIn(a, r)),
      avgSize: mean((a.trips || []).filter(t => inRange(t.entry_date, r)).map(t => t.size_pct)),
      avgExposure: mean(exp.map(p => p[1])),
      perWeek: days ? fills.length / (days / 7) : NaN,
      trips: trips.length,
      book: b,
    };
  }

  function all(d, r) { return d.agents.map(a => stats(a, d, r)); }

  // ---------- chart series ----------
  /** [[date, y]] for the chart: "value" in CHF, "return" vs the range base,
   *  "pnl" in CHF vs the base. Starts at the base so lines share a zero. */
  function curve(a, d, r, mode) {
    const w = windowOf(a, d, r);
    const pts = (w.baseDate ? [[w.baseDate, w.base]] : []).concat(w.pts);
    return pts.map(([t, v]) => [t, mode === "return" ? v / w.base - 1 : mode === "pnl" ? v - w.base : v]);
  }

  function drawdownCurve(a, d, r) {
    const w = windowOf(a, d, r);
    const pts = (w.baseDate ? [[w.baseDate, w.base]] : []).concat(w.pts);
    const dd = drawdowns(pts.map(p => p[1]));
    return pts.map((p, i) => [p[0], dd[i]]);
  }

  // ---------- assets ----------
  /** Per ticker: fills, realised + open P&L of positions in the range. */
  function assets(a, r) {
    const out = {};
    const row = t => out[t] || (out[t] = { ticker: t, fills: 0, pnl: 0, trips: 0 });
    a.trades.filter(t => inRange(t.date, r)).forEach(t => { row(t.ticker).fills++; });
    tripsClosedIn(a, r).forEach(t => { const x = row(t.ticker); x.pnl += t.pnl_chf; x.trips++; });
    if (toLatest(r)) (a.trips || []).filter(t => t.status === "open").forEach(t => {
      const x = row(t.ticker); x.pnl += t.pnl_chf; x.trips++;
    });
    return Object.values(out);
  }

  /** Current exposure per ticker and per asset group for a set of accounts. */
  function exposure(accts, d) {
    const total = sum(accts.map(a => book(a).value));
    const byAsset = {}, byGroup = {};
    accts.forEach(a => a.positions.forEach(p => {
      byAsset[p.ticker] = (byAsset[p.ticker] || 0) + p.value_chf;
      const g = (d.groups || {})[p.ticker] || "Other";
      byGroup[g] = (byGroup[g] || 0) + p.value_chf;
    }));
    const list = o => Object.entries(o).map(([k, v]) => ({ name: k, chf: v, pct: v / total })).sort((x, y) => y.chf - x.chf);
    const invested = sum(Object.values(byAsset));
    return { total, cash: total - invested, cashPct: (total - invested) / total, long: invested / total, short: 0,
      byAsset: list(byAsset), byGroup: list(byGroup) };
  }

  // ---------- warnings ----------
  /** Warnings from the actual book and curve; each says what triggered it. */
  function alerts(d, r) {
    // The buy-and-hold yardstick is concentrated and fully invested by
    // design, so it is left out of the warnings.
    const S = all(d, r).filter((s, i) => !d.agents[i].benchmark), out = [];
    const vols = S.filter(s => s.enough && isFinite(s.vol) && s.vol > 0).map(s => s.vol).sort((x, y) => x - y);
    S.forEach(s => {
      const b = s.book;
      if (b.largest && b.largest.pct > LIMITS.concentration) out.push({ level: "warn", kind: "High concentration", id: s.id,
        text: `${s.name} has ${(b.largest.pct * 100).toFixed(1)}% of its account in ${b.largest.ticker} (warning above ${LIMITS.concentration * 100}%).` });
      if (s.curDD <= LIMITS.drawdown) out.push({ level: "warn", kind: "High drawdown", id: s.id,
        text: `${s.name} is ${(-s.curDD * 100).toFixed(1)}% below its peak in ${r.label} (warning from ${-LIMITS.drawdown * 100}%).` });
      if (s.enough && vols.length >= 3) {
        const others = vols.filter(v => v !== s.vol), mid = others[Math.floor(others.length / 2)];
        if (mid > 0 && s.vol > LIMITS.volMultiple * mid) out.push({ level: "warn", kind: "High volatility", id: s.id,
          text: `${s.name} swings ${(s.vol * 100).toFixed(1)}% a year, ${(s.vol / mid).toFixed(1)}× the middle of the other accounts (${(mid * 100).toFixed(1)}%).` });
      }
      if (b.open && b.cashPct < LIMITS.lowCash) out.push({ level: "info", kind: "Fully invested", id: s.id,
        text: `${s.name} keeps only ${(b.cashPct * 100).toFixed(1)}% in cash, so new buys have to wait for a sale.` });
    });
    return out;
  }

  // ---------- agent vs agent ----------
  const p1 = v => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
  /** Plain sentences, each one a direct reading of two numbers. */
  function compareSummary(A, B, r) {
    const s = [];
    const better = (x, y) => x > y;
    s.push(`Over ${r.label}, ${A.name} returned ${p1(A.ret)} and ${B.name} ${p1(B.ret)}.`);
    if (A.enough && B.enough && isFinite(A.sharpe) && isFinite(B.sharpe)) {
      const hiRet = A.ret >= B.ret ? A : B, loRet = hiRet === A ? B : A;
      if (loRet.sharpe > hiRet.sharpe && hiRet.ret !== loRet.ret)
        s.push(`${loRet.name} earned less but had the higher Sharpe ratio (${loRet.sharpe.toFixed(2)} vs ${hiRet.sharpe.toFixed(2)}), so more return per unit of day-to-day swings.`);
      else s.push(`${hiRet.name} also had the higher Sharpe ratio (${hiRet.sharpe.toFixed(2)} vs ${loRet.sharpe.toFixed(2)}).`);
      const hv = A.vol >= B.vol ? A : B, lv = hv === A ? B : A;
      if (hv.vol > lv.vol * 1.25) s.push(`${hv.name} was more volatile (${(hv.vol * 100).toFixed(1)}% a year vs ${(lv.vol * 100).toFixed(1)}%).`);
    } else {
      s.push(`Sharpe ratio and volatility need at least ${MIN_RETURNS} trading days in the range (this range has ${Math.min(A.returns, B.returns)}).`);
    }
    if (A.maxDD !== B.maxDD) {
      const deep = A.maxDD < B.maxDD ? A : B, shallow = deep === A ? B : A;
      if (deep.maxDD < 0) s.push(`${deep.name}'s largest drop from a peak was ${p1(deep.maxDD)}, deeper than ${shallow.name}'s ${p1(shallow.maxDD)}.`);
    }
    if (A.closed >= 3 && B.closed >= 3 && A.winRate !== B.winRate) {
      const hw = A.winRate > B.winRate ? A : B, lw = hw === A ? B : A;
      s.push(`${hw.name} won ${Math.round(hw.winRate * 100)}% of its ${hw.closed} closed positions, ${lw.name} ${Math.round(lw.winRate * 100)}% of ${lw.closed}.`);
    } else if (A.closed + B.closed) {
      s.push(`Win rates are not compared yet: ${A.name} closed ${A.closed} position${A.closed === 1 ? "" : "s"} and ${B.name} ${B.closed} (at least 3 each needed).`);
    }
    if (A.fills !== B.fills) {
      const many = A.fills > B.fills ? A : B, few = many === A ? B : A;
      s.push(few.fills ? `${many.name} traded more often: ${many.fills} fills vs ${few.fills}.` : `${many.name} made ${many.fills} fills; ${few.name} made none.`);
    }
    if (isFinite(A.avgSize) && isFinite(B.avgSize) && Math.abs(A.avgSize - B.avgSize) > 0.02) {
      const big = A.avgSize > B.avgSize ? A : B, small = big === A ? B : A;
      s.push(`${big.name} took larger positions (${(big.avgSize * 100).toFixed(1)}% of the account on average vs ${(small.avgSize * 100).toFixed(1)}%).`);
    }
    if (isFinite(A.avgExposure) && isFinite(B.avgExposure) && Math.abs(A.avgExposure - B.avgExposure) > 0.05) {
      const hi = A.avgExposure > B.avgExposure ? A : B, lo = hi === A ? B : A;
      s.push(`${hi.name} kept more of its money invested (${Math.round(hi.avgExposure * 100)}% on average vs ${Math.round(lo.avgExposure * 100)}%).`);
    }
    return s;
  }

  return { RF, PERIODS, MIN_RETURNS, LIMITS, RANGES, range, inRange, windowOf, stats, all, curve, drawdownCurve,
    exposureSeries, book, assets, exposure, alerts, compareSummary, tripsTouching, tripsClosedIn, addDays };
});
