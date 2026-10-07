/* Simulation layer · market data and feature engineering.
 *
 * Loads real end-of-day closes exported by the Python engine
 * (docs/data/backtest.json, written by `python main.py --dashboard`) and
 * converts them to CHF with the exported USD/CHF series. If that file is
 * not reachable (for example when index.html is opened from disk) a
 * synthetic regime-switching market is generated instead and the System
 * Health panel says so.
 *
 * To feed your own data, return the same shape from V3.Market.load():
 *   { source, tickers, series: { TICKER: { dates: [...], close: Float64Array } } }
 */
(function () {
  "use strict";
  const V3 = window.V3;

  async function fetchFirst(urls) {
    for (const u of urls) {
      try {
        const r = await fetch(u, { cache: "no-store" });
        if (r.ok) return await r.json();
      } catch { /* try the next location */ }
    }
    return null;
  }

  function fromExport(json) {
    const fxPairs = (json.fx && json.fx.USD) || [];
    const fx = new Map(fxPairs);
    let lastFx = fxPairs.length ? fxPairs[0][1] : 1;
    const series = {};
    for (const [ticker, pairs] of Object.entries(json.prices || {})) {
      if (pairs.length < 400) continue;
      const ccy = (json.currencies || {})[ticker] || "USD";
      const dates = [], close = new Float64Array(pairs.length);
      pairs.forEach(([d, v], i) => {
        if (fx.has(d)) lastFx = fx.get(d);
        dates.push(d);
        close[i] = ccy === "CHF" ? v : v * (fxPairs.length ? lastFx : 1);
      });
      series[ticker] = { dates, close };
    }
    return {
      source: "historical", fxLoaded: fxPairs.length > 0,
      tickers: Object.keys(series), series,
      first: json.start, last: json.last,
    };
  }

  function synthetic() {
    const rnd = V3.rng(7), tickers = ["SYN-A", "SYN-B", "SYN-C", "SYN-D", "SYN-E"];
    const series = {}, n = 1300, start = Date.UTC(2021, 0, 4);
    const dates = [];
    for (let i = 0, d = start; dates.length < n; d += 864e5) {
      const wd = new Date(d).getUTCDay();
      if (wd !== 0 && wd !== 6) dates.push(new Date(d).toISOString().slice(0, 10));
      i++;
    }
    const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
    tickers.forEach((t, k) => {
      const close = new Float64Array(n);
      let p = 50 + 150 * rnd(), drift = 0, vol = 0.012 + 0.01 * rnd();
      for (let i = 0; i < n; i++) {
        if (i % 60 === 0) { drift = [0.0011, -0.0009, 0.0001][Math.floor(rnd() * 3)]; vol = 0.008 + 0.018 * rnd(); }
        p *= Math.exp(drift + vol * gauss());
        close[i] = p;
      }
      series[t] = { dates, close };
    });
    return { source: "synthetic", fxLoaded: false, tickers, series, first: dates[0], last: dates[n - 1] };
  }

  // ------------------------------------------------------------ features --
  V3.FEATURES = [
    { key: "ret1", label: "1-day return" },
    { key: "ret5", label: "5-day momentum" },
    { key: "ret20", label: "20-day momentum" },
    { key: "emaGap", label: "Price vs EMA20" },
    { key: "trend", label: "EMA20 vs EMA50 trend" },
    { key: "rsi", label: "RSI(14)" },
    { key: "vol", label: "20-day volatility" },
    { key: "volRatio", label: "Volatility vs 100-day" },
    { key: "dd60", label: "Drop from 60-day high" },
    { key: "z20", label: "20-day z-score" },
  ];

  function ema(x, n) {
    const out = new Float64Array(x.length), a = 2 / (n + 1);
    out[0] = x[0];
    for (let i = 1; i < x.length; i++) out[i] = a * x[i] + (1 - a) * out[i - 1];
    return out;
  }

  /** Causal features for one series; row i uses closes up to i only. */
  function computeFeatures(close) {
    const n = close.length, F = V3.FEATURES.length;
    const raw = new Float64Array(n * F).fill(NaN);
    const r1 = new Float64Array(n);
    for (let i = 1; i < n; i++) r1[i] = Math.log(close[i] / close[i - 1]);
    const e20 = ema(close, 20), e50 = ema(close, 50);
    let gain = 0, loss = 0;
    const vol20 = new Float64Array(n).fill(NaN), vol100 = new Float64Array(n).fill(NaN);
    for (let i = 1; i < n; i++) {
      const d = close[i] - close[i - 1];
      gain = (gain * 13 + Math.max(d, 0)) / 14; loss = (loss * 13 + Math.max(-d, 0)) / 14;
      const rsi = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
      if (i >= 20) vol20[i] = std(r1, i - 19, i);
      if (i >= 100) vol100[i] = std(r1, i - 99, i);
      if (i < 100) continue;
      let hi = 0, sum = 0, sq = 0;
      for (let j = i - 59; j <= i; j++) hi = Math.max(hi, close[j]);
      for (let j = i - 19; j <= i; j++) { sum += close[j]; sq += close[j] * close[j]; }
      const m = sum / 20, sd = Math.sqrt(Math.max(sq / 20 - m * m, 1e-12));
      const row = [r1[i], Math.log(close[i] / close[i - 5]), Math.log(close[i] / close[i - 20]),
        close[i] / e20[i] - 1, e20[i] / e50[i] - 1, (rsi - 50) / 50, vol20[i],
        vol20[i] / vol100[i] - 1, close[i] / hi - 1, (close[i] - m) / sd];
      for (let f = 0; f < F; f++) raw[i * F + f] = row[f];
    }
    return { raw, vol20, e20, e50 };
  }

  function std(x, a, b) {
    let s = 0, q = 0; const n = b - a + 1;
    for (let i = a; i <= b; i++) { s += x[i]; q += x[i] * x[i]; }
    return Math.sqrt(Math.max(q / n - (s / n) ** 2, 0));
  }

  /** Scale every feature by its spread over the training period only. */
  function standardise(market) {
    const F = V3.FEATURES.length, mean = new Float64Array(F), sd = new Float64Array(F), cnt = new Float64Array(F);
    for (const t of market.tickers) {
      const s = market.series[t];
      for (let i = 0; i < s.trainEnd; i++) for (let f = 0; f < F; f++) {
        const v = s.feat.raw[i * F + f]; if (!isFinite(v)) continue;
        mean[f] += v; sd[f] += v * v; cnt[f]++;
      }
    }
    for (let f = 0; f < F; f++) { mean[f] /= cnt[f]; sd[f] = Math.sqrt(sd[f] / cnt[f] - mean[f] ** 2) || 1; }
    for (const t of market.tickers) {
      const s = market.series[t], n = s.close.length;
      s.z = new Float64Array(n * F);
      for (let i = 0; i < n * F; i++) {
        const f = i % F, v = (s.feat.raw[i] - mean[f]) / sd[f];
        s.z[i] = isFinite(v) ? Math.max(-3, Math.min(3, v)) : NaN;
      }
    }
  }

  /** Regime of one series at index i: trend strength and volatility level. */
  V3.regimeAt = function (s, i) {
    const trend = Math.abs(s.feat.e20[i] / s.feat.e50[i] - 1);
    const volR = s.feat.vol20[i] / (s.volMedian || s.feat.vol20[i]);
    const trending = trend > 0.025;
    const vol = volR > 1.35 ? "High volatility" : volR < 0.75 ? "Low volatility" : "Normal volatility";
    return { trend: trending ? "Trending" : "Range-bound", vol, volRatio: volR, trendStrength: trend,
      label: (trending ? "Trending" : "Range-bound") + " · " + vol };
  };

  V3.Market = {
    async load() {
      const json = await fetchFirst(V3.config.dataUrls);
      const m = json && json.prices ? fromExport(json) : synthetic();
      for (const t of m.tickers) {
        const s = m.series[t];
        s.feat = computeFeatures(s.close);
        s.start = 101;                                       // first fully-featured bar
        s.trainEnd = Math.max(s.start + 200, s.close.length - V3.config.validationDays);
        const v = Array.from(s.feat.vol20.slice(s.start, s.trainEnd)).filter(isFinite).sort((a, b) => a - b);
        s.volMedian = v[Math.floor(v.length / 2)];
      }
      standardise(m);
      return m;
    },
  };
})();
