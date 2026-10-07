/* Wiring: load data, pre-train, build the 3D view and the panels, connect
 * the bus, and hand the controls to the user.
 *
 * To drive the lab from your own model, replace `new V3.Engine(market)`
 * with an object that exposes the same methods and emits the same V3.EVENTS.
 */
(function () {
  "use strict";
  const V3 = window.V3, E = V3.EVENTS;
  const $ = id => document.getElementById(id);
  const FLOW_MS = [1500, 420, 360, 330];          // decision-flow animation per speed
  const tick = () => new Promise(r => setTimeout(r, 30));

  async function boot() {
    const msg = t => ($("bootMsg").textContent = t);
    try {
      await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 2000))]);
      await Promise.race([Promise.all(["600 20px 'Saira Semi Condensed'", "700 20px 'Saira Semi Condensed'"].map(x => document.fonts.load(x))),
        new Promise(r => setTimeout(r, 1500))]);
    } catch { /* fonts are cosmetic */ }

    msg("Loading market history…"); await tick();
    const market = await V3.Market.load();
    msg(`Pre-training the agent on ${market.tickers.length} ${market.source === "historical" ? "historical" : "synthetic"} assets (${V3.config.warmupEpisodes} episodes)…`);
    await tick();
    const engine = new V3.Engine(market);
    engine.warmup();
    V3.engine = engine;                                  // handy in the browser console

    msg("Building the network…"); await tick();
    let graph = null;
    try {
      graph = new V3.Graph3D($("stage"), {
        getStatus: id => V3.ui.nodeStatus(id, engine),
        onSelect: id => V3.ui.showNode(id, engine),
        viewRect: visibleStage,
      });
      window.addEventListener("resize", () => graph.resize());
      new MutationObserver(() => setTimeout(() => graph.resize(), 400)).observe(document.body, { attributes: true, attributeFilter: ["class"] });
      graph.onStage = (i, rec) => V3.ui.stage(i, rec);
    } catch (err) {
      console.error(err);
      $("stage").insertAdjacentHTML("beforeend", `<p style="position:absolute;top:45%;width:100%;text-align:center;color:#7f8ea3">3D view unavailable (WebGL is off). The panels still work.</p>`);
    }
    V3.graph = graph;

    V3.ui.init(engine);
    V3.ui.initTabs(engine);
    wireControls(engine, graph);

    if (graph) {
      V3.bus.on(E.DECISION, rec => graph.playDecision(rec));
      V3.bus.on(E.REGIME, reg => graph.setRegime(reg));
      V3.bus.on(E.MODEL, () => { graph.pulse("learning", "#c08cff", 1.4); graph.pulse("monitor", "#5eead4", 1); graph.pulse("agent", "#ffcf7a", 1); });
      V3.bus.on(E.EPISODE, () => graph.pulse("monitor", "#5eead4", 0.8));
      V3.bus.on(E.RISK, e => graph.pulse("risk", e.level === "high" ? "#ff6b6b" : "#ffb454", 1.3));
      V3.bus.on(E.BACKTEST, () => { graph.emit("data", "backtest", { bright: true, speed: 2 }); graph.emit("learning", "backtest", { bright: true, speed: 2 });
        setTimeout(() => graph.emit("backtest", "monitor", { bright: true, speed: 2 }), 500); });
    }

    engine.setSpeed(+(V3.store.get("v3lab-speed") ?? 1));
    engine.tick(1);
    engine.start();
    $("boot").classList.add("gone");
    setTimeout(() => $("boot").remove(), 800);
  }

  /** The part of the stage not hidden behind the floating panels (desktop layout). */
  function visibleStage() {
    if (window.innerWidth <= 900) return null;
    const W = window.innerWidth, H = window.innerHeight;
    const l = document.querySelector(".col.left").getBoundingClientRect(), r = document.querySelector(".col.right").getBoundingClientRect();
    const top = document.querySelector(".top").getBoundingClientRect(), d = $("drawer").getBoundingClientRect();
    const x0 = l.right, x1 = r.left || W, y0 = top.bottom, y1 = Math.min(d.top, H);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 - 36 };
  }

  function wireControls(engine, graph) {
    const play = $("btnPlay");
    const sync = () => {
      play.innerHTML = engine.running ? '<span class="i-pause"></span>' : '<span class="i-play"></span>';
      play.title = engine.running ? "Pause the simulation (space)" : "Resume the simulation (space)";
      document.querySelectorAll("#speed button").forEach((b, i) => b.classList.toggle("on", i === engine.speedIdx));
      if (graph) { graph.setPaused(!engine.running); graph.setFlowDuration(FLOW_MS[engine.speedIdx]); }
    };
    $("speed").innerHTML = engine.speeds.map((s, i) => `<button data-i="${i}" title="${s.steps} session${s.steps > 1 ? "s" : ""} every ${s.interval} ms">${s.label}</button>`).join("");
    $("speed").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { engine.setSpeed(+b.dataset.i); V3.store.set("v3lab-speed", b.dataset.i); } });
    const toggle = () => (engine.running ? engine.pause() : engine.start());
    play.addEventListener("click", toggle);
    V3.bus.on(E.STATUS, sync);

    const rot = $("btnRotate");
    const setRot = on => { rot.classList.toggle("on", on); if (graph) graph.setAutoRotate(on); V3.store.set("v3lab-rotate", on ? "1" : "0"); };
    setRot(V3.store.get("v3lab-rotate") !== "0");
    rot.addEventListener("click", () => setRot(!rot.classList.contains("on")));
    $("btnReset").addEventListener("click", () => { if (graph) graph.resetCamera(); V3.ui.showNode(null, engine); });

    const search = $("search");
    search.addEventListener("input", () => { if (graph) graph.filter(search.value); });
    search.addEventListener("keydown", e => {
      if (e.key === "Enter" && graph) {
        const hits = graph.filter(search.value);
        if (hits && hits.length) { graph.focus(hits[0]); V3.ui.showNode(hits[0], engine); }
      }
      if (e.key === "Escape") { search.value = ""; if (graph) graph.filter(""); search.blur(); }
    });

    $("nodeClose").addEventListener("click", () => { V3.ui.showNode(null, engine); if (graph) graph.select(null); });
    $("nodeFocus").addEventListener("click", () => { const id = V3.ui.shownNode(); if (id && graph) graph.focus(id); });

    document.addEventListener("keydown", e => {
      if (e.target.matches("input, select, textarea")) return;
      if (e.key === " ") { e.preventDefault(); toggle(); }
      else if (e.key === "r" || e.key === "R") setRot(!rot.classList.contains("on"));
      else if (e.key === "0") $("btnReset").click();
      else if (e.key === "/") { e.preventDefault(); search.focus(); }
      else if (e.key === "Escape") $("nodeClose").click();
    });
    sync();
  }

  boot().catch(err => {
    console.error(err);
    $("bootMsg").textContent = "Could not start: " + err.message;
  });
})();
