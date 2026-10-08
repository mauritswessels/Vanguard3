/* UI layer · bottom drawer: training charts, backtesting, model versions,
 * risk and the trade history. */
(function () {
  "use strict";
  const V3 = window.V3, f = V3.fmt, E = V3.EVENTS, ui = V3.ui;
  const $ = id => document.getElementById(id);
  const sign = v => (v > 0 ? "pos" : v < 0 ? "neg" : "");
  const GREEN = "#6cc391", RED = "#e27466";
  let engine, active = "training";
  const isOn = tab => active === tab && !document.body.classList.contains("collapsed");

  // --------------------------------------------------------------- tabs ---
  function initTabs(onChange) {
    const saved = V3.store.get("v3lab-tab");
    document.querySelectorAll(".tabs [role=tab]").forEach(b => b.addEventListener("click", () => select(b.dataset.tab)));
    function select(tab) {
      active = tab; V3.store.set("v3lab-tab", tab);
      document.querySelectorAll(".tabs [role=tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
      document.querySelectorAll(".tab-body").forEach(b => b.classList.toggle("on", b.dataset.body === tab));
      if (document.body.classList.contains("collapsed")) toggleDrawer(false);
      onChange(tab);
    }
    function toggleDrawer(collapse) {
      document.body.classList.toggle("collapsed", collapse);
      V3.store.set("v3lab-drawer", collapse ? "0" : "1");
      if (!collapse) setTimeout(() => onChange(active), 380);
    }
    $("drawerToggle").addEventListener("click", () => toggleDrawer(!document.body.classList.contains("collapsed")));
    if (V3.store.get("v3lab-drawer") === "0") document.body.classList.add("collapsed");
    if (saved && document.querySelector(`[data-tab="${saved}"]`)) select(saved);
    ui.selectTab = select;
  }

  // ----------------------------------------------------------- training ---
  const T = {};
  let range = 200;
  function initTraining() {
    const C = V3.charts;
    T.reward = C.bars($("chReward"), { label: "Reward", yFmt: v => (+v).toFixed(1) });
    T.equity = C.line($("chEquity"), { color: "#7fa7d9", label: "CHF", yFmt: v => f.chf(v) });
    T.win = C.line($("chWin"), { color: "#d3a75f", label: "Win rate", yFmt: v => Math.round(v * 100) + "%" });
    T.dd = C.bars($("chDD"), { label: "Max DD", yFmt: v => (v * 100).toFixed(0) + "%" });
    T.ret = C.bars($("chRet"), { label: "Return", yFmt: v => (v * 100).toFixed(0) + "%" });
    T.eps = C.line($("chEps"), { color: "#a99bd6", label: "ε", yFmt: v => (+v).toFixed(2) });
    T.win.options.scales.y.min = 0; T.win.options.scales.y.max = 1;
    T.eps.options.scales.y.min = 0;
    // Break-even line on the equity chart.
    T.equity.data.datasets.push({ label: "Start", data: [], borderColor: "rgba(140,170,210,.35)", borderDash: [4, 4], borderWidth: 1, fill: false });
    document.querySelectorAll("#trainRange button").forEach(b => b.addEventListener("click", () => {
      range = +b.dataset.n;
      document.querySelectorAll("#trainRange button").forEach(x => x.classList.toggle("on", x === b));
      renderTraining();
    }));
  }

  function renderTraining() {
    const eps = range ? engine.episodes.slice(-range) : engine.episodes;
    const L = eps.map(e => e.n), C = V3.charts;
    C.set(T.reward, L, eps.map(e => e.reward), eps.map(e => (e.reward >= 0 ? GREEN : RED) + "cc"));
    C.set(T.equity, L, eps.map(e => e.equityEnd));
    T.equity.data.datasets[1].data = eps.map(() => V3.config.capital); T.equity.update("none");
    C.set(T.win, L, eps.map(e => e.rollingWin));
    C.set(T.dd, L, eps.map(e => -e.maxDD), eps.map(() => RED + "aa"));
    C.set(T.ret, L, eps.map(e => e.ret), eps.map(e => (e.ret >= 0 ? GREEN : RED) + "cc"));
    C.set(T.eps, L, eps.map(e => e.epsilon));
  }

  // ----------------------------------------------------------- backtest ---
  let btChart;
  function initBacktest() {
    const m = engine.market;
    $("btAsset").innerHTML = m.tickers.map(t => `<option>${t}</option>`).join("");
    $("btAsset").value = m.tickers.includes("SPY") ? "SPY" : m.tickers[0];
    btChart = V3.charts.line($("chBT"), { color: "#d3a75f", label: "Model", yFmt: v => f.chf(v),
      extra: [{ label: "Buy & hold", data: [], borderColor: "rgba(140,170,210,.6)", borderWidth: 1.2, borderDash: [4, 3], fill: false }] });
    btChart.options.plugins.legend = { display: true, position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 2, color: "#8b9ab0" } };
    quick("val");
    $("btQuick").addEventListener("click", e => { if (e.target.dataset.q) quick(e.target.dataset.q); });
    $("btAsset").addEventListener("change", () => quick("val"));
    $("btForm").addEventListener("submit", e => { e.preventDefault(); runBacktest(); });
    refreshVersions();
  }

  function quick(q) {
    const s = engine.market.series[$("btAsset").value], last = s.dates[s.dates.length - 1];
    const back = y => { const d = new Date(last + "T00:00:00Z"); d.setUTCFullYear(d.getUTCFullYear() - y); return d.toISOString().slice(0, 10); };
    $("btTo").value = last;
    $("btFrom").value = q === "val" ? s.dates[s.trainEnd] : q === "all" ? s.dates[s.start] : back(q === "1y" ? 1 : 3);
    $("btFrom").min = $("btTo").min = s.dates[s.start]; $("btFrom").max = $("btTo").max = last;
  }

  function refreshVersions() {
    const sel = $("btVer"), cur = sel.value;
    sel.innerHTML = engine.versions.slice().reverse().map(v =>
      `<option value="${v.id}">${v.name}${v.best ? " · best validation" : ""} (ep ${v.episode})</option>`).join("");
    const best = engine.versions.find(v => v.best);
    if (cur && engine.versions.some(v => String(v.id) === cur)) sel.value = cur;
    else if (best) sel.value = best.id;
  }

  function runBacktest() {
    $("btErr").textContent = "";
    if (!engine.versions.length) { $("btErr").textContent = "No saved model version yet."; return; }
    const cap = Math.max(1000, +$("btCap").value || 100000);
    const r = engine.backtest({ ticker: $("btAsset").value, from: $("btFrom").value, to: $("btTo").value, capital: cap,
      freq: $("btFreq").value, versionId: $("btVer").value });
    if (r.error) { $("btErr").textContent = r.error; return; }
    renderBacktest(r);
  }

  function renderBacktest(r) {
    const s = engine.market.series[r.ticker], trainEndDate = s.dates[s.trainEnd];
    const inSample = r.from < trainEndDate;
    $("btTitle").innerHTML = `<b>Historical simulation</b> · ${r.version} on ${r.ticker} · ${f.date(r.from)} – ${f.date(r.to)} · ${r.freq} decisions · ` +
      (inSample ? `<span class="warn">includes training data (in-sample)</span>` : `<span class="pos">held-out year, never trained on</span>`);
    const pf = r.profitFactor === Infinity ? "∞" : f.num(r.profitFactor, 2);
    const k = [["Total return", f.pct(r.total), sign(r.total)], ["Annualised", f.pct(r.annual), sign(r.annual)],
      ["Win rate", f.pctU(r.winRate), ""], ["Trades", r.trades, ""], ["Max drawdown", "−" + f.pctU(r.maxDD, 1), r.maxDD > 0.15 ? "neg" : ""],
      ["Profit factor", pf, r.profitFactor > 1 ? "pos" : r.profitFactor < 1 ? "neg" : ""], ["Buy & hold", f.pct(r.buyHoldRet), sign(r.buyHoldRet)]];
    $("btErr").textContent = r.trades ? "" : "The model stayed in cash for this whole period: its greedy policy never scored BUY highest.";
    $("btKpis").innerHTML = k.map(([l, v, c]) => `<div class="kv"><span>${l}</span><b class="${c}">${v}</b></div>`).join("");
    btChart.data.labels = r.equity.map(p => p[0]);
    btChart.data.datasets[0].data = r.equity.map(p => p[1]);
    btChart.data.datasets[1].data = r.buyHold.map(p => p[1]);
    btChart.update("none");
  }

  // -------------------------------------------------------------- model ---
  let verChart, compareSel = [];
  function initModel() {
    verChart = new window.Chart(hostCanvas($("chVer")), {
      type: "bar",
      data: { labels: [], datasets: [
        { label: "Training (avg episode)", data: [], backgroundColor: "#7fa7d9aa", borderRadius: 1 },
        { label: "Validation (held-out year)", data: [], backgroundColor: "#d3a75faa", borderRadius: 1 }] },
      options: { plugins: { legend: { display: true, position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 6, color: "#8b9ab0" } },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${f.pct(c.parsed.y)}` } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: "rgba(140,170,210,.08)" }, ticks: { callback: v => (v * 100).toFixed(0) + "%" } } } },
    });
    $("verTable").addEventListener("change", e => {
      if (e.target.type !== "checkbox") return;
      const id = +e.target.value;
      compareSel = e.target.checked ? [...compareSel.filter(x => x !== id), id].slice(-2) : compareSel.filter(x => x !== id);
      renderModel();
    });
  }
  function hostCanvas(c) {
    const d = document.createElement("div"); d.style.cssText = "position:relative;flex:1;min-height:0";
    c.replaceWith(d); d.appendChild(c); return c;
  }

  function renderModel() {
    const st = engine.state(), vs = engine.versions, cur = vs[vs.length - 1], best = vs.find(v => v.best);
    const recent = engine.episodes.slice(-V3.config.versionEvery);
    const avgR = recent.length ? recent.reduce((a, e) => a + e.reward, 0) / recent.length : null;
    $("modelCard").innerHTML = `<h3 style="margin-top:0">Current version</h3><p class="ver-name">${cur ? cur.name : "–"}</p>
      <p class="fine" style="margin:0 0 10px">Now training ${st.training}. Validation uses the final ${V3.config.validationDays} sessions of every asset, which training never sees.</p>
      <div class="kv-list">${[
        ["Status", st.status], ["Episodes trained", st.totalEpisodes], ["Weight updates", st.updates.toLocaleString("en")],
        ["Latest update", cur ? `${f.time(cur.created)} · ep ${cur.episode}` : "–"], ["Learning rate", st.lr], ["Exploration ε", f.num(st.epsilon, 3)],
        ["Training reward (20 ep)", f.num(avgR, 2)], ["Validation return", cur ? f.pct(cur.val.ret) : "–"],
        ["Validation Sharpe", cur ? f.num(cur.val.sharpe, 2) : "–"], ["Validation win rate", cur ? f.pctU(cur.val.winRate) : "–"],
        ["Best on validation", best ? best.name : "–"],
      ].map(([k, v]) => `<span>${k}</span><b>${v}</b>`).join("")}</div>`;

    if (!compareSel.length && vs.length) compareSel = vs.length > 1 ? [vs[vs.length - 2].id, cur.id] : [cur.id];
    $("verTable").innerHTML = `<thead><tr><th></th><th>Version</th><th>Saved</th><th>Episode</th><th>Train reward</th><th>Train return</th><th>Val return</th><th>Val Sharpe</th><th>Val win</th></tr></thead><tbody>` +
      vs.slice().reverse().map(v => `<tr><td><input type="checkbox" value="${v.id}" ${compareSel.includes(v.id) ? "checked" : ""} aria-label="Compare ${v.name}"></td>
        <td>${v.name} ${v.best ? '<span class="pill best">BEST</span>' : ""}</td><td>${v.phase === "pre-training" ? "pre-training" : f.time(v.created)}</td><td>${v.episode}</td>
        <td class="${sign(v.train.reward)}">${f.num(v.train.reward, 2)}</td><td class="${sign(v.train.ret)}">${f.pct(v.train.ret)}</td>
        <td class="${sign(v.val.ret)}">${f.pct(v.val.ret)}</td><td>${f.num(v.val.sharpe, 2)}</td><td>${f.pctU(v.val.winRate)}</td></tr>`).join("") + "</tbody>";
    $("verTable").querySelectorAll("tbody tr").forEach(tr => tr.addEventListener("click", e => {
      if (e.target.tagName !== "INPUT") { const cb = tr.querySelector("input"); cb.checked = !cb.checked; cb.dispatchEvent(new Event("change", { bubbles: true })); }
    }));

    const pair = compareSel.map(id => vs.find(v => v.id === id)).filter(Boolean).sort((a, b) => a.id - b.id);
    if (pair.length === 2) {
      const [a, b] = pair, rows = [["Train reward", v => v.train.reward, x => f.num(x, 2)], ["Train return", v => v.train.ret, x => f.pct(x)],
        ["Validation return", v => v.val.ret, x => f.pct(x)], ["Validation Sharpe", v => v.val.sharpe, x => f.num(x, 2)],
        ["Validation win rate", v => v.val.winRate, x => f.pctU(x)], ["Validation trades", v => v.val.trades, x => x],
        ["Exploration ε", v => v.epsilon, x => f.num(x, 3)]];
      $("verCompare").innerHTML = `<table><thead><tr><th>Compare</th><th>${a.name}</th><th>${b.name}</th><th>Change</th></tr></thead><tbody>` +
        rows.map(([l, g, fm]) => { const d = g(b) - g(a); return `<tr><td>${l}</td><td>${fm(g(a))}</td><td>${fm(g(b))}</td><td class="${l.includes("ε") ? "" : sign(d)}">${d >= 0 ? "+" : ""}${l.includes("rate") || l.includes("return") ? (d * 100).toFixed(1) + " pt" : f.num(d, 2)}</td></tr>`; }).join("") +
        "</tbody></table>";
    } else $("verCompare").innerHTML = `<p class="fine">Tick two versions to compare them side by side.</p>`;

    verChart.data.labels = vs.map(v => v.name.replace("LinQ-", ""));
    verChart.data.datasets[0].data = vs.map(v => v.train.ret);
    verChart.data.datasets[1].data = vs.map(v => v.val.ret);
    verChart.update("none");
  }

  // --------------------------------------------------------------- risk ---
  function renderRisk() {
    const st = engine.state(), R = V3.RISK, r = engine.run, s = r.s;
    const vol = s.feat.vol20[r.i] * Math.sqrt(252), volR = st.regime ? st.regime.volRatio : 1;
    const open = r.open, stopDist = open ? s.close[r.i] / open.stop - 1 : null;
    const g = (name, val, txt, max, marks, lvl, note) => `<div class="gauge ${lvl}"><div class="gh"><span>${name}</span><span>${lvl === "r" ? "BREACH" : lvl === "y" ? "WARNING" : "OK"}</span></div>
      <div class="gv">${txt}</div><div class="track"><i style="width:${Math.min(100, Math.max(0, val / max * 100)).toFixed(1)}%"></i>${marks.map(m => `<u style="left:${m / max * 100}%"></u>`).join("")}</div><div class="gn">${note}</div></div>`;
    $("riskGauges").innerHTML = [
      g("Exposure", st.exposure, f.pctU(st.exposure), 1.2, [R.maxPosition], st.exposure > R.maxPosition ? "r" : st.exposure > 0.9 ? "y" : "", `Invested share of equity · limit ${f.pctU(R.maxPosition)}`),
      g("Concentration", st.exposure > 0 ? 1 : 0, st.exposure > 0 ? `100% in ${r.ticker}` : "No position", 1, [], st.exposure > 0.6 ? "y" : "",
        "Episodes trade one asset, so any position is fully concentrated"),
      g("Drawdown", st.drawdown, "−" + f.pctU(st.drawdown, 1), 0.15, [R.ddHalve, R.ddBlock], st.drawdown >= R.ddBlock ? "r" : st.drawdown >= R.ddHalve ? "y" : "",
        `Sizes halve at ${f.pctU(R.ddHalve)}, buys blocked at ${f.pctU(R.ddBlock)}`),
      g("Volatility", vol, f.pctU(vol, 1) + " ann.", 0.8, [R.targetVol], volR > 1.6 ? "r" : volR > 1.25 ? "y" : "", `${f.num(volR, 2)}× its median · target ${f.pctU(R.targetVol)}`),
      g("Episode max drawdown", st.maxDD, "−" + f.pctU(st.maxDD, 1), 0.2, [R.ddHalve, R.ddBlock], st.maxDD >= R.ddBlock ? "r" : st.maxDD >= R.ddHalve ? "y" : "", "Deepest fall in this episode"),
      g("Stop distance", stopDist || 0, open ? f.pctU(stopDist, 1) + " to stop" : "No open stop", 0.15, [], open && stopDist < 0.02 ? "y" : "",
        open ? `Stop at ${f.px(open.stop)} CHF` : `Stop = ${R.stopAtr}× daily volatility below entry`),
    ].join("");
    const why = { LOW: "Within all limits.", MODERATE: "One indicator above its comfort zone.", ELEVATED: "Several indicators are stretched. New positions may be shrunk.",
      HIGH: "Limits are binding. New buys are being reduced or blocked." }[st.risk];
    $("riskStatus").className = "risk-status " + st.risk;
    $("riskStatus").innerHTML = `<span>Risk status</span><b>${st.risk}</b><span>${why}</span>`;
    $("riskLimits").innerHTML = [["Max position", f.pctU(R.maxPosition) + " of equity"], ["Min position", f.pctU(R.minPosition)],
      ["Volatility target", f.pctU(R.targetVol) + " annual"], ["Stop", `${R.stopAtr}× daily vol`], ["Halve size at DD", f.pctU(R.ddHalve)],
      ["Block buys at DD", f.pctU(R.ddBlock)], ["Direction", "Long only"], ["Real orders", "Disabled"]].map(([k, v]) => `<span>${k}</span><b>${v}</b>`).join("");
    const ev = engine.riskEvents.slice(-30).reverse();
    $("riskEvents").innerHTML = ev.length ? ev.map(e => `<li><span class="lamp ${e.level === "high" ? "r" : "y"}"></span><div>${V3.esc(e.text)}<small>${e.ticker} · sim ${e.date} · ${f.time(e.wall)}</small></div></li>`).join("")
      : `<li><span class="lamp g"></span><div>No interventions yet</div></li>`;
  }
  function riskDot(st) { $("riskDot").className = "dot" + (st.risk === "HIGH" ? " r" : st.risk === "ELEVATED" ? " y" : ""); }

  // ------------------------------------------------------------- trades ---
  const COLS = [
    ["id", "#", t => t.id], ["entryDate", "Date", t => t.entryDate], ["ticker", "Asset", t => t.ticker], ["dir", "Direction", () => "LONG"],
    ["entryPrice", "Entry", t => t.entryPrice], ["exitPrice", "Exit", t => t.exitPrice ?? -1], ["pnl", "P&L CHF", t => t.pnl ?? 0],
    ["reward", "Reward", t => t.reward], ["confidence", "Confidence", t => t.confidence], ["version", "Model", t => t.version],
  ];
  let sortKey = "id", sortDir = -1, selTrade = null, miniChart = null;

  function renderTrades() {
    const col = COLS.find(c => c[0] === sortKey), get = col[2];
    const rows = engine.trades.slice(-300).sort((a, b) => { const x = get(a), y = get(b); return (x > y ? 1 : x < y ? -1 : 0) * sortDir; });
    $("tradeTable").innerHTML = `<thead><tr>${COLS.map(([k, l]) => `<th data-k="${k}" class="${k === sortKey ? (sortDir > 0 ? "asc" : "desc") : ""}">${l}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(t => `<tr data-id="${t.id}" class="${selTrade && selTrade.id === t.id ? "sel" : ""}"><td>${t.id}</td><td>${t.entryDate}</td><td>${t.ticker}</td><td>LONG</td>
        <td>${f.px(t.entryPrice)}</td><td>${t.status === "open" ? '<span class="pill open">OPEN</span>' : f.px(t.exitPrice)}</td>
        <td class="${sign(t.pnl)}">${t.pnl == null ? "–" : f.chf(t.pnl)}</td><td class="${sign(t.reward)}">${f.num(t.reward, 2)}</td>
        <td>${f.pctU(t.confidence)}</td><td>${t.version}</td></tr>`).join("") + "</tbody>";
  }

  function inspect(t) {
    selTrade = t;
    const s = engine.market.series[t.ticker], i0 = s.dates.indexOf(t.entryDate), i1 = t.exitDate ? s.dates.indexOf(t.exitDate) : Math.min(i0 + 20, s.dates.length - 1);
    const a = Math.max(0, i0 - 25), b = Math.min(s.dates.length - 1, i1 + 15);
    const pnlPct = t.exitPrice ? t.exitPrice / t.entryPrice - 1 : null;
    $("inspect").innerHTML = `<h4><span>Trade #${t.id} · ${t.ticker}</span><span class="${sign(t.pnl)}">${t.pnl == null ? "OPEN" : f.chf(t.pnl) + " CHF"}</span></h4>
      <p class="fine" style="margin:0">Simulated long trade by ${t.version}. Prices in CHF.</p>
      <div class="mini"><canvas id="chTrade"></canvas></div>
      <div class="kv-list">${[["Entry", `${t.entryDate} @ ${f.px(t.entryPrice)}`], ["Exit", t.exitDate ? `${t.exitDate} @ ${f.px(t.exitPrice)}` : "Still open"],
        ["Exit reason", t.exitReason || "–"], ["Shares", t.shares], ["Size", f.pctU(t.size) + " of equity"], ["Stop", f.px(t.stop)],
        ["Return", f.pct(pnlPct, 2)], ["Reward while held", f.num(t.reward, 3)], ["Confidence at entry", f.pctU(t.confidence)]]
        .map(([k, v]) => `<span>${k}</span><b>${v}</b>`).join("")}</div>
      <h3>Model's selected signals at entry</h3><div class="attr" id="tradeAttr"></div>
      <p class="fine">Linear-score contributions at the moment of the BUY. An approximation of what drove the score, not a causal explanation.</p>`;
    ui.renderAttr($("tradeAttr"), t.reasons || []);
    if (miniChart) miniChart.destroy();
    const labels = s.dates.slice(a, b + 1), px = Array.from(s.close.slice(a, b + 1));
    const mark = (d, p) => labels.map(x => (x === d ? p : null));
    miniChart = new window.Chart($("chTrade"), {
      type: "line",
      data: { labels, datasets: [
        { data: px, borderColor: "#9aa7b8", borderWidth: 1.3, fill: false, tension: 0.2 },
        { data: mark(t.entryDate, t.entryPrice), pointRadius: 5, pointBackgroundColor: GREEN, showLine: false },
        { data: t.exitDate ? mark(t.exitDate, t.exitPrice) : [], pointRadius: 5, pointBackgroundColor: RED, showLine: false },
        { data: labels.map(() => t.stop), borderColor: "rgba(255,107,107,.45)", borderDash: [3, 3], borderWidth: 1, fill: false },
      ] },
      options: { scales: { x: { ticks: { maxTicksLimit: 4, maxRotation: 0 }, grid: { display: false } }, y: { ticks: { maxTicksLimit: 4 }, grid: { color: "rgba(140,170,210,.08)" } } },
        plugins: { tooltip: { enabled: false } } },
    });
    $("tradeTable").querySelectorAll("tbody tr").forEach(tr => tr.classList.toggle("sel", +tr.dataset.id === t.id));
  }

  function initTrades() {
    $("tradeTable").addEventListener("click", e => {
      const th = e.target.closest("th");
      if (th) { const k = th.dataset.k; sortDir = k === sortKey ? -sortDir : (k === "ticker" || k === "version" ? 1 : -1); sortKey = k; renderTrades(); return; }
      const tr = e.target.closest("tbody tr");
      if (tr) { const t = engine.trades.find(x => x.id === +tr.dataset.id); if (t) inspect(t); }
    });
  }

  // --------------------------------------------------------------- init ---
  ui.initTabs = function (eng) {
    engine = eng;
    initTraining(); initBacktest(); initModel(); initTrades();
    const renderActive = tab => ({ training: renderTraining, model: renderModel, risk: renderRisk, trades: renderTrades }[tab] || (() => {}))();
    initTabs(renderActive);
    renderTraining(); renderModel(); renderRisk(); renderTrades();
    runBacktest();

    const ep = ui.batched(() => { if (isOn("training")) renderTraining(); });
    V3.bus.on(E.EPISODE, ep);
    V3.bus.on(E.MODEL, () => { refreshVersions(); if (isOn("model")) renderModel(); });
    V3.bus.on(E.STATUS, () => { if (isOn("model")) renderModel(); });
    setInterval(() => { if (isOn("model")) renderModel(); }, 5000);
    let lastRisk = 0, lastTrades = 0, tradesDirty = false;
    V3.bus.on(E.TRADE, () => { tradesDirty = true; });
    V3.bus.on(E.STEP, ui.batched(st => {
      riskDot(st);
      const now = performance.now();
      if (isOn("risk") && now - lastRisk > 400) { lastRisk = now; renderRisk(); }
      if (isOn("trades") && tradesDirty && now - lastTrades > 700) { lastTrades = now; tradesDirty = false; renderTrades(); }
    }));
    V3.bus.on(E.RISK, () => { if (isOn("risk")) renderRisk(); });
  };
})();
