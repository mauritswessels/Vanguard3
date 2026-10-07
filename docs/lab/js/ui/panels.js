/* UI layer · live system, health, decision, component detail, regime and
 * the pipeline strip. Reads engine state and bus events; never mutates the
 * simulation except through the play / pause / speed controls in main.js.
 */
(function () {
  "use strict";
  const V3 = window.V3, f = V3.fmt, E = V3.EVENTS;
  const $ = id => document.getElementById(id);
  const sign = v => (v > 0 ? "pos" : v < 0 ? "neg" : "");

  /** Coalesce repeated renders into one per animation frame. */
  function batched(fn) {
    let queued = false, arg;
    return a => { arg = a; if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fn(arg); }); };
  }

  const ui = (V3.ui = { batched });
  let engineRef = null; const engine0 = () => engineRef;

  // ----------------------------------------------------------- live panel --
  const LIVE = [
    ["episode", "Episode"], ["version", "Model version"],
    ["equity", "Sim portfolio CHF"], ["ret", "Sim return"],
    ["reward", "Step reward"], ["epReward", "Episode reward"],
    ["win", "Win rate (50)"], ["trades", "Trades"],
    ["maxDD", "Max drawdown"], ["eps", "Exploration rate"],
    ["risk", "Risk level"], ["status", "Training status"],
    ["regime", "Market regime", true], ["asset", "Trading (simulated)", true],
  ];
  const liveCells = {};
  const STEADY = new Set(["equity", "ret", "reward", "epReward", "asset"]);

  function buildLive() {
    $("live").innerHTML = LIVE.map(([k, l, wide]) => `<div class="kv${wide ? " wide" : ""}" data-k="${k}"><span>${l}</span><b>–</b></div>`).join("");
    for (const el of $("live").children) liveCells[el.dataset.k] = el;
  }

  function setCell(k, text, cls = "") {
    const el = liveCells[k], b = el.lastElementChild;
    if (b.textContent === text) return;
    b.textContent = text; b.className = cls;
    if (STEADY.has(k)) return;                          // values that change every step do not flash
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }

  const RISK_CLS = { LOW: "pos", MODERATE: "", ELEVATED: "warn", HIGH: "neg" };

  function renderLive(st) {
    setCell("episode", `${st.episode}  ·  ${st.totalEpisodes} done`);
    setCell("version", st.version ? `${st.version.name} → v${engine0().versions.length + 1}` : `${st.training} (untrained)`);
    setCell("equity", f.chf(st.equity));
    setCell("ret", f.pct(st.ret, 2), sign(st.ret));
    setCell("reward", f.num(st.reward, 3), sign(st.reward));
    setCell("epReward", f.num(st.episodeReward, 2), sign(st.episodeReward));
    setCell("win", f.pctU(st.winRate, 0));
    setCell("trades", String(st.trades));
    setCell("maxDD", st.maxDD ? "−" + f.pctU(st.maxDD, 1) : "0%", st.maxDD > V3.RISK.ddHalve ? "neg" : "");
    setCell("eps", f.num(st.epsilon, 3));
    setCell("risk", st.risk, RISK_CLS[st.risk]);
    setCell("status", st.status, st.status === "Training" ? "pos" : "warn");
    setCell("regime", st.regime ? st.regime.label : "–");
    setCell("asset", `${st.ticker}  ·  ${f.date(st.date)}${st.position ? "  ·  long" : "  ·  flat"}`);
    $("epProg").style.width = (st.progress * 100).toFixed(1) + "%";
    $("epProgTxt").textContent = f.pctU(st.progress);
    $("verProg").style.width = (st.versionProgress * 100).toFixed(1) + "%";
    $("verProgTxt").textContent = `${Math.round(st.versionProgress * V3.config.versionEvery)} / ${V3.config.versionEvery} episodes`;
    const tag = $("liveStatus");
    tag.textContent = st.status === "Training" ? "live" : st.status.toLowerCase();
    tag.className = "tag" + (st.status === "Training" ? " live" : "");
  }

  function renderSpark(engine) {
    const c = $("spark"), w = c.clientWidth, h = 46, dpr = Math.min(devicePixelRatio, 2);
    if (!w) return;
    if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const eq = engine.run.equity.map(p => p[1]), n = V3.config.episodeLength + 1;
    const lo = Math.min(...eq, V3.config.capital * 0.98), hi = Math.max(...eq, V3.config.capital * 1.02);
    const y = v => h - 3 - (v - lo) / (hi - lo) * (h - 6), x = i => i / (n - 1) * w;
    g.strokeStyle = "rgba(140,170,210,.18)"; g.setLineDash([3, 3]); g.beginPath();
    g.moveTo(0, y(V3.config.capital)); g.lineTo(w, y(V3.config.capital)); g.stroke(); g.setLineDash([]);
    const up = eq[eq.length - 1] >= V3.config.capital, col = up ? "#3ddc97" : "#ff6b6b";
    const grd = g.createLinearGradient(0, 0, 0, h); grd.addColorStop(0, col + "44"); grd.addColorStop(1, col + "00");
    g.beginPath(); eq.forEach((v, i) => (i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v))));
    g.strokeStyle = col; g.lineWidth = 1.5; g.stroke();
    g.lineTo(x(eq.length - 1), h); g.lineTo(0, h); g.closePath(); g.fillStyle = grd; g.fill();
    g.fillStyle = col; g.beginPath(); g.arc(x(eq.length - 1), y(eq[eq.length - 1]), 2.5, 0, 7); g.fill();
    $("sparkNote").textContent = `Simulated equity, episode ${engine.episodes.length + 1} on ${engine.run.ticker} (starts at 100,000 CHF)`;
  }

  // --------------------------------------------------------------- health --
  function renderHealth(st, engine) {
    const age = (Date.now() - st.lastUpdate) / 1000;
    const feats = engine.decisions.length ? engine.decisions[engine.decisions.length - 1].features : [];
    const featOk = feats.length === V3.FEATURES.length && feats.every(Number.isFinite);
    const m = engine.market;
    const rows = [
      ["Data feed", m.source === "historical" ? (m.fxLoaded ? "g" : "y") : "y",
        m.source === "historical" ? `${m.tickers.length} assets · ${m.fxLoaded ? "CHF" : "USD, no FX"}` : "Synthetic fallback"],
      ["Feature pipeline", featOk ? "g" : (feats.length ? "r" : "y"), featOk ? `${V3.FEATURES.length} features ok` : "Waiting"],
      ["AI model", st.status === "Training" ? "g" : "y", `${st.training} · ${st.status}`],
      ["Backtesting engine", st.backtestStatus === "Running" ? "y" : "g", st.backtestStatus],
      ["Risk engine", st.risk === "HIGH" ? "r" : st.risk === "ELEVATED" ? "y" : "g", `Active · ${st.risk}`],
      ["Simulation", engine.running ? "g" : "y", engine.running ? `Running ${engine.statusInfo().speed.label}` : "Paused"],
      ["Last update", engine.running ? (age < 6 ? "g" : age < 30 ? "y" : "r") : "y", f.time(st.lastUpdate)],
      ["Broker connection", "", "Off by design"],
    ];
    $("health").innerHTML = rows.map(([n, c, s]) =>
      `<li title="${V3.esc(n + ": " + s)}"><span class="lamp ${c}"></span><span class="hn">${n}</span><span class="hs">${V3.esc(s)}</span></li>`).join("");
  }

  // ------------------------------------------------------------- decision --
  function renderDecision(rec) {
    const d = rec.decision, r = rec.risk, ac = V3.ACTION_COLORS[d.name];
    $("decTime").textContent = f.time(new Date());
    $("decAction").innerHTML = `<span style="color:${ac}">${d.name}</span>${d.explored ? "<small>EXPLORING</small>" : ""}`;
    $("decAsset").textContent = rec.ticker;
    $("decDate").textContent = `${f.date(rec.date)} · sim close`;
    $("decConf").textContent = f.pctU(d.confidence);
    $("decQ").innerHTML = V3.ACTIONS.map((a, k) =>
      `<div class="qb"><span>${a}</span><div class="track"><i style="width:${(d.probs[k] * 100).toFixed(1)}%;background:${V3.ACTION_COLORS[a]}${a === d.name ? "" : "77"}"></i></div><em>${f.pctU(d.probs[k])}</em></div>`).join("");

    let result;
    if (!r.approved) result = `<span class="neg">Blocked by risk manager</span>`;
    else if (rec.traded && rec.traded.side === "BUY") {
      const t = rec.traded.trade; result = `<span class="pos">Bought ${t.shares} @ ${f.px(t.entryPrice)}</span>`;
    } else if (rec.traded) {
      const t = rec.traded.trade; result = `<span class="${sign(t.pnl)}">Sold, P&amp;L ${f.chf(t.pnl)} CHF</span>`;
    } else result = r.action !== d.name ? `No trade (${d.name === "BUY" ? "already long" : "nothing to sell"})` : rec.position ? "Holding position" : "Stayed flat";

    const open = rec.traded && rec.traded.side === "BUY" ? rec.traded.trade : null;
    const rows = [
      ["Price (CHF)", f.px(rec.price)],
      ["Executed", `<span style="color:${V3.ACTION_COLORS[r.action]}">${r.action}</span>${r.action !== d.name ? " (risk / position rule)" : ""}`],
      ["Position size", open ? `${open.shares} sh · ${f.pctU(open.size)} of equity` : rec.position ? "Unchanged" : "None"],
      ["Stop", open || rec.position ? f.px(open ? open.stop : r.stop) + (open ? "" : " (if bought)") : f.px(r.stop) + " (if bought)"],
      ["Risk params", `vol ${f.pctU(V3.RISK.targetVol)} · DD ${f.pctU(V3.RISK.ddHalve)}/${f.pctU(V3.RISK.ddBlock)}`],
      ["Result", result],
      ["Reward (next session)", `<span class="${sign(rec.reward)}">${f.num(rec.reward, 3)}</span>`],
      ["Model", `${rec.version} · episode ${rec.episode}`],
    ];
    $("decRows").innerHTML = rows.map(([k, v]) => `<span>${k}</span><b>${v}</b>`).join("");
    renderAttr($("decAttr"), rec.attribution.slice(0, 5));
  }

  function renderAttr(el, attr) {
    const mx = Math.max(...attr.map(a => Math.abs(a.contribution)), 1e-6);
    el.innerHTML = attr.map(a => {
      const w = Math.abs(a.contribution) / mx * 50, pos = a.contribution >= 0;
      return `<div class="ar" title="Standardised value ${f.num(a.value, 2)}"><span>${V3.esc(a.feature)}</span>` +
        `<div class="track"><i style="left:${pos ? 50 : 50 - w}%;width:${w}%;background:${pos ? "#3ddc97" : "#ff6b6b"}"></i></div>` +
        `<em class="${pos ? "pos" : "neg"}">${(pos ? "+" : "") + a.contribution.toFixed(2)}</em></div>`;
    }).join("");
  }
  ui.renderAttr = renderAttr;

  // --------------------------------------------------- component details --
  /** Live facts per component, for the hover tooltip and the detail panel. */
  ui.nodeInfo = function (id, engine) {
    const st = engine.state(), m = engine.market, last = engine.decisions[engine.decisions.length - 1];
    const s0 = m.series[m.tickers[0]];
    const ver = st.version, best = engine.versions.find(v => v.best);
    const lastTd = last ? last.td : 0;
    const info = {
      data: [["Source", m.source === "historical" ? "Vanguard3 export (yfinance EOD)" : "Synthetic fallback"],
        ["Assets", m.tickers.length], ["History", `${s0.dates[0]} → ${s0.dates[s0.dates.length - 1]}`],
        ["Currency", m.fxLoaded ? "CHF (converted)" : "USD"], ["Current bar", `${st.ticker} ${st.date}`]],
      features: [["Features", `${V3.FEATURES.length} standardised`], ["Scaled on", "Training period only"],
        ["Strongest now", last ? (() => { const k = last.features.reduce((b, v, i, a) => Math.abs(v) > Math.abs(a[b]) ? i : b, 0); return `${V3.FEATURES[k].label} (${f.num(last.features[k], 2)})`; })() : "–"]],
      strategy: [["Regime", st.regime ? st.regime.label : "–"], ["Trend strength", st.regime ? f.pctU(st.regime.trendStrength, 1) : "–"],
        ["Vol vs median", st.regime ? f.num(st.regime.volRatio, 2) + "×" : "–"]],
      agent: [["Model", "Linear Q-learning"], ["Training", st.training], ["Deployed", ver ? ver.name : "–"],
        ["Last action", last ? `${last.decision.name} · ${f.pctU(last.decision.confidence)}` : "–"], ["Exploration rate", f.num(st.epsilon, 3)]],
      risk: [["Level", st.risk], ["Exposure", f.pctU(st.exposure)], ["Drawdown", f.pctU(st.drawdown, 1)],
        ["Limits", `halve ${f.pctU(V3.RISK.ddHalve)} · block ${f.pctU(V3.RISK.ddBlock)}`]],
      exec: [["Fee", `${V3.config.commission} CHF per fill`], ["Slippage", `${V3.config.slippageBps} bp`], ["Simulated trades", st.trades],
        ["Real orders", "Disabled"]],
      portfolio: [["Sim equity", f.chf(st.equity) + " CHF"], ["Return", f.pct(st.ret, 2)], ["Position", st.position ? `${st.position.shares} ${st.ticker}` : "Flat"],
        ["Max drawdown", f.pctU(st.maxDD, 1)]],
      backtest: [["Status", st.backtestStatus], ["Versions available", engine.versions.length], ["Last run", ui.lastBacktest ? `${ui.lastBacktest.ticker} ${f.pct(ui.lastBacktest.total)}` : "–"]],
      reward: [["Step reward", f.num(st.reward, 3)], ["Episode reward", f.num(st.episodeReward, 2)], ["Formula", "return% − cost − DD penalty"]],
      learning: [["Method", "TD(0) Q-learning"], ["Learning rate", st.lr], ["Discount γ", engine.agent.gamma], ["Updates", st.updates.toLocaleString("en")],
        ["Last TD error", f.num(lastTd, 3)], ["Versions", engine.versions.length]],
      monitor: [["Episodes", st.totalEpisodes], ["Win rate (50)", f.pctU(st.winRate)], ["Best version", best ? `${best.name} · Sharpe ${f.num(best.val.sharpe, 2)}` : "–"]],
    }[id] || [];
    return info;
  };

  ui.nodeStatus = function (id, engine) {
    const rows = ui.nodeInfo(id, engine);
    return rows.slice(0, 2).map(([k, v]) => `${k}: ${V3.esc(v)}`).join("<br>");
  };

  let shownNode = null;
  ui.showNode = function (id, engine) {
    shownNode = id;
    const p = $("nodePanel");
    if (!id) { p.hidden = true; return; }
    const n = V3.NODES.find(x => x.id === id);
    p.hidden = false;
    $("nodeTitle").textContent = n.name;
    $("nodeCat").textContent = { data: "Data", process: "Processing", core: "Core model", risk: "Risk", exec: "Execution (simulated)",
      research: "Research", learn: "Learning", monitor: "Monitoring" }[n.cat];
    $("nodeCat").style.color = V3.CAT_COLORS[n.cat];
    $("nodeDesc").textContent = n.desc;
    ui.refreshNode(engine);
  };
  ui.refreshNode = function (engine) {
    if (!shownNode) return;
    $("nodeRows").innerHTML = ui.nodeInfo(shownNode, engine).map(([k, v]) => `<span>${k}</span><b title="${V3.esc(v)}">${V3.esc(v)}</b>`).join("");
  };
  ui.shownNode = () => shownNode;

  // --------------------------------------------------------------- regime --
  function renderRegime(reg) {
    document.querySelectorAll("#regime .rg").forEach(el => el.classList.toggle("on", el.dataset.rg === reg.trend || el.dataset.rg === reg.vol));
    $("regime").title = `Simulated market regime: ${reg.label}. Trend = EMA20 vs EMA50 gap ${f.pctU(reg.trendStrength, 1)}; volatility ${f.num(reg.volRatio, 2)}× its median.`;
  }

  // ------------------------------------------------------- pipeline strip --
  const STAGE_COLORS = { data: "#4cc9f0", features: "#7c8cff", analyse: "#ffcf7a", decide: "#ffcf7a", risk: "#ff6b6b", exec: "#3ddc97",
    portfolio: "#3ddc97", reward: "#c08cff", learn: "#c08cff" };
  function buildStrip() {
    $("strip").innerHTML = V3.PIPELINE.map((s, i) => `<li style="--sc:${STAGE_COLORS[s.key]}"><i>${i + 1}</i>${s.label}</li>`).join("");
  }
  ui.stage = function (i, rec) {
    const lis = $("strip").children;
    for (let k = 0; k < lis.length; k++) {
      lis[k].classList.toggle("on", k === i);
      lis[k].classList.toggle("done", i >= 0 && k < i);
    }
    if (i === 3) lis[3].style.setProperty("--sc", V3.ACTION_COLORS[rec.decision.name]);
  };

  // ----------------------------------------------------------------- init --
  ui.init = function (engine) {
    engineRef = engine;
    buildLive(); buildStrip();
    const step = batched(st => {
      renderLive(st); renderSpark(engine); renderHealth(st, engine);
      ui.refreshNode(engine);
    });
    const decision = batched(renderDecision);
    V3.bus.on(E.STEP, step);
    V3.bus.on(E.DECISION, decision);
    V3.bus.on(E.REGIME, renderRegime);
    V3.bus.on(E.STATUS, () => step(engine.state()));
    V3.bus.on(E.BACKTEST, r => { ui.lastBacktest = r; renderHealth(engine.state(), engine); });
    setInterval(() => renderHealth(engine.state(), engine), 2000);
    const st = engine.state(); step(st);
    if (engine.regime) renderRegime(engine.regime);
  };
})();
