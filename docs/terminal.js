/* Vanguard3 research terminal: Leaderboard, Agent analysis, Trades, Risk and
   Performance tabs of the live page, plus the "at a glance" strip on the
   Overview. Every number comes from V3Metrics (metrics.js) over paper.json;
   every reason shown is the text the agent recorded when it decided. */
(function () {
  "use strict";
  const M = window.V3Metrics;

  const TABS = [["overview", "Overview"], ["leaderboard", "Leaderboard"], ["analysis", "Agent analysis"],
    ["trades", "Trades"], ["risk", "Risk"], ["performance", "Performance"]];

  /** What each agent's signal score means (it ranks competing buys). */
  const SCORE = {
    trend: ["ADX trend strength", v => v.toFixed(1)],
    reversion: ["RSI points below its entry level", v => v.toFixed(1)],
    volatility: ["ATRs above the breakout level", v => v.toFixed(2)],
    learner: ["model score, BUY minus HOLD", v => (v >= 0 ? "+" : "") + v.toFixed(3)],
    news: ["target weight Claude chose", v => (v * 100).toFixed(1) + "%"],
  };

  let X;                                   // helpers handed over by index.html
  const st = { tview: "positions", agent: "all", asset: "all", side: "all", outcome: "all", status: "all", q: "", limit: 60,
    sort: "ret", mode: "return", hidden: new Set(), a: null, b: null, scope: "all" };

  // ---------- small formatters ----------
  const ok = v => typeof v === "number" && isFinite(v);
  const NA = (why = "Insufficient data") => `<span class="na" title="${why}">Insufficient data</span>`;
  const dash = `<span class="faint">–</span>`;
  const P = (v, d = 1) => ok(v) ? `<span class="${X.cls(v)}">${X.pct(v, d)}</span>` : dash;
  const C = v => ok(v) ? `<span class="${X.cls(v)}">${(v >= 0 ? "+" : "") + X.chf.format(v)}</span>` : dash;
  const C0 = v => ok(v) ? X.chf.format(v) : dash;
  const R = v => ok(v) ? v.toFixed(2) : dash;
  const price = (v, t, d) => ok(v) ? `${v.toFixed(2)} <span class="faint">${X.esc(d.currencies[t] || "")}</span>` : dash;
  const dateS = s => s ? X.fmtDate(X.ts(s)) : "–";
  const typeOf = a => a.benchmark ? "Benchmark" : a.fixed_twin ? "Fixed rules" : a.ai
    ? (a.ai.kind === "news" ? "AI · Claude news" : "AI · daily learner") : a.learning ? "Learning · monthly" : "Fixed rules";
  const agentCell = a => `<div class="agent-name">${X.sw(a)}<div style="min-width:0">${X.esc(a.name)}<small>${typeOf(a)}</small></div></div>`;
  const byId = (d, id) => d.agents.find(a => a.id === id);

  // ---------- range ----------
  function loadRange() {
    try { return JSON.parse(X.store.get("v3-range")) || { kind: "all" }; } catch { return { kind: "all" }; }
  }
  function rangeNow(d) { const s = loadRange(); return M.range(s.kind, d, s); }

  function timeBar(d) {
    const s = loadRange(), r = M.range(s.kind, d, s);
    return `<div class="timebar" role="group" aria-label="Time range">
      ${M.RANGES.map(([k, l]) => `<button type="button" data-range="${k}" aria-pressed="${k === r.kind}">${l}</button>`).join("")}
      <span class="custom" ${r.kind === "custom" ? "" : "hidden"}>
        <input type="date" data-from value="${X.esc(s.from || d.start)}" min="${d.start}" max="${d.last}" aria-label="From">
        <span class="faint">to</span>
        <input type="date" data-to value="${X.esc(s.to || d.last)}" min="${d.start}" max="${d.last}" aria-label="To"></span>
      <span class="faint range-note">${r.kind === "today" ? "Values are recorded once per trading day, so today = the last 24 hours = the latest session."
        : `Showing ${X.esc(r.label)}.`}</span></div>`;
  }

  function bindTimeBar(el, rerender) {
    el.querySelectorAll("[data-range]").forEach(b => b.addEventListener("click", () => {
      const s = loadRange(); s.kind = b.dataset.range; X.store.set("v3-range", JSON.stringify(s)); rerender();
    }));
    el.querySelectorAll("[data-from],[data-to]").forEach(i => i.addEventListener("change", () => {
      const s = loadRange(); s.kind = "custom";
      s.from = el.querySelector("[data-from]").value || null; s.to = el.querySelector("[data-to]").value || null;
      X.store.set("v3-range", JSON.stringify(s)); rerender();
    }));
  }

  // ---------- chart helper ----------
  function chart(canvas, datasets, yFmt, extra = {}) {
    const o = X.baseOptions(yFmt);
    const xs = datasets.flatMap(ds => ds.data.map(p => p.x));
    if (xs.length) { o.scales.x.min = Math.min(...xs); o.scales.x.max = Math.max(...xs); }
    if (extra.tooltip) o.plugins.tooltip.callbacks.label = extra.tooltip;
    if (extra.zoom && window.ChartZoom) {
      o.plugins.zoom = { zoom: { drag: { enabled: true, backgroundColor: "rgba(232,228,220,.07)", borderColor: "rgba(232,228,220,.3)", borderWidth: 1 },
        pinch: { enabled: !!window.Hammer }, mode: "x" }, limits: { x: { minRange: 2 * 864e5 } } };
    }
    if (extra.onClick) o.onClick = extra.onClick;
    if (datasets.every(ds => ds.data.length < 3)) datasets.forEach(ds => { ds.pointRadius = 3; });
    const c = new Chart(canvas, { type: "line", data: { datasets }, options: o });
    X.addChart(c); return c;
  }
  const ds = (a, pairs, extra = {}) => Object.assign(X.series(pairs, a.key, a.name, X.lineStyle(a)), extra);

  // ======================================================================
  // Overview strip
  // ======================================================================
  function overviewHtml(d) {
    const r = M.range("all", d), S = M.all(d, r), al = M.alerts(d, r);
    const day = d.agents.map(a => {
      const e = a.equity; if (e.length < 1) return null;
      const prev = e.length > 1 ? e[e.length - 2][1] : d.initial_capital_chf;
      return { a, chg: e[e.length - 1][1] - prev, pct: e[e.length - 1][1] / prev - 1 };
    }).filter(Boolean).sort((x, y) => y.pct - x.pct);
    const fills = d.agents.flatMap(a => a.trades.map(t => ({ a, t }))).sort((x, y) =>
      x.t.date === y.t.date ? y.t.id - x.t.id : x.t.date < y.t.date ? 1 : -1).slice(0, 8);
    const trips = d.agents.flatMap(a => (a.trips || []).filter(t => t.status === "open" || t.exit_date >= M.addDays(d.last, -29)).map(t => ({ a, t })))
      .sort((x, y) => y.t.pnl_chf - x.t.pnl_chf);
    const wl = trips.length ? [...trips.slice(0, 3), ...trips.slice(3).slice(-3).filter(x => x.t.pnl_chf < 0)] : [];
    const alertList = al.length ? al.map(alertHtml).join("") : `<p class="empty">No warnings. Every account is within the limits listed on the Risk tab.</p>`;
    return `<section class="glance"><div class="section-head"><h2>At a glance</h2>
        <span class="muted">${S.filter(s => !byId(d, s.id).benchmark).length} agents and 1 benchmark · last close ${dateS(d.last)}</span></div>
      <div class="glance-grid">
        <div><h3 class="h-sm">Latest session</h3><div class="mini">${day.map(x => `<div class="mini-row"><span class="agent-name">${X.sw(x.a)}${X.esc(x.a.name)}</span>
          <span class="num">${C(x.chg)}</span><span class="num">${P(x.pct, 2)}</span></div>`).join("")}</div></div>
        <div><h3 class="h-sm">Risk alerts</h3>${alertList}
          <h3 class="h-sm" style="margin-top:14px">Biggest winners and losers <span class="faint">(open, or closed in 30 days)</span></h3>
          ${wl.length ? `<div class="mini">${wl.map(x => `<div class="mini-row"><span class="agent-name">${X.sw(x.a)}<b class="tick">${X.esc(x.t.ticker)}</b>
            <span class="faint">${x.t.status}</span></span><span class="num">${C(x.t.pnl_chf)}</span><span class="num">${P(x.t.pnl_pct)}</span></div>`).join("")}</div>`
            : `<p class="empty">No positions yet.</p>`}</div>
        <div><h3 class="h-sm">Latest trades</h3>${fills.length ? `<div class="mini">${fills.map(({ a, t }) => `<div class="mini-row">
          <span class="agent-name">${X.sw(a)}<span class="side ${t.side}">${t.side}</span><b class="tick">${X.esc(t.ticker)}</b></span>
          <span class="num">${t.quantity} @ ${t.price.toFixed(2)}</span><span class="faint num">${dateS(t.date)}</span></div>`).join("")}</div>`
          : `<p class="empty">No trades yet. The first fills come at the next market open.</p>`}</div>
      </div></section>`;
  }

  function alertHtml(x) {
    return `<div class="alert ${x.level}"><b>${X.esc(x.kind)}</b> ${X.esc(x.text)}</div>`;
  }

  // ======================================================================
  // Leaderboard
  // ======================================================================
  const SORTS = [["ret", "Total return"], ["pnl", "P&L"], ["sharpe", "Sharpe ratio"], ["winRate", "Win rate"],
    ["maxDD", "Max drawdown"], ["fills", "Number of trades"]];

  function leaderboard(el, d) {
    const r = rangeNow(d), S = M.all(d, r);
    const players = S.filter(s => !byId(d, s.id).benchmark), bench = S.filter(s => byId(d, s.id).benchmark);
    const key = st.sort, val = s => key === "sharpe" && !s.enough ? NaN : s[key];
    players.sort((x, y) => (ok(val(y)) ? val(y) : -Infinity) - (ok(val(x)) ? val(x) : -Infinity));
    const avg = players.reduce((n, s) => n + s.ret, 0) / players.length;
    const row = (s, rank) => {
      const a = byId(d, s.id), diff = s.ret - avg;
      return `<tr class="${rank === 1 ? "lead" : ""} ${a.benchmark ? "ref" : ""}" style="--c:${X.color(a.key)}">
        <td class="rk num">${rank || "Ref"}</td><td>${agentCell(a)}</td>
        <td class="num">${C0(s.value)}</td><td class="num faint">${C0(s.start)}</td>
        <td class="num"><b>${P(s.ret, 2)}</b></td><td class="num">${C(s.pnl)}</td>
        <td class="num">${C(s.realized)}</td><td class="num">${s.unrealized == null ? dash : C(s.unrealized)}</td>
        <td class="num">${s.fills}</td><td class="num">${s.closed ? `${Math.round(s.winRate * 100)}% <span class="faint">of ${s.closed}</span>` : dash}</td>
        <td class="num">${ok(s.avgWin) ? `${C(s.avgWin)}` : dash}</td><td class="num">${ok(s.avgLoss) ? C(s.avgLoss) : dash}</td>
        <td class="num">${s.maxDD < 0 ? P(s.maxDD) : "0.0%"}</td>
        <td class="num">${s.enough ? R(s.sharpe) : NA(`Needs ${M.MIN_RETURNS} trading days; has ${s.returns}`)}</td>
        <td class="num">${C0(s.book.cash)}</td><td class="num">${Math.round(s.book.exposure * 100)}%</td>
        <td class="num">${a.benchmark ? "" : `<span class="vs ${diff >= 0 ? "up" : "down"}" title="Return minus the average of the ${players.length} agents">
          ${diff >= 0 ? "▲" : "▼"} ${Math.abs(diff * 100).toFixed(2)} pts</span>`}</td></tr>`;
    };
    el.innerHTML = `${timeBar(d)}
      <section><div class="section-head"><h2>Leaderboard</h2>
        <label class="muted">Rank by <select id="lb-sort">${SORTS.map(([k, l]) => `<option value="${k}" ${k === key ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
        <div class="tbl-wrap"><table class="dense lb"><thead><tr><th>#</th><th>Agent</th><th class="r">Value CHF</th><th class="r">Start</th>
          <th class="r">Return</th><th class="r">P&amp;L</th><th class="r">Realized</th><th class="r">Unrealized</th><th class="r">Trades</th>
          <th class="r">Win rate</th><th class="r">Avg win</th><th class="r">Avg loss</th><th class="r">Max DD</th><th class="r">Sharpe</th>
          <th class="r">Cash</th><th class="r">Invested</th><th class="r">vs average</th></tr></thead>
          <tbody>${players.map((s, i) => row(s, i + 1)).join("")}${bench.map(s => row(s, 0)).join("")}</tbody></table></div>
        <p class="notice small">Value is at the last close (${dateS(d.last)}). Start is the value just before the range begins
          (${C0(d.initial_capital_chf)} CHF at launch). Trades counts every buy and sell fill; win rate, average win and loss count closed positions
          (all fees included). Unrealized is only known for the latest close. "vs average" compares each return with the average of the
          ${players.length} agents (${P(avg, 2)}). Ref = buy and hold SPY, the yardstick.</p></section>`;
    el.querySelector("#lb-sort").addEventListener("change", e => { st.sort = e.target.value; leaderboard(el, d); });
    bindTimeBar(el, () => leaderboard(el, d));
  }

  // ======================================================================
  // Trades
  // ======================================================================
  function decisionHtml(dec, a, d, title) {
    if (!dec) return `<div class="dec"><h4>${title}</h4><p class="faint">No decision was recorded for this fill.</p></div>`;
    const det = dec.details || {}, sc = SCORE[a.key];
    const when = dec.time === "midday" ? `midday check on ${dateS(dec.date)}` : `close of ${dateS(dec.date)}`;
    const parts = [`<div class="kvs"><span>Stated reason</span><b>${X.esc(dec.reason || "–")}</b></div>`];
    if (dec.check) parts.push(`<div class="kvs"><span>Its rule with that day's values</span><span>${X.esc(dec.check)}</span></div>`);
    if (dec.score != null && sc) parts.push(`<div class="kvs"><span>Signal strength</span><span class="num">${sc[1](dec.score)} <span class="faint">(${sc[0]})</span></span></div>`);
    if (det.model_scores) parts.push(`<div class="kvs"><span>Model scores</span><span class="num">${Object.entries(det.model_scores)
      .map(([k, v]) => `${k} ${v.toFixed(3)}`).join(" · ")}</span></div>`);
    if (det.explored) parts.push(`<div class="kvs"><span>Exploration</span><span>A deliberate random try, so the model can learn from it.</span></div>`);
    if (det.factors) parts.push(`<div class="kvs"><span>Biggest factors</span><span>${det.factors.map(f =>
      `${X.esc(f.feature)} (${f.effect >= 0 ? "for" : "against"}, ${f.effect.toFixed(3)})`).join(" · ")}</span></div>`);
    if (det.target_weight != null) parts.push(`<div class="kvs"><span>Target weight</span><span class="num">${(det.target_weight * 100).toFixed(1)}% of the account</span></div>`);
    if (det.market_view) parts.push(`<div class="kvs"><span>Claude's market view</span><span>“${X.esc(det.market_view)}”</span></div>`);
    if (det.quarterly) parts.push(`<div class="kvs"><span>Quarterly results read</span><span>${X.esc(det.quarterly)}</span></div>`);
    if (det.headlines && det.headlines.length) parts.push(`<div class="kvs"><span>Headlines read</span><ul class="heads">${det.headlines.map(h => `<li>${X.esc(h)}</li>`).join("")}</ul></div>`);
    if (dec.stop != null) parts.push(`<div class="kvs"><span>Stop set at decision</span><span class="num">${dec.stop.toFixed(2)}</span></div>`);
    return `<div class="dec"><h4>${title} <span class="faint">decided at the ${when}</span></h4>${parts.join("")}</div>`;
  }

  function fillLine(t, d) {
    return `<tr><td class="num">${dateS(t.date)} <span class="faint">${t.session === "midday" ? "midday" : "open"}</span></td>
      <td><span class="side ${t.side}">${t.side}</span></td><td class="num">${t.quantity}</td><td class="num">${price(t.price, t.ticker, d)}</td>
      <td class="num faint">${t.market_price.toFixed(2)}</td><td class="num">${C0(t.value_chf)}</td><td class="num">${X.chf2.format(t.fees_chf)}</td>
      <td class="num">${t.pnl_chf == null ? dash : C(t.pnl_chf)}</td></tr>`;
  }

  function tripCard(a, t, d) {
    const fills = t.fills.map(i => a.trades.find(x => x.id === i)).filter(Boolean);
    const pos = a.positions.find(p => p.ticker === t.ticker);
    const watch = (a.watch || []).find(w => w.held && w.ticker === t.ticker);
    const stop = t.entry && t.entry.stop != null ? t.entry.stop.toFixed(2) : null;
    const risk = [
      `<div class="kvs"><span>Position size at entry</span><span class="num">${(t.size_pct * 100).toFixed(1)}% of the account</span></div>`,
      `<div class="kvs"><span>Stop-loss</span><span>${stop ? `${stop} at entry` : "None set by this agent"}${t.status === "open" && pos && pos.stop != null ? `; trailing stop now ${pos.stop.toFixed(2)}` : ""}</span></div>`,
      `<div class="kvs"><span>Take-profit</span><span>No fixed target; it sells when its exit rule triggers</span></div>`,
      t.status === "open" && watch ? `<div class="kvs"><span>Exit rule now</span><span>${X.esc(watch.note)}</span></div>` : "",
      `<div class="kvs"><span>Confidence</span><span class="faint">Not produced by this agent</span></div>`,
    ].join("");
    const pnlCls = t.pnl_chf >= 0 ? "win" : "loss";
    return `<details class="trip ${t.status} ${pnlCls}" style="--c:${X.color(a.key)}"><summary>
      <span class="num faint">${dateS(t.entry_date)}</span>
      <span class="agent-name">${X.sw(a)}<span class="nm">${X.esc(a.name)}</span></span>
      <b class="tick">${X.esc(t.ticker)}</b>
      <span class="tag st-${t.status}">${t.status === "open" ? "OPEN" : "CLOSED"}</span>
      <span class="num">${price(t.entry_price, t.ticker, d)} → ${t.exit_price == null ? `<span class="faint">open</span>` : price(t.exit_price, t.ticker, d)}</span>
      <span class="num">${t.quantity} sh · ${(t.size_pct * 100).toFixed(1)}%</span>
      <span class="num">${C(t.pnl_chf)} ${P(t.pnl_pct)}</span>
      <span class="num faint">${t.holding_days}d</span></summary>
      <div class="trip-body">
        <div class="grid-dec">${decisionHtml(t.entry, a, d, "Entry")}${t.status === "closed" ? decisionHtml(t.exit, a, d, "Exit")
          : `<div class="dec"><h4>Exit</h4><p class="faint">Still open. Valued at the last close: ${C0(t.value_chf)} CHF, ${C(t.unrealized_chf)} unrealized.</p></div>`}
          <div class="dec"><h4>Risk</h4>${risk}</div></div>
        <div class="tbl-wrap"><table class="dense"><thead><tr><th>Fill</th><th>Side</th><th class="r">Qty</th><th class="r">Price paid</th>
          <th class="r">Market</th><th class="r">Value CHF</th><th class="r">Fees CHF</th><th class="r">Realised P&amp;L</th></tr></thead>
          <tbody>${fills.map(f => fillLine(f, d)).join("")}</tbody></table></div>
      </div></details>`;
  }

  function fillCard(a, t, d) {
    return `<details class="trip" style="--c:${X.color(a.key)}"><summary>
      <span class="num faint">${dateS(t.date)}</span>
      <span class="agent-name">${X.sw(a)}<span class="nm">${X.esc(a.name)}</span></span>
      <b class="tick">${X.esc(t.ticker)}</b><span class="side ${t.side}">${t.side}</span>
      <span class="num">${t.quantity} @ ${price(t.price, t.ticker, d)}</span>
      <span class="num">${C0(t.value_chf)} CHF</span>
      <span class="num">${t.pnl_chf == null ? "" : C(t.pnl_chf)}</span>
      <span class="faint">${t.session === "midday" ? "midday" : "at the open"}</span></summary>
      <div class="trip-body"><div class="grid-dec">${decisionHtml(t.decision, a, d, t.side === "BUY" ? "Buy" : "Sell")}</div>
        <div class="tbl-wrap"><table class="dense"><tbody>${fillLine(t, d)}</tbody></table></div></div></details>`;
  }

  const text = (...xs) => xs.filter(Boolean).join(" ").toLowerCase();
  const decText = dec => dec ? text(dec.reason, dec.check, ...((dec.details || {}).headlines || []), (dec.details || {}).market_view) : "";

  function trades(el, d) {
    const r = rangeNow(d), q = st.q.trim().toLowerCase();
    const agents = d.agents.filter(a => st.agent === "all" || a.id === st.agent);
    const tickers = [...new Set(d.agents.flatMap(a => a.trades.map(t => t.ticker)))].sort();
    let items, total;
    if (st.tview === "positions") {
      items = agents.flatMap(a => M.tripsTouching(a, r).map(t => ({ a, t })))
        .filter(({ a, t }) => (st.asset === "all" || t.ticker === st.asset)
          && (st.status === "all" || t.status === st.status)
          && (st.outcome === "all" || (st.outcome === "win" ? t.pnl_chf > 0 : t.pnl_chf < 0))
          && (!q || text(a.name, t.ticker, decText(t.entry), decText(t.exit)).includes(q)))
        .sort((x, y) => x.t.entry_date < y.t.entry_date ? 1 : -1);
    } else {
      items = agents.flatMap(a => a.trades.filter(t => M.inRange(t.date, r)).map(t => ({ a, t })))
        .filter(({ a, t }) => (st.asset === "all" || t.ticker === st.asset) && (st.side === "all" || t.side === st.side)
          && (st.outcome === "all" || (t.side === "SELL" && (st.outcome === "win" ? t.pnl_chf > 0 : t.pnl_chf < 0)))
          && (!q || text(a.name, t.ticker, t.reason, decText(t.decision)).includes(q)))
        .sort((x, y) => x.t.date === y.t.date ? y.t.id - x.t.id : x.t.date < y.t.date ? 1 : -1);
    }
    total = items.length;
    const opt = (v, l, cur) => `<option value="${X.esc(v)}" ${v === cur ? "selected" : ""}>${X.esc(l)}</option>`;
    el.innerHTML = `${timeBar(d)}
      <section><div class="section-head"><h2>Trade log</h2>
        <div class="chips sub-nav" role="group" aria-label="Show">
          <button type="button" data-tv="positions" aria-pressed="${st.tview === "positions"}">Positions (entry to exit)</button>
          <button type="button" data-tv="fills" aria-pressed="${st.tview === "fills"}">Every fill</button></div></div>
        <div class="filters">
          <select data-f="agent" aria-label="Agent">${opt("all", "All agents", st.agent)}${d.agents.map(a => opt(a.id, a.name, st.agent)).join("")}</select>
          <select data-f="asset" aria-label="Asset">${opt("all", "All assets", st.asset)}${tickers.map(t => opt(t, t, st.asset)).join("")}</select>
          ${st.tview === "fills" ? `<select data-f="side" aria-label="Side">${opt("all", "Buys and sells", st.side)}${opt("BUY", "Buys", st.side)}${opt("SELL", "Sells", st.side)}</select>`
            : `<select data-f="status" aria-label="Open or closed">${opt("all", "Open and closed", st.status)}${opt("open", "Open", st.status)}${opt("closed", "Closed", st.status)}</select>`}
          <select data-f="outcome" aria-label="Outcome">${opt("all", "Winners and losers", st.outcome)}${opt("win", "Winners", st.outcome)}${opt("loss", "Losers", st.outcome)}</select>
          <input type="search" data-f="q" value="${X.esc(st.q)}" placeholder="Search tickers, reasons, headlines" aria-label="Search">
          <span class="faint">${total} ${st.tview === "positions" ? "position" : "fill"}${total === 1 ? "" : "s"}</span></div>
        <div class="trips">${items.slice(0, st.limit).map(({ a, t }) => st.tview === "positions" ? tripCard(a, t, d) : fillCard(a, t, d)).join("")
          || `<p class="empty">${d.agents.some(a => a.trades.length) ? "Nothing matches these filters." : "No trades yet. The first fills arrive at the next market open."}</p>`}</div>
        ${total > st.limit ? `<button type="button" class="more" data-more>Show ${Math.min(60, total - st.limit)} more</button>` : ""}
        <p class="notice small">Every reason, rule value, score and headline is what the agent recorded when it decided; nothing is written
          afterwards. No agent here produces a confidence percentage, so none is shown. The platform is long only (no shorts or covers).
          Prices are in each market's own currency; values, fees and P&amp;L in CHF include commission, slippage and the currency spread.</p></section>`;
    const rerender = () => trades(el, d);
    el.querySelectorAll("[data-tv]").forEach(b => b.addEventListener("click", () => { st.tview = b.dataset.tv; st.limit = 60; rerender(); }));
    el.querySelectorAll("select[data-f]").forEach(s => s.addEventListener("change", () => { st[s.dataset.f] = s.value; st.limit = 60; rerender(); }));
    const search = el.querySelector("input[data-f=q]");
    let timer; search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => {
      st.q = search.value; st.limit = 60; rerender(); const s = el.querySelector("input[data-f=q]"); s.focus(); s.setSelectionRange(s.value.length, s.value.length);
    }, 250); });
    const more = el.querySelector("[data-more]"); if (more) more.addEventListener("click", () => { st.limit += 60; rerender(); });
    bindTimeBar(el, rerender);
  }

  // ======================================================================
  // Performance
  // ======================================================================
  function performance(el, d) {
    const r = rangeNow(d), S = M.all(d, r), mode = st.mode;
    const fmtY = mode === "return" ? v => (v * 100).toFixed(1) + "%" : v => X.chf.format(v);
    const list = S.slice().sort((x, y) => y.ret - x.ret);
    el.innerHTML = `${timeBar(d)}
      <section><div class="section-head"><h2>Equity curves</h2>
        <div class="chips sub-nav" role="group" aria-label="Measure">${[["value", "Portfolio value"], ["return", "Total return %"], ["pnl", "P&L"]]
          .map(([k, l]) => `<button type="button" data-mode="${k}" aria-pressed="${k === mode}">${l}</button>`).join("")}</div></div>
        <div class="legend">${d.agents.map(a => `<button type="button" data-hide="${a.id}" aria-pressed="${!st.hidden.has(a.id)}" class="${st.hidden.has(a.id) ? "off" : ""}">${X.sw(a)}${X.esc(a.name)}</button>`).join("")}
          <button type="button" data-all>Show all</button>${window.ChartZoom ? `<button type="button" data-reset>Reset zoom</button>` : ""}</div>
        <div class="perf-grid">
          <div class="chart-box tall"><canvas id="t-perf" aria-label="Equity curves"></canvas></div>
          <div class="perf-side">${list.map(s => { const a = byId(d, s.id); return `<div class="ps-row ${st.hidden.has(a.id) ? "off" : ""}">
            <span class="agent-name">${X.sw(a)}${X.esc(a.name)}</span><span class="num"><b>${P(s.ret, 2)}</b></span>
            <span class="num faint">${C0(s.value)}</span></div>`; }).join("")}</div></div>
        <p class="notice small">${window.ChartZoom ? "Drag across the chart to zoom into a period. " : ""}Click a point to list the trades made around that day.
          Hover to read each account's value and return. Solid = learning or AI agents, dashed = fixed twins, grey dashed = buy and hold SPY.</p>
        <div id="t-near"></div></section>
      <section><div class="section-head"><h2>Drop from previous high</h2><span class="muted">deep or long dips = large drawdowns</span></div>
        <div class="chart-box short"><canvas id="t-dd" aria-label="Drawdowns"></canvas></div></section>
      <section><div class="section-head"><h2>Consistency</h2><span class="muted">${X.esc(r.label)}</span></div>
        <div class="tbl-wrap"><table class="dense"><thead><tr><th>Agent</th><th class="r">Return</th><th class="r">Volatility (a year)</th>
          <th class="r">Sharpe</th><th class="r">Max drawdown</th><th class="r">Up days</th><th class="r">Best day</th><th class="r">Worst day</th></tr></thead>
          <tbody>${list.map(s => { const a = byId(d, s.id), rets = dailyRets(a, d, r);
            return `<tr><td>${agentCell(a)}</td><td class="num">${P(s.ret, 2)}</td>
            <td class="num">${s.enough ? P(s.vol).replace("+", "") : NA(`Needs ${M.MIN_RETURNS} trading days; has ${s.returns}`)}</td>
            <td class="num">${s.enough ? R(s.sharpe) : NA(`Needs ${M.MIN_RETURNS} trading days; has ${s.returns}`)}</td>
            <td class="num">${s.maxDD < 0 ? P(s.maxDD) : "0.0%"}</td>
            <td class="num">${rets.length ? Math.round(rets.filter(x => x > 0).length / rets.length * 100) + "%" : dash}</td>
            <td class="num">${rets.length ? P(Math.max(...rets), 2) : dash}</td><td class="num">${rets.length ? P(Math.min(...rets), 2) : dash}</td></tr>`; }).join("")}</tbody></table></div></section>`;

    const shown = d.agents.filter(a => !st.hidden.has(a.id));
    const base = {};
    const sets = shown.map(a => { const w = M.windowOf(a, d, r); base[a.name] = w.base; return ds(a, M.curve(a, d, r, mode)); });
    const c = chart(el.querySelector("#t-perf"), sets, fmtY, {
      zoom: true,
      tooltip: ctx => {
        const b = base[ctx.dataset.label], y = ctx.parsed.y;
        const v = mode === "value" ? y : mode === "pnl" ? b + y : b * (1 + y);
        return ` ${ctx.dataset.label}: ${X.chf.format(v)} CHF (${X.pct(v / b - 1, 2)})`;
      },
      onClick: (evt, _els, ch) => near(el, d, ch.scales.x.getValueForPixel(evt.x)),
    });
    chart(el.querySelector("#t-dd"), shown.map(a => ds(a, M.drawdownCurve(a, d, r))), v => (v * 100).toFixed(0) + "%");
    el.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => { st.mode = b.dataset.mode; X.clearCharts(); performance(el, d); }));
    el.querySelectorAll("[data-hide]").forEach(b => b.addEventListener("click", () => {
      st.hidden.has(b.dataset.hide) ? st.hidden.delete(b.dataset.hide) : st.hidden.add(b.dataset.hide); X.clearCharts(); performance(el, d);
    }));
    el.querySelector("[data-all]").addEventListener("click", () => { st.hidden.clear(); X.clearCharts(); performance(el, d); });
    const reset = el.querySelector("[data-reset]"); if (reset) reset.addEventListener("click", () => c.resetZoom());
    bindTimeBar(el, () => { X.clearCharts(); performance(el, d); });
  }

  function dailyRets(a, d, r) {
    const w = M.windowOf(a, d, r), v = [w.base, ...w.pts.map(p => p[1])], out = [];
    for (let i = 1; i < v.length; i++) out.push(v[i] / v[i - 1] - 1);
    return out;
  }

  function near(el, d, ms) {
    if (!isFinite(ms)) return;
    const day = new Date(ms).toISOString().slice(0, 10), from = M.addDays(day, -3), to = M.addDays(day, 3);
    const rows = d.agents.filter(a => !st.hidden.has(a.id)).flatMap(a => a.trades.filter(t => t.date >= from && t.date <= to).map(t => ({ a, t })))
      .sort((x, y) => x.t.date < y.t.date ? -1 : 1);
    el.querySelector("#t-near").innerHTML = `<div class="near"><h3 class="h-sm">Trades from ${dateS(from)} to ${dateS(to)}</h3>
      ${rows.length ? rows.map(({ a, t }) => `<div class="mini-row"><span class="agent-name">${X.sw(a)}${X.esc(a.name)}</span>
        <span><span class="side ${t.side}">${t.side}</span> <b class="tick">${X.esc(t.ticker)}</b> ${t.quantity} @ ${t.price.toFixed(2)}</span>
        <span class="faint num">${dateS(t.date)} · ${X.esc(t.reason)}</span></div>`).join("") : `<p class="empty">No trades in those days.</p>`}</div>`;
  }

  // ======================================================================
  // Risk
  // ======================================================================
  function risk(el, d) {
    const r = rangeNow(d), S = M.all(d, r), al = M.alerts(d, r), L = M.LIMITS;
    const accts = st.scope === "all" ? d.agents : d.agents.filter(a => a.id === st.scope);
    const ex = M.exposure(accts, d);
    const largest = accts.flatMap(a => a.positions.map(p => ({ a, p, pct: p.value_chf / M.book(a).value }))).sort((x, y) => y.p.value_chf - x.p.value_chf).slice(0, 10);
    const bars = (rows, total) => rows.length ? rows.map(x => `<div class="hbar"><span>${X.esc(x.name)}</span>
      <span class="hb"><i style="width:${Math.min(100, x.pct * 100)}%"></i></span><span class="num">${(x.pct * 100).toFixed(1)}%</span></div>`).join("")
      : `<p class="empty">Nothing invested${total ? "" : " yet"}.</p>`;
    const needs = s => `Needs ${M.MIN_RETURNS} trading days; has ${s.returns}`;
    el.innerHTML = `${timeBar(d)}
      <section><div class="section-head"><h2>Warnings</h2><span class="muted">checked on every account in ${X.esc(r.label)}</span></div>
        ${al.length ? `<div class="alerts">${al.map(alertHtml).join("")}</div>` : `<p class="empty">No warnings right now.</p>`}
        <p class="notice small">Limits: one position above ${L.concentration * 100}% of an account; ${-L.drawdown * 100}% or more below its peak;
          volatility above ${L.volMultiple}× the middle of the other accounts (needs ${M.MIN_RETURNS} trading days); under ${L.lowCash * 100}% cash.</p></section>
      <section><div class="section-head"><h2>Risk by agent</h2></div>
        <div class="tbl-wrap"><table class="dense"><thead><tr><th>Agent</th><th class="r">Max DD</th><th class="r">Now from peak</th>
          <th class="r">Volatility</th><th class="r">Sharpe</th><th class="r">Win rate</th><th class="r">Avg win</th><th class="r">Avg loss</th>
          <th class="r">Profit factor</th><th class="r">Largest loss</th><th class="r">Largest gain</th><th class="r">Avg hold</th>
          <th class="r">Open</th><th class="r">Cash</th><th class="r">Invested</th><th class="r">Largest position</th><th class="r" title="1 divided by the sum of squared position weights: how many equal-sized positions the book is worth">Effective positions</th></tr></thead>
          <tbody>${S.map(s => { const a = byId(d, s.id), b = s.book; return `<tr><td>${agentCell(a)}</td>
            <td class="num">${s.maxDD < 0 ? P(s.maxDD) : "0.0%"}</td><td class="num">${s.curDD < 0 ? P(s.curDD) : "0.0%"}</td>
            <td class="num">${s.enough ? (s.vol * 100).toFixed(1) + "%" : NA(needs(s))}</td><td class="num">${s.enough ? R(s.sharpe) : NA(needs(s))}</td>
            <td class="num">${s.closed ? Math.round(s.winRate * 100) + "%" : NA("No closed positions in this range")}</td>
            <td class="num">${P(s.avgWinPct)}</td><td class="num">${P(s.avgLossPct)}</td>
            <td class="num">${s.profitFactor === Infinity ? "no losses" : ok(s.profitFactor) ? s.profitFactor.toFixed(2) : dash}</td>
            <td class="num">${s.largestLoss ? `${C(s.largestLoss.pnl_chf)} <span class="faint">${X.esc(s.largestLoss.ticker)}</span>` : dash}</td>
            <td class="num">${s.largestGain ? `${C(s.largestGain.pnl_chf)} <span class="faint">${X.esc(s.largestGain.ticker)}</span>` : dash}</td>
            <td class="num">${ok(s.avgHoldDays) ? s.avgHoldDays.toFixed(1) + "d" : dash}</td><td class="num">${b.open}</td>
            <td class="num">${Math.round(b.cashPct * 100)}%</td><td class="num">${Math.round(b.exposure * 100)}%</td>
            <td class="num">${b.largest ? `${(b.largest.pct * 100).toFixed(1)}% <span class="faint">${X.esc(b.largest.ticker)}</span>` : dash}</td>
            <td class="num">${b.effective ? b.effective.toFixed(1) : dash}</td></tr>`; }).join("")}</tbody></table></div>
        <p class="notice small">Volatility is the yearly size of daily swings; Sharpe is return per unit of that swing above a 0.5% risk-free rate.
          Both need ${M.MIN_RETURNS} trading days in the range. Win rate, averages, profit factor (gains ÷ losses), largest gain and loss and
          holding time use positions closed in the range. Cash, invested share and position sizes are the book at the last close.</p></section>
      <section><div class="section-head"><h2>Exposure</h2>
        <label class="muted">Accounts <select id="rk-scope"><option value="all">All accounts combined</option>${d.agents.map(a =>
          `<option value="${a.id}" ${a.id === st.scope ? "selected" : ""}>${X.esc(a.name)}</option>`).join("")}</select></label></div>
        <div class="kv"><div><span class="eyebrow">Long</span><b class="num">${(ex.long * 100).toFixed(1)}%</b></div>
          <div><span class="eyebrow">Short</span><b class="num">0.0%</b></div>
          <div><span class="eyebrow">Cash</span><b class="num">${(ex.cashPct * 100).toFixed(1)}%</b></div>
          <div><span class="eyebrow">Value</span><b class="num">${C0(ex.total)} CHF</b></div></div>
        <div class="grid2">
          <div><h3 class="h-sm">By asset</h3>${bars(ex.byAsset.slice(0, 15), ex.long)}</div>
          <div><h3 class="h-sm">By region and asset class <span class="faint">(no sector data in this platform)</span></h3>${bars(ex.byGroup, ex.long)}
            <h3 class="h-sm" style="margin-top:14px">Largest positions</h3>${largest.length ? `<div class="mini">${largest.map(x => `<div class="mini-row">
              <span class="agent-name">${X.sw(x.a)}<b class="tick">${X.esc(x.p.ticker)}</b></span><span class="num">${C0(x.p.value_chf)} CHF</span>
              <span class="num">${(x.pct * 100).toFixed(1)}% <span class="faint">of ${X.esc(x.a.name)}</span></span></div>`).join("")}</div>` : `<p class="empty">No positions.</p>`}</div>
        </div></section>
      <section><div class="section-head"><h2>Invested share over time</h2><span class="muted">positions ÷ account value at each close</span></div>
        <div class="chart-box short"><canvas id="t-exp" aria-label="Invested share over time"></canvas></div></section>`;
    chart(el.querySelector("#t-exp"), d.agents.map(a => ds(a, M.exposureSeries(a, d, r))), v => Math.round(v * 100) + "%");
    el.querySelector("#rk-scope").addEventListener("change", e => { st.scope = e.target.value; X.clearCharts(); risk(el, d); });
    bindTimeBar(el, () => { X.clearCharts(); risk(el, d); });
  }

  // ======================================================================
  // Agent vs agent
  // ======================================================================
  function analysis(el, d) {
    const r = rangeNow(d);
    const ids = d.agents.map(a => a.id);
    if (!ids.includes(st.a)) st.a = ids[0];
    if (!ids.includes(st.b) || st.b === st.a) st.b = ids.find(i => i !== st.a);
    const A = byId(d, st.a), B = byId(d, st.b), sA = M.stats(A, d, r), sB = M.stats(B, d, r);
    const sel = (k, cur) => `<select data-pick="${k}">${d.agents.map(a => `<option value="${a.id}" ${a.id === cur ? "selected" : ""}>${X.esc(a.name)}</option>`).join("")}</select>`;
    // [label, value fn, format fn, which is better: 1 higher, -1 lower, 0 neither]
    const vol = s => s.enough ? s.vol : NaN, sh = s => s.enough ? s.sharpe : NaN;
    const rows = [
      ["Return", s => s.ret, v => P(v, 2), 1], ["P&L (CHF)", s => s.pnl, C, 1],
      ["Sharpe ratio", sh, R, 1], ["Volatility (a year)", vol, v => ok(v) ? (v * 100).toFixed(1) + "%" : NA(), -1],
      ["Max drawdown", s => s.maxDD, v => v < 0 ? P(v) : "0.0%", 1], ["Now below peak", s => s.curDD, v => v < 0 ? P(v) : "0.0%", 1],
      ["Win rate", s => s.closed ? s.winRate : NaN, v => ok(v) ? Math.round(v * 100) + "%" : dash, 1],
      ["Closed positions", s => s.closed, v => String(v), 0], ["Trades (fills)", s => s.fills, v => String(v), 0],
      ["Trades per week", s => s.perWeek, v => ok(v) ? v.toFixed(1) : dash, 0],
      ["Avg win", s => s.avgWinPct, v => P(v), 1], ["Avg loss", s => s.avgLossPct, v => P(v), 1],
      ["Profit factor", s => s.profitFactor, v => v === Infinity ? "no losses" : R(v), 1],
      ["Avg position size", s => s.avgSize, v => ok(v) ? (v * 100).toFixed(1) + "%" : dash, 0],
      ["Avg invested share", s => s.avgExposure, v => ok(v) ? Math.round(v * 100) + "%" : dash, 0],
      ["Avg holding period", s => s.avgHoldDays, v => ok(v) ? v.toFixed(1) + " days" : dash, 0],
      ["Open positions now", s => s.book.open, v => String(v), 0],
      ["Largest position now", s => s.book.largest ? s.book.largest.pct : NaN, v => ok(v) ? (v * 100).toFixed(1) + "%" : dash, 0],
    ];
    const mark = (va, vb, dir) => !dir || !ok(va) || !ok(vb) || va === vb ? ["", ""]
      : (dir > 0 ? va > vb : va < vb) ? ["best", ""] : ["", "best"];
    const table = rows.map(([l, f, fmt, dir]) => { const va = f(sA), vb = f(sB), [ca, cb] = mark(va, vb, dir);
      return `<tr><td>${l}</td><td class="num ${ca}">${fmt(va)}</td><td class="num ${cb}">${fmt(vb)}</td></tr>`; }).join("");
    const assets = (a) => { const xs = M.assets(a, r);
      const top = xs.slice().sort((x, y) => y.fills - x.fills).slice(0, 5), best = xs.filter(x => x.pnl > 0).sort((x, y) => y.pnl - x.pnl).slice(0, 3),
        worst = xs.filter(x => x.pnl < 0).sort((x, y) => x.pnl - y.pnl).slice(0, 3);
      const li = (arr, f) => arr.length ? arr.map(f).join("") : `<span class="faint">none yet</span>`;
      return `<div class="asset-box">${X.sw(a)}<b>${X.esc(a.name)}</b>
        <div><span class="eyebrow">Most traded</span>${li(top, x => `<span class="chip">${X.esc(x.ticker)} <span class="faint">${x.fills}</span></span>`)}</div>
        <div><span class="eyebrow">Best</span>${li(best, x => `<span class="chip">${X.esc(x.ticker)} ${C(x.pnl)}</span>`)}</div>
        <div><span class="eyebrow">Worst</span>${li(worst, x => `<span class="chip">${X.esc(x.ticker)} ${C(x.pnl)}</span>`)}</div></div>`; };
    el.innerHTML = `${timeBar(d)}
      <section><div class="section-head"><h2>Agent vs agent</h2><div class="vs-pick">${sel("a", st.a)}<span class="faint">vs</span>${sel("b", st.b)}</div></div>
        <div class="grid2">
          <div class="tbl-wrap"><table class="dense cmp"><thead><tr><th></th><th class="r">${X.sw(A)} ${X.esc(A.name)}</th><th class="r">${X.sw(B)} ${X.esc(B.name)}</th></tr></thead>
            <tbody>${table}</tbody></table>
            <p class="notice small">A dot marks the better value where "better" is clear. Volatility and Sharpe need ${M.MIN_RETURNS} trading days in the range.</p></div>
          <div style="display:grid;gap:14px;align-content:start"><div class="summary"><h3 class="h-sm">Summary <span class="faint">(written from the numbers on this page)</span></h3>
            ${M.compareSummary(sA, sB, r).map(x => `<p>${X.esc(x)}</p>`).join("")}</div>
            ${assets(A)}${assets(B)}</div></div></section>
      <section><div class="section-head"><h2>Return over the range</h2></div><div class="chart-box short"><canvas id="t-cmp-eq"></canvas></div>
        <span class="eyebrow">Drop from previous high</span><div class="chart-box short"><canvas id="t-cmp-dd"></canvas></div></section>`;
    chart(el.querySelector("#t-cmp-eq"), [A, B].map(a => ds(a, M.curve(a, d, r, "return"))), v => (v * 100).toFixed(1) + "%");
    chart(el.querySelector("#t-cmp-dd"), [A, B].map(a => ds(a, M.drawdownCurve(a, d, r))), v => (v * 100).toFixed(0) + "%");
    el.querySelectorAll("[data-pick]").forEach(s => s.addEventListener("change", () => {
      st[s.dataset.pick] = s.value; if (st.a === st.b) st[s.dataset.pick === "a" ? "b" : "a"] = ids.find(i => i !== s.value);
      X.clearCharts(); analysis(el, d);
    }));
    bindTimeBar(el, () => { X.clearCharts(); analysis(el, d); });
  }

  // ======================================================================
  window.V3Terminal = {
    TABS,
    init(helpers) { X = helpers; },
    overviewHtml,
    render(tab, el, d) {
      ({ leaderboard, analysis, trades, risk, performance })[tab](el, d);
    },
  };
})();
