/* Simulation layer · training loop, validation, versions and backtests.
 *
 * Everything here is simulated paper trading on historical prices. No order
 * ever leaves the browser. The engine publishes its state through V3.bus
 * (see V3.EVENTS in core.js); the UI only listens.
 *
 * Connecting your own AI: write an object with the same public surface as
 * V3.Engine (start, pause, setSpeed, state(), backtest(...), versions) that
 * emits the same events from your model's outputs, and pass it to the UI in
 * main.js instead of `new V3.Engine(market)`.
 */
(function () {
  "use strict";
  const V3 = window.V3, E = V3.EVENTS, C = V3.config;

  /** A simulated account trading one asset over a window of sessions. */
  class Run {
    constructor(market, ticker, i0, i1, capital) {
      this.ticker = ticker; this.s = market.series[ticker];
      this.i = i0; this.i0 = i0; this.i1 = i1;
      this.cash = capital; this.capital = capital; this.shares = 0; this.open = null;
      this.peak = capital; this.maxDD = 0; this.rewardSum = 0; this.closed = [];
      this.equity = [[this.s.dates[i0], capital]];
    }
    get done() { return this.i >= this.i1; }
    value(i = this.i) { return this.cash + this.shares * this.s.close[i]; }

    /**
     * Decide at the close of session i, fill at that close (+ slippage),
     * then mark at session i+1 to get the reward. Returns a full record of
     * the pipeline for the UI.
     */
    step(agent, { explore, learn, decide = true, version = "" }) {
      const s = this.s, i = this.i, price = s.close[i];
      const eq0 = this.value(i);
      const dd0 = 1 - eq0 / this.peak;
      const rec = { date: s.dates[i], ticker: this.ticker, price, events: [] };

      // Protective stop from the previous session's risk check.
      if (this.shares > 0 && price <= this.open.stop) {
        this.close(i, price, "Stop hit");
        rec.events.push({ level: "elevated", text: `${this.ticker} stop hit at ${V3.fmt.px(price)}` });
      }

      const phi = agent.phi(s.z, i, this.shares > 0);
      const dec = decide ? agent.act(phi, explore) : { action: 1, name: "HOLD", q: [0, 0, 0], probs: [0, 1, 0], confidence: 1, explored: false };
      const risk = V3.riskCheck(dec, { price, vol: s.feat.vol20[i], position: this.shares > 0, drawdown: dd0 });
      if (risk.event) rec.events.push(risk.event);

      let traded = null;
      if (risk.action === "BUY") {
        const { fill } = V3.execute("BUY", 1, price);
        const shares = Math.floor((eq0 * risk.size - C.commission) / fill);
        if (shares > 0) {
          const ex = V3.execute("BUY", shares, price);
          this.cash -= shares * ex.fill + C.commission;
          this.shares = shares;
          V3._tradeSeq = (V3._tradeSeq || 0) + 1;
          this.open = { id: V3._tradeSeq, ticker: this.ticker,
            entryDate: s.dates[i], entryPrice: ex.fill, shares, size: risk.size, stop: risk.stop,
            confidence: dec.confidence, version, reasons: agent.attribution(phi, dec.action).slice(0, 4),
            reward: 0, status: "open" };
          traded = { side: "BUY", trade: this.open };
        }
      } else if (risk.action === "SELL" && this.shares > 0) {
        traded = { side: "SELL", trade: this.close(i, price, "Agent sold") };
      }

      // Advance one session and score the outcome.
      this.i = i + 1;
      const eq1 = this.value(this.i);
      this.peak = Math.max(this.peak, eq1);
      const dd1 = 1 - eq1 / this.peak;
      this.maxDD = Math.max(this.maxDD, dd1);
      const reward = (eq1 / eq0 - 1) * 100 - (traded ? 0.02 : 0) - Math.max(0, dd1 - dd0) * 2;
      this.rewardSum += reward;
      if (this.open) this.open.reward += reward;
      this.equity.push([s.dates[this.i], eq1]);
      let td = 0;
      if (learn) td = agent.update(phi, dec.action, reward, agent.phi(s.z, this.i, this.shares > 0), this.done);

      return Object.assign(rec, {
        decision: dec, risk, traded, reward, td, equity: eq1, drawdown: dd1,
        features: Array.from(phi.slice(0, V3.FEATURES.length)),
        attribution: agent.attribution(phi, dec.action),
        position: this.shares > 0, exposure: this.shares * s.close[this.i] / eq1,
        regime: V3.regimeAt(s, i),
      });
    }

    close(i, price, why) {
      const ex = V3.execute("SELL", this.shares, price);
      this.cash += this.shares * ex.fill - C.commission;
      const t = Object.assign(this.open, {
        exitDate: this.s.dates[i], exitPrice: ex.fill, exitReason: why, status: "closed",
        pnl: this.shares * (ex.fill - this.open.entryPrice) - 2 * C.commission,
      });
      this.closed.push(t);
      this.shares = 0; this.open = null;
      return t;
    }

    finish() { if (this.shares > 0) this.close(this.i, this.s.close[this.i], "Episode end"); }
  }

  const SPEEDS = [
    { label: "1×", interval: 1800, steps: 1 },
    { label: "4×", interval: 500, steps: 1 },
    { label: "25×", interval: 90, steps: 2 },
    { label: "250×", interval: 40, steps: 10 },
  ];

  class Engine {
    constructor(market, seed = 11) {
      this.market = market;
      this.rand = V3.rng(seed);
      this.agent = new V3.LinearQAgent({ rand: this.rand });
      this.episodes = []; this.versions = []; this.trades = []; this.decisions = [];
      this.riskEvents = []; this.steps = []; this.running = false; this.speedIdx = 1;
      this.timer = null; this.status = "Idle"; this.regime = null; this.lastUpdate = new Date();
      this.backtestStatus = "Idle";
    }

    get speeds() { return SPEEDS; }

    warmup() {
      this.status = "Warm-up";
      for (let k = 0; k < C.warmupEpisodes; k++) {
        this.newEpisode();
        while (!this.run.done) this.record(this.run.step(this.agent, { explore: true, learn: true, version: this.trainingName() }), false);
        this.endEpisode(false);
      }
      this.newEpisode();
      this.status = "Ready";
    }

    trainingName() { return `LinQ-v${this.versions.length + 1}`; }
    currentVersion() { return this.versions[this.versions.length - 1] || null; }

    newEpisode() {
      const ts = this.market.tickers, t = ts[Math.floor(this.rand() * ts.length)], s = this.market.series[t];
      const span = s.trainEnd - s.start - C.episodeLength - 1;
      const i0 = s.start + Math.floor(this.rand() * Math.max(span, 1));
      this.run = new Run(this.market, t, i0, Math.min(i0 + C.episodeLength, s.trainEnd - 1), C.capital);
    }

    endEpisode(emit = true) {
      const r = this.run; r.finish();
      const won = r.closed.filter(t => t.pnl > 0).length;
      const ep = {
        n: this.episodes.length + 1, ticker: r.ticker, from: r.s.dates[r.i0], to: r.s.dates[r.i1],
        reward: r.rewardSum, ret: r.value(r.i1) / r.capital - 1, maxDD: r.maxDD,
        trades: r.closed.length, winRate: r.closed.length ? won / r.closed.length : null,
        epsilon: this.agent.epsilon, rollingWin: this.rollingWinRate(), equityEnd: r.value(r.i1),
      };
      this.episodes.push(ep);
      this.agent.decayExploration();
      if (emit) V3.bus.emit(E.EPISODE, ep);
      if (ep.n % C.versionEvery === 0) this.saveVersion(emit);
    }

    record(rec, emit = true) {
      this.lastUpdate = new Date();
      if (rec.traded) {
        const t = rec.traded.trade;
        if (rec.traded.side === "BUY") { this.tradeCount = (this.tradeCount || 0) + 1; t.id = this.tradeCount; this.trades.push(t); }
        if (emit) V3.bus.emit(E.TRADE, { side: rec.traded.side, trade: t });
      }
      rec.events.forEach(ev => {
        const e = Object.assign({ date: rec.date, ticker: rec.ticker, wall: new Date() }, ev);
        this.riskEvents.push(e);
        if (emit) V3.bus.emit(E.RISK, e);
      });
      if (this.trades.length > 600) this.trades.splice(0, this.trades.length - 600);
      if (this.riskEvents.length > 80) this.riskEvents.splice(0, this.riskEvents.length - 80);
      this.steps.push({ date: rec.date, equity: rec.equity, drawdown: rec.drawdown, reward: rec.reward, exposure: rec.exposure });
      if (this.steps.length > 2000) this.steps.splice(0, this.steps.length - 2000);
    }

    rollingWinRate(n = 50) {
      const closed = this.trades.filter(t => t.status === "closed").slice(-n);
      return closed.length ? closed.filter(t => t.pnl > 0).length / closed.length : null;
    }

    /** Greedy policy on the held-out final year of every asset. */
    validate(weights) {
      const probe = new V3.LinearQAgent({ rand: this.rand }); probe.load(weights);
      const rets = [], sharpes = [], wins = [];
      for (const t of this.market.tickers) {
        const s = this.market.series[t];
        const r = new Run(this.market, t, s.trainEnd, s.close.length - 1, C.capital);
        const daily = [];
        while (!r.done) { const e0 = r.value(); r.step(probe, { explore: false, learn: false }); daily.push(r.value() / e0 - 1); }
        r.finish();
        rets.push(r.value(r.i1) / C.capital - 1);
        const m = daily.reduce((a, b) => a + b, 0) / daily.length;
        const sd = Math.sqrt(daily.reduce((a, b) => a + (b - m) ** 2, 0) / daily.length);
        sharpes.push(sd > 0 ? m / sd * Math.sqrt(252) : 0);
        r.closed.forEach(tr => wins.push(tr.pnl > 0 ? 1 : 0));
      }
      const avg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
      return { ret: avg(rets), sharpe: avg(sharpes), winRate: avg(wins), trades: wins.length };
    }

    saveVersion(emit = true) {
      const phase = this.status === "Warm-up" ? "pre-training" : "live";
      this.status = "Validating";
      const weights = this.agent.snapshot();
      const recent = this.episodes.slice(-C.versionEvery);
      const avg = k => recent.reduce((a, e) => a + (e[k] || 0), 0) / recent.length;
      const val = this.validate(weights);
      const best = this.versions.reduce((b, v) => (!b || v.val.sharpe > b.val.sharpe ? v : b), null);
      const v = {
        id: this.versions.length + 1, name: `LinQ-v${this.versions.length + 1}`,
        episode: this.episodes.length, created: new Date(), simDate: this.run.s.dates[this.run.i],
        phase, weights, lr: this.agent.lr, epsilon: this.agent.epsilon, updates: this.agent.updates,
        train: { reward: avg("reward"), ret: avg("ret"), winRate: avg("winRate") },
        val, best: !best || val.sharpe > best.val.sharpe,
      };
      if (v.best) this.versions.forEach(x => (x.best = false));
      this.versions.push(v);
      this.status = phase === "pre-training" ? "Warm-up" : this.running ? "Training" : "Paused";
      if (emit) V3.bus.emit(E.MODEL, v);
    }

    // ------------------------------------------------------- live loop --
    start() {
      if (this.running) return;
      this.running = true; this.status = "Training"; this.schedule();
      V3.bus.emit(E.STATUS, this.statusInfo());
    }
    pause() {
      this.running = false; this.status = "Paused"; clearTimeout(this.timer);
      V3.bus.emit(E.STATUS, this.statusInfo());
    }
    setSpeed(idx) { this.speedIdx = idx; if (this.running) { clearTimeout(this.timer); this.schedule(); } V3.bus.emit(E.STATUS, this.statusInfo()); }
    statusInfo() { return { running: this.running, speed: SPEEDS[this.speedIdx], speedIdx: this.speedIdx }; }

    schedule() {
      const sp = SPEEDS[this.speedIdx];
      this.timer = setTimeout(() => { this.tick(sp.steps); if (this.running) this.schedule(); }, sp.interval);
    }

    tick(n = 1) {
      let rec = null;
      for (let k = 0; k < n; k++) {
        if (this.run.done) { this.endEpisode(); this.newEpisode(); }
        rec = this.run.step(this.agent, { explore: true, learn: true, version: this.trainingName() });
        rec.version = this.trainingName();
        rec.episode = this.episodes.length + 1;
        this.record(rec);
        this.decisions.push(rec);
        if (this.decisions.length > 300) this.decisions.shift();
      }
      if (!this.regime || this.regime.label !== rec.regime.label) {
        this.regime = rec.regime; V3.bus.emit(E.REGIME, this.regime);
      }
      V3.bus.emit(E.DECISION, rec);
      V3.bus.emit(E.STEP, this.state());
    }

    /** Snapshot for the live panels. */
    state() {
      const r = this.run, eq = r.value(), last = this.decisions[this.decisions.length - 1];
      const exposure = r.shares * r.s.close[r.i] / eq;
      const volRatio = this.regime ? this.regime.volRatio : 1;
      const drawdown = 1 - eq / r.peak;
      return {
        episode: this.episodes.length + 1, totalEpisodes: this.episodes.length,
        progress: (r.i - r.i0) / (r.i1 - r.i0),
        versionProgress: (this.episodes.length % C.versionEvery) / C.versionEvery,
        reward: last ? last.reward : 0, episodeReward: r.rewardSum,
        winRate: this.rollingWinRate(), equity: eq, ret: eq / r.capital - 1,
        maxDD: r.maxDD, drawdown, trades: this.tradeCount || 0, epsilon: this.agent.epsilon,
        version: this.currentVersion(), training: this.trainingName(), regime: this.regime,
        risk: V3.riskLevel({ exposure, drawdown, volRatio }), exposure,
        status: this.status, ticker: r.ticker, date: r.s.dates[r.i], position: r.open,
        lr: this.agent.lr, updates: this.agent.updates, lastUpdate: this.lastUpdate,
        dataSource: this.market.source, fxLoaded: this.market.fxLoaded, backtestStatus: this.backtestStatus,
      };
    }

    // -------------------------------------------------------- backtests --
    /** Historical simulation of a saved version; never learns, never explores. */
    backtest({ ticker, from, to, capital, freq, versionId }) {
      this.backtestStatus = "Running";
      const s = this.market.series[ticker];
      const v = this.versions.find(x => x.id === +versionId) || this.currentVersion();
      const probe = new V3.LinearQAgent({ rand: this.rand }); probe.load(v.weights);
      let i0 = s.dates.findIndex(d => d >= from); if (i0 < s.start) i0 = s.start;
      let i1 = s.dates.length - 1; while (i1 > i0 && s.dates[i1] > to) i1--;
      if (i1 - i0 < 10) { this.backtestStatus = "Idle"; return { error: "Pick a range of at least 10 trading days." }; }
      const r = new Run(this.market, ticker, i0, i1, capital);
      const every = freq === "weekly" ? 5 : 1;
      while (!r.done) r.step(probe, { explore: false, learn: false, decide: (r.i - i0) % every === 0, version: v.name });
      r.finish();
      const gp = r.closed.filter(t => t.pnl > 0).reduce((a, t) => a + t.pnl, 0);
      const gl = -r.closed.filter(t => t.pnl < 0).reduce((a, t) => a + t.pnl, 0);
      const days = (Date.parse(s.dates[i1]) - Date.parse(s.dates[i0])) / 864e5;
      const total = r.cash / capital - 1;
      const bh = [], p0 = s.close[i0];
      for (let i = i0; i <= i1; i++) bh.push([s.dates[i], capital * s.close[i] / p0]);
      const result = {
        ticker, from: s.dates[i0], to: s.dates[i1], capital, freq, version: v.name,
        total, annual: Math.pow(1 + total, 365.25 / Math.max(days, 1)) - 1,
        winRate: r.closed.length ? r.closed.filter(t => t.pnl > 0).length / r.closed.length : null,
        trades: r.closed.length, maxDD: r.maxDD, profitFactor: gl > 0 ? gp / gl : (gp > 0 ? Infinity : null),
        equity: r.equity, buyHold: bh, buyHoldRet: s.close[i1] / p0 - 1,
      };
      this.backtestStatus = "Done";
      V3.bus.emit(E.BACKTEST, result);
      return result;
    }
  }

  V3.Engine = Engine;
})();
