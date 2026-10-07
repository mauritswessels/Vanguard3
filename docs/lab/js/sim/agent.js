/* Simulation layer · the learning agent, risk manager and execution model.
 *
 * LinearQAgent is a small, transparent reinforcement-learning agent:
 *   Q(s, a) = w_a · φ(s)      for a ∈ {SELL, HOLD, BUY}
 * trained with one-step temporal-difference (Q-learning) updates and
 * epsilon-greedy exploration. Because it is linear, each feature's share of
 * a decision (w_a,i × φ_i) can be shown exactly; this is the model's own
 * scoring, not a human-style explanation of why markets move.
 *
 * Replace this file with an adapter to your own model: keep `act()` and
 * `update()` and return the same objects.
 */
(function () {
  "use strict";
  const V3 = window.V3;
  const ACTIONS = ["SELL", "HOLD", "BUY"];
  V3.ACTIONS = ACTIONS;

  class LinearQAgent {
    constructor(opts = {}) {
      this.nFeat = V3.FEATURES.length;
      this.dim = this.nFeat + 2;                  // features + position flag + bias
      this.lr = opts.lr ?? 0.01;
      this.gamma = opts.gamma ?? 0.9;
      this.epsilon = opts.epsilon ?? 0.6;
      this.epsilonMin = opts.epsilonMin ?? 0.03;
      this.epsilonDecay = opts.epsilonDecay ?? 0.985;
      this.rand = opts.rand || Math.random;
      this.w = ACTIONS.map(() => new Float64Array(this.dim).map(() => (this.rand() - 0.5) * 0.02));
      this.updates = 0;
    }

    phi(z, row, position) {
      const v = new Float64Array(this.dim);
      for (let f = 0; f < this.nFeat; f++) v[f] = z[row * this.nFeat + f];
      v[this.nFeat] = position ? 1 : -1;
      v[this.nFeat + 1] = 1;
      return v;
    }

    q(phi) { return this.w.map(w => dot(w, phi)); }

    /** Pick an action. Confidence is a softmax over the Q-values. */
    act(phi, explore = true) {
      const q = this.q(phi);
      const greedy = q.indexOf(Math.max(...q));
      const explored = explore && this.rand() < this.epsilon;
      const a = explored ? Math.floor(this.rand() * 3) : greedy;
      const t = 0.5, mx = Math.max(...q), e = q.map(v => Math.exp((v - mx) / t)), s = e.reduce((x, y) => x + y, 0);
      const probs = e.map(v => v / s);
      return { action: a, name: ACTIONS[a], q, probs, confidence: probs[a], explored };
    }

    /** One Q-learning step; returns the TD error. */
    update(phi, a, reward, phiNext, done) {
      const target = done ? reward : reward + this.gamma * Math.max(...this.q(phiNext));
      const td = Math.max(-5, Math.min(5, target - dot(this.w[a], phi)));
      const w = this.w[a];
      for (let i = 0; i < this.dim; i++) w[i] = Math.max(-4, Math.min(4, w[i] + this.lr * td * phi[i]));
      this.updates++;
      return td;
    }

    decayExploration() { this.epsilon = Math.max(this.epsilonMin, this.epsilon * this.epsilonDecay); }

    /** Feature contributions to the chosen action relative to the average action. */
    attribution(phi, a) {
      const out = [];
      for (let f = 0; f < this.nFeat; f++) {
        const avg = (this.w[0][f] + this.w[1][f] + this.w[2][f]) / 3;
        out.push({ feature: V3.FEATURES[f].label, value: phi[f], contribution: (this.w[a][f] - avg) * phi[f] });
      }
      return out.sort((x, y) => Math.abs(y.contribution) - Math.abs(x.contribution));
    }

    snapshot() { return this.w.map(w => Array.from(w)); }
    load(weights) { this.w = weights.map(w => Float64Array.from(w)); }
  }

  function dot(a, b) { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }

  // ------------------------------------------------------------ risk ----
  /** Position sizing, stops and drawdown guards. All limits in V3.RISK. */
  V3.RISK = {
    targetVol: 0.15,        // annualised volatility the position is sized to
    maxPosition: 1.0,       // max fraction of equity in the asset
    minPosition: 0.1,
    stopAtr: 2.5,           // stop distance in daily-volatility units of price
    ddHalve: 0.08,          // drawdown at which new sizes are halved
    ddBlock: 0.12,          // drawdown at which new buys are blocked
  };

  V3.riskCheck = function (decision, ctx) {
    const R = V3.RISK, notes = [];
    const dailyVol = Math.max(ctx.vol, 0.004);
    let size = Math.min(R.maxPosition, Math.max(R.minPosition, R.targetVol / (dailyVol * Math.sqrt(252))));
    let action = decision.name, approved = true, event = null;
    if (action === "BUY" && !ctx.position) {
      if (ctx.drawdown >= R.ddBlock) {
        approved = false; action = "HOLD";
        event = { level: "high", text: `Buy blocked: drawdown ${(ctx.drawdown * 100).toFixed(1)}% ≥ ${R.ddBlock * 100}%` };
      } else if (ctx.drawdown >= R.ddHalve) {
        size /= 2;
        event = { level: "elevated", text: `Size halved: drawdown ${(ctx.drawdown * 100).toFixed(1)}%` };
      }
      notes.push(`Vol-target size ${(size * 100).toFixed(0)}% of equity`);
    }
    const stop = ctx.price * (1 - R.stopAtr * dailyVol);
    if (action === "BUY" && ctx.position) action = "HOLD";       // already long
    if (action === "SELL" && !ctx.position) action = "HOLD";     // long-only, nothing to sell
    return { approved, action, size, stop, notes, event, limits: { ...R } };
  };

  V3.riskLevel = function ({ exposure, drawdown, volRatio }) {
    const score = (drawdown >= V3.RISK.ddBlock ? 3 : drawdown >= V3.RISK.ddHalve ? 2 : drawdown >= 0.04 ? 1 : 0)
      + (volRatio > 1.6 ? 2 : volRatio > 1.25 ? 1 : 0) + (exposure > 0.9 ? 1 : 0);
    return score >= 4 ? "HIGH" : score >= 2 ? "ELEVATED" : score >= 1 ? "MODERATE" : "LOW";
  };

  // -------------------------------------------------------- execution ----
  V3.execute = function (side, shares, price) {
    const slip = V3.config.slippageBps / 1e4;
    const fill = side === "BUY" ? price * (1 + slip) : price * (1 - slip);
    return { fill, cost: V3.config.commission + shares * price * slip };
  };

  V3.LinearQAgent = LinearQAgent;
})();
