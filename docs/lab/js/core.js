/* Vanguard3 Lab: shared namespace, event bus, configuration and helpers.
 *
 * Every layer talks through V3.bus so the 3D view, the panels and the
 * simulation never call each other directly. To plug in a real model,
 * emit the same events (see EVENTS below) from your own source.
 */
(function () {
  "use strict";
  const V3 = (window.V3 = window.V3 || {});

  // ---------------------------------------------------------------- bus --
  const handlers = {};
  V3.bus = {
    on(evt, fn) { (handlers[evt] = handlers[evt] || []).push(fn); return () => this.off(evt, fn); },
    off(evt, fn) { handlers[evt] = (handlers[evt] || []).filter(f => f !== fn); },
    emit(evt, data) { (handlers[evt] || []).forEach(fn => { try { fn(data); } catch (e) { console.error(evt, e); } }); },
  };

  /** Event contract between the simulation (or your model) and the UI. */
  V3.EVENTS = {
    READY: "ready",          // {market}               data loaded, warm-up done
    STEP: "step",            // {state}                every simulated session
    DECISION: "decision",    // {decision}             a full pipeline pass to animate
    TRADE: "trade",          // {trade}                a position opened or closed
    EPISODE: "episode",      // {episode}              an episode finished
    MODEL: "model",          // {version}              new model version saved
    RISK: "risk",            // {event}                risk manager intervention
    REGIME: "regime",        // {regime}               regime changed
    STATUS: "status",        // {running, speed}       play / pause / speed
    BACKTEST: "backtest",    // {result}               backtest finished
  };

  // ------------------------------------------------------------- config --
  V3.config = {
    capital: 100000,          // simulated CHF per episode
    commission: 2,            // CHF per fill (Interactive Brokers style)
    slippageBps: 5,
    episodeLength: 120,       // trading days per training episode
    validationDays: 252,      // most recent year is held out for validation
    versionEvery: 20,         // episodes between model versions
    warmupEpisodes: 120,       // trained silently before the UI starts
    dataUrls: ["../data/backtest.json", "data/backtest.json"],
  };

  /** Component graph. `cat` drives colour; `size` the sphere radius. */
  V3.NODES = [
    { id: "data", name: "Market Data", cat: "data", size: 6,
      desc: "End-of-day prices replayed from the Vanguard3 history, converted to CHF." },
    { id: "features", name: "Feature Engineering", cat: "process", size: 6,
      desc: "Turns prices into 10 standardised signals: momentum, trend, RSI, volatility, drawdown." },
    { id: "strategy", name: "Strategy Engine", cat: "process", size: 6,
      desc: "Rule-based context: trend filter and market-regime classifier feeding the agent." },
    { id: "agent", name: "AI Trading Agent", cat: "core", size: 15,
      desc: "Linear Q-learning agent. Scores BUY / HOLD / SELL from the features and picks one (epsilon-greedy while training)." },
    { id: "risk", name: "Risk Manager", cat: "risk", size: 6.5,
      desc: "Sizes positions by volatility, sets stops, and blocks or shrinks trades when drawdown rises." },
    { id: "exec", name: "Execution Simulator", cat: "exec", size: 6,
      desc: "Simulated fills with slippage and a flat 2 CHF fee. Never sends real orders." },
    { id: "portfolio", name: "Portfolio", cat: "exec", size: 6.5,
      desc: "Simulated cash, position, equity and drawdown for the current episode." },
    { id: "backtest", name: "Backtesting", cat: "research", size: 6,
      desc: "Replays any saved model version over a chosen asset and date range." },
    { id: "reward", name: "Reward / P&L", cat: "learn", size: 6,
      desc: "Reward = next-session equity change (in %) minus 0.02 per trade and 2× any increase in drawdown." },
    { id: "learning", name: "Learning System", cat: "learn", size: 7,
      desc: "Temporal-difference updates of the agent's weights; validates and versions the model." },
    { id: "monitor", name: "Performance Monitor", cat: "monitor", size: 6,
      desc: "Tracks reward, win rate, drawdown and validation results across episodes." },
  ];

  V3.LINKS = [
    ["data", "features"], ["features", "strategy"], ["features", "agent"], ["strategy", "agent"],
    ["agent", "risk"], ["risk", "exec"], ["exec", "portfolio"], ["portfolio", "reward"],
    ["reward", "learning"], ["learning", "agent"], ["portfolio", "monitor"], ["reward", "monitor"],
    ["learning", "monitor"], ["data", "backtest"], ["learning", "backtest"], ["backtest", "monitor"],
    ["portfolio", "risk"],
  ];

  /** The 9 visible stages of one decision, as hops through the graph. */
  V3.PIPELINE = [
    { key: "data", label: "Data", hops: [["data", "features"]] },
    { key: "features", label: "Features", hops: [["features", "agent"], ["features", "strategy"]] },
    { key: "analyse", label: "Analyse", hops: [["strategy", "agent"]], pulse: "agent" },
    { key: "decide", label: "Decide", hops: [], pulse: "agent" },
    { key: "risk", label: "Risk", hops: [["agent", "risk"]], pulse: "risk" },
    { key: "exec", label: "Execute", hops: [["risk", "exec"]] },
    { key: "portfolio", label: "Portfolio", hops: [["exec", "portfolio"]] },
    { key: "reward", label: "Reward", hops: [["portfolio", "reward"]] },
    { key: "learn", label: "Learn", hops: [["reward", "learning"], ["learning", "agent"]], pulse: "learning" },
  ];

  V3.CAT_COLORS = {
    data: "#7fa7d9", process: "#8f97c4", core: "#e8e4dc", risk: "#e27466",
    exec: "#6cc391", research: "#9aa7b8", learn: "#a99bd6", monitor: "#74b9aa",
  };
  V3.ACTION_COLORS = { BUY: "#6cc391", SELL: "#e27466", HOLD: "#8b9097" };

  // ------------------------------------------------------------ helpers --
  V3.fmt = {
    chf: v => v == null || !isFinite(v) ? "–" : new Intl.NumberFormat("de-CH", { maximumFractionDigits: 0 }).format(v),
    chf2: v => v == null || !isFinite(v) ? "–" : new Intl.NumberFormat("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v),
    pct: (v, d = 1) => v == null || !isFinite(v) ? "–" : (v >= 0 ? "+" : "") + (v * 100).toFixed(d) + "%",
    pctU: (v, d = 0) => v == null || !isFinite(v) ? "–" : (v * 100).toFixed(d) + "%",
    num: (v, d = 2) => v == null || !isFinite(v) ? "–" : v.toFixed(d),
    px: v => v == null || !isFinite(v) ? "–" : v >= 1000 ? v.toFixed(0) : v.toFixed(2),
    date: s => s ? new Date(s + "T00:00:00Z").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }) : "–",
    time: d => d.toLocaleTimeString("en-GB", { hour12: false }),
  };
  V3.esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** Seeded PRNG so a run is reproducible when needed. */
  V3.rng = function (seed) {
    let s = seed >>> 0 || 1;
    return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 1e9) / 1e9; };
  };
  V3.store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* unavailable */ } },
  };
})();
