/* Vanguard3 live hub: a 3D network of the live paper accounts that gets
 * denser every trading day. Built from docs/data/paper.json only.
 *
 *   centre    the V3 mark
 *   agents    the large coloured nodes near the centre; size = account value
 *   markets   the labelled nodes around them, one per watched ticker
 *   specks    one per agent, per day, per market that came close to the
 *             agent's buy rule (a near miss). These pile up into clouds
 *             between an agent and the markets it keeps looking at.
 *   trades    larger dots; agent colour while held, then green or red
 *   lines     solid = position held now, dashed = order for the next open
 *   rings     one per monthly self-review of a learning agent
 *
 * Hovering an agent lights up its part of the network. The slider replays
 * the network day by day since launch.
 */
(function () {
  "use strict";
  const THREE = window.THREE;

  // Market colours, by kind of asset.
  const FUNDS = ["SPY", "QQQ", "IWM", "DIA", "EWL", "VGK", "EWJ", "EEM", "FXI", "INDA", "EWZ",
    "XLK", "XLF", "XLV", "XLE", "XLI", "XLU", "VNQ"];
  const MACRO = ["TLT", "IEF", "LQD", "HYG", "GLD", "SLV", "DBC", "USO"];
  const GROUPS = {
    us: { color: css("--m-us") || "#f17bb4", label: "US stocks" },
    swiss: { color: css("--m-swiss") || "#ff9d5c", label: "Swiss stocks" },
    euro: { color: css("--m-euro") || "#7fd1ff", label: "European stocks" },
    funds: { color: css("--m-funds") || "#a58cf2", label: "index and country funds" },
    macro: { color: css("--m-macro") || "#e9c75a", label: "bonds, metals, commodities" },
  };
  const groupOf = t => GROUPS[/\.SW$/.test(t) ? "swiss" : /\.(DE|PA|AS)$/.test(t) ? "euro"
    : FUNDS.includes(t) ? "funds" : MACRO.includes(t) ? "macro" : "us"];
  const LABELS = 28;          // only the busiest markets get a name tag
  const EDGE = css("--hub-edge") || "#74b0ac";   // the network's thin links, from the page palette
  const BG = new THREE.Color(css("--hub-bg") || "#15181b");

  function label(text, color, size = 22, pill = false) {
    const c = document.createElement("canvas"), g = c.getContext("2d");
    const font = `${pill ? 600 : 500} ${size * 2}px ${css("--hub-font") || '"JetBrains Mono", ui-monospace, monospace'}`;
    g.font = font;
    c.width = Math.ceil(g.measureText(text).width) + (pill ? 40 : 16); c.height = size * 3;
    if (pill) {                                   // dark tag with a coloured edge, readable over the network
      const r = c.height / 2 - 4;
      g.beginPath(); g.roundRect(3, 4, c.width - 6, c.height - 8, r);
      g.fillStyle = css("--hub-pill") || "rgba(12,14,16,0.86)"; g.fill(); g.lineWidth = 4; g.strokeStyle = color; g.stroke();
    }
    g.font = font; g.fillStyle = color; g.textBaseline = "middle"; g.textAlign = "center"; g.fillText(text, c.width / 2, c.height / 2 + 1);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: !pill }));
    if (pill) sp.renderOrder = 10;
    const h = size / 3.4; sp.scale.set(h * c.width / c.height, h, 1);
    return sp;
  }

  /** Soft round glow used behind the agents. */
  let glowTex = null;
  function glow(color, strength) {
    if (!glowTex) {
      const c = document.createElement("canvas"); c.width = c.height = 128;
      const g = c.getContext("2d"), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
      grad.addColorStop(0, "rgba(255,255,255,1)"); grad.addColorStop(0.25, "rgba(255,255,255,.45)"); grad.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
      glowTex = new THREE.CanvasTexture(c);
    }
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity: strength,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    sp.userData.strength = strength;
    return sp;
  }

  /** The V3 logo as one tube, the same single stroke as the 2D mark. */
  function markCurve() {
    const P = (x, y) => new THREE.Vector3((x - 32) / 2.2, (32 - y) / 2.2, 0);
    const path = new THREE.CurvePath();
    const line = (a, b) => path.add(new THREE.LineCurve3(P(...a), P(...b)));
    const bez = (a, b, c, d) => path.add(new THREE.CubicBezierCurve3(P(...a), P(...b), P(...c), P(...d)));
    line([9, 17], [20.5, 47]); line([20.5, 47], [32, 17]); line([32, 17], [52, 17]); line([52, 17], [43, 29.5]);
    bez([43, 29.5], [49.2, 29.5], [53.5, 33.4], [53.5, 38.8]);
    bez([53.5, 38.8], [53.5, 44.3], [49.2, 48], [43.6, 48]);
    bez([43.6, 48], [40.4, 48], [37.8, 46.8], [36, 44.8]);
    return path;
  }

  /** Small deterministic random numbers, so the network looks the same on every visit. */
  function rand(seed) {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    return () => { h = Math.imul(h ^ (h >>> 15), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); h ^= h >>> 16; return (h >>> 0) / 4294967296; };
  }
  function gauss(r) { return Math.sqrt(-2 * Math.log(r() + 1e-9)) * Math.cos(2 * Math.PI * r()); }

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  /** Held-position intervals per agent: [ticker, buyDate, sellDate | null]. */
  function holdings(a) {
    const open = {}, out = [];
    for (const t of a.trades) {
      if (t.side === "BUY") open[t.ticker] = { ticker: t.ticker, buy: t, sell: null };
      else if (open[t.ticker]) { open[t.ticker].sell = t; out.push(open[t.ticker]); delete open[t.ticker]; }
    }
    return out.concat(Object.values(open));
  }

  class Hub {
    constructor(el, data, { onSelect, fmt } = {}) {
      this.el = el; this.data = data; this.onSelect = onSelect || (() => {}); this.fmt = fmt;
      this.dates = data.agents[0].equity.map(p => p[0]);
      this.day = this.dates.length - 1;
      this.colors = { up: css("--up"), down: css("--down"), ink: css("--ink"), muted: css("--muted") };
      this.focus = null;

      const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.outputColorSpace = THREE.SRGBColorSpace;
      el.prepend(r.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(40, 1, 1, 3000);
      this.view = { theta: -Math.PI / 2, phi: 1.15, radius: 200 };
      this.scene.add(new THREE.HemisphereLight("#e6e9ee", css("--hub-bg") || "#1a1d21", 1.2));
      const key = new THREE.DirectionalLight("#ffffff", 1.3); key.position.set(80, 140, 120); this.scene.add(key);

      this.world = new THREE.Group(); this.scene.add(this.world);
      this.layout();
      this.buildCore(); this.buildNodes();
      this.dynamic = new THREE.Group(); this.world.add(this.dynamic);
      this.tip = el.querySelector(".hub-tip");
      this.bindControls(); this.bindBar();
      this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(el); this.resize();
      this.clock = new THREE.Clock();
      this.grow = matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 0;   // 0→1 opening growth
      this.setDay(this.day);
      this.frame = this.frame.bind(this); this.raf = requestAnimationFrame(this.frame);
    }

    /** Agents on an inner ring; markets settle outside, pulled toward the agents that watch them most. */
    layout() {
      const A = [...this.data.agents].sort((a, b) => (a.benchmark - b.benchmark) || a.key.localeCompare(b.key) || (a.fixed_twin - b.fixed_twin));
      const n = A.length, ringR = 34 + 0.1 * Math.max(0, Object.keys(this.data.prices || {}).length - 15);
      this.agentPos = new Map(A.map((a, i) => {
        const ang = -Math.PI / 2 + (i / n) * Math.PI * 2;
        return [a, new THREE.Vector3(Math.cos(ang) * ringR, (i % 2 ? 7 : -7), Math.sin(ang) * ringR)];
      }));
      this.order = A;
      const tickers = Object.keys(this.data.prices || {}).length ? Object.keys(this.data.prices)
        : [...new Set(A.flatMap(a => (a.watch || []).map(w => w.ticker)))];
      // How strongly each agent is tied to each market: near misses + trades.
      const weight = new Map(tickers.map(t => [t, new Map()]));
      for (const a of A) {
        const add = (t, v) => { const m = weight.get(t); if (m) m.set(a, (m.get(a) || 0) + v); };
        (a.scans || []).forEach(([, day]) => Object.entries(day).forEach(([t, p]) => add(t, p)));
        a.trades.forEach(t => add(t.ticker, 4));
        (a.watch || []).forEach(w => add(w.ticker, w.held ? 4 : 0.2));
      }
      const N = tickers.length, extra = Math.max(0, N - 15);
      const R = 76 + 0.2 * extra, bandMax = 84 + 0.22 * extra, yMax = 26 + 0.15 * extra;
      this.extent = bandMax;
      const pos = new Map();
      tickers.forEach((t, i) => {               // start on a Fibonacci sphere
        const y = 1 - (i + 0.5) / N * 2, rr = Math.sqrt(1 - y * y), th = i * Math.PI * (3 - Math.sqrt(5));
        pos.set(t, new THREE.Vector3(Math.cos(th) * rr * R, y * yMax, Math.sin(th) * rr * R));
      });
      const tmp = new THREE.Vector3();
      for (let it = 0; it < 220; it++) {
        for (const t of tickers) {
          const p = pos.get(t), f = new THREE.Vector3();
          let total = 0; weight.get(t).forEach(v => total += v);
          weight.get(t).forEach((v, a) => f.add(tmp.copy(this.agentPos.get(a)).sub(p).multiplyScalar(0.02 * v / (total || 1))));
          for (const u of tickers) if (u !== t) {
            tmp.copy(p).sub(pos.get(u)); const d2 = Math.max(tmp.lengthSq(), 25);
            f.add(tmp.multiplyScalar(260 / d2));
          }
          p.add(f);
          const len = Math.hypot(p.x, p.z);                // keep markets in an outer band
          const target = Math.min(Math.max(len, 62), bandMax);
          p.x *= target / (len || 1); p.z *= target / (len || 1); p.y = Math.max(-yMax, Math.min(yMax + 4, p.y));
        }
      }
      this.tickers = tickers; this.tickerPos = pos;
    }

    buildCore() {
      const mat = new THREE.MeshStandardMaterial({ color: this.colors.ink, roughness: 0.5, metalness: 0.1, emissive: this.colors.ink, emissiveIntensity: 0.18 });
      this.core = new THREE.Mesh(new THREE.TubeGeometry(markCurve(), 260, 1.1, 12, false), mat);
      this.core.scale.setScalar(0.7);
      this.world.add(this.core);
    }

    buildNodes() {
      this.agents = this.order.map(a => {
        const color = new THREE.Color(css("--a-" + a.key) || this.colors.muted);
        const twin = a.fixed_twin;
        // Learners are solid and glowing; fixed twins are a hollow wire shell around a small core.
        const node = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 24),
          new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0.05, emissive: color, emissiveIntensity: twin ? 0.25 : 0.55,
            transparent: true, opacity: 1 }));
        node.userData = { kind: "agent", agent: a };
        const group = new THREE.Group(); group.add(node); this.world.add(group);
        let shell = null;
        if (twin) {
          node.scale.setScalar(0.55);
          shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1, 2),
            new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.9 }));
          shell.userData = { kind: "agent", agent: a };
          group.add(shell);
        }
        const halo = glow(color, twin ? 0.35 : 0.7); group.add(halo);
        const name = twin ? a.name.replace(" (fixed)", "") + " · fixed" : a.name;
        const lab = label(name, "#" + color.getHexString(), twin ? 17 : 21, true); group.add(lab);
        return { a, node, shell, halo, group, lab, color, home: this.agentPos.get(a) };
      });
      this.markets = this.tickers.map(t => {
        const color = new THREE.Color(groupOf(t).color);
        const node = new THREE.Mesh(new THREE.SphereGeometry(1, 28, 16),
          new THREE.MeshStandardMaterial({ color, roughness: 0.5, emissive: color, emissiveIntensity: 0.2 }));
        node.userData = { kind: "market", ticker: t };
        const group = new THREE.Group(); group.add(node); this.world.add(group);
        const lab = label(t, "#" + color.getHexString(), 18); group.add(lab);
        return { t, node, group, lab, color, home: this.tickerPos.get(t) };
      });
    }

    /** Everything that depends on the chosen day. */
    setDay(day) {
      this.day = day;
      const date = this.dates[day], days = day + 1, latest = day === this.dates.length - 1;
      this.dynamic.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
      this.dynamic.clear();
      const k = 1;
      this.core.scale.setScalar((0.55 + 0.08 * Math.log1p(days)) * (0.4 + 0.6 * k));
      const touches = new Map(this.tickers.map(t => [t, 0]));

      const specks = [], links = [], self = this;
      const P = (v) => v.clone().multiplyScalar(k);
      function speck(pos, color, size, info, focusKey) { specks.push({ pos, color, size, info, focusKey }); }
      function link(a, b, color, alpha, focusKey) { links.push({ a, b, color, alpha, focusKey }); }

      for (const g of this.agents) {
        const a = g.a, eq = (a.equity[day] || a.equity[a.equity.length - 1])[1];
        const size = (4.4 * Math.sqrt(eq / this.data.initial_capital_chf) + 0.3 * Math.log1p(days)) * (0.3 + 0.7 * k);
        const home = P(g.home);
        g.group.position.copy(home);
        if (g.shell) { g.shell.scale.setScalar(size); g.node.scale.setScalar(size * 0.45); } else g.node.scale.setScalar(size);
        g.halo.scale.setScalar(size * 6);
        g.lab.position.set(0, size + 4.2, 0);
        g.size = size;
        const key = a.id || a.key;
        link(new THREE.Vector3(), home, g.color, 0.35, key);
        if (a.fixed_twin) {                        // tie each fixed twin to its learning version
          const mate = this.agents.find(o => o.a.key === a.key && !o.a.fixed_twin);
          if (mate) link(home, P(mate.home), g.color, 0.6, key);
        }

        // Near misses: one speck per day per market close to the buy rule.
        const held = holdings(a);
        const isHeld = (t, d) => held.some(h => h.ticker === t && h.buy.date <= d && (!h.sell || d < h.sell.date));
        const tally = new Map();
        (a.scans || []).forEach(([d, picks]) => {
          if (d > date) return;
          Object.entries(picks).forEach(([t, p]) => {
            if (!this.tickerPos.has(t) || isHeld(t, d)) return;
            const r = rand(key + t + d), tp = P(this.tickerPos.get(t));
            // A cloud around the market, on the side facing the agent; nearer when closer to a buy.
            const toward = home.clone().sub(tp).normalize();
            const pos = tp.clone().addScaledVector(toward, 5 + 12 * (1 - p) + 3 * r())
              .add(new THREE.Vector3(gauss(r), gauss(r), gauss(r)).multiplyScalar(2.4 + 2.5 * (1 - p)));
            const col = g.color.clone().lerp(new THREE.Color(css("--hub-dim") || "#7d8791"), p >= 1 ? 0 : 0.45 - 0.4 * p);
            speck(pos, col, p >= 1 ? 0.8 : 0.45 + 0.2 * p, { kind: "scan", agent: a, ticker: t, date: d, p }, key);
            link(pos, tp, EDGE, d === date ? 0.3 : 0.05 + 0.06 * p, key);
            if (d === date) link(home, pos, EDGE, 0.1, key);
            tally.set(t, (tally.get(t) || 0) + 1);
            touches.set(t, touches.get(t) + 1);
          });
        });
        tally.forEach((n, t) => link(home, P(this.tickerPos.get(t)), g.color, Math.min(0.3, 0.025 * n), key));

        // Trades: a dot near the market; agent colour while held, then the result's colour.
        held.forEach(h => {
          if (h.buy.date > date || !this.tickerPos.has(h.ticker)) return;
          const sold = h.sell && h.sell.date <= date;
          const r = rand(key + h.ticker + h.buy.date);
          const tp = P(this.tickerPos.get(h.ticker));
          const pos = home.clone().lerp(tp, 0.78).add(new THREE.Vector3(gauss(r), gauss(r), gauss(r)).multiplyScalar(2));
          const col = sold ? new THREE.Color(h.sell.pnl_chf >= 0 ? this.colors.up : this.colors.down) : g.color;
          speck(pos, col, sold ? 0.85 : 1.3, { kind: "trade", agent: a, buy: h.buy, sell: sold ? h.sell : null }, key);
          if (!sold) { link(home, tp, g.color, 0.85, key); }
          else link(pos, tp, col, 0.35, key);
          touches.set(h.ticker, touches.get(h.ticker) + 3);
        });

        // Orders for the next open: dashed line to the market.
        if (latest) a.pending_orders.forEach(o => {
          if (!this.tickerPos.has(o.ticker)) return;
          const tp = P(this.tickerPos.get(o.ticker));
          const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints([home, tp]),
            new THREE.LineDashedMaterial({ color: g.color, dashSize: 1.6, gapSize: 1.2, transparent: true, opacity: 0.9 }));
          ln.computeLineDistances(); ln.userData.focusKey = key; this.dynamic.add(ln);
          const ball = new THREE.Mesh(new THREE.SphereGeometry(1.4, 14, 10),
            new THREE.MeshBasicMaterial({ color: g.color, wireframe: true, transparent: true, opacity: 0.85 }));
          ball.position.copy(home.clone().lerp(tp, 0.85)); ball.userData = { kind: "order", agent: a, order: o, focusKey: key };
          this.dynamic.add(ball);
        });

        // One ring per monthly review so far.
        (a.learning_log || []).filter(e => e.date <= date).forEach((e, j) => {
          const t = new THREE.Mesh(new THREE.TorusGeometry(size + 1.4 + j * 0.9, 0.1, 6, 64),
            new THREE.MeshBasicMaterial({ color: e.switched ? this.colors.ink : g.color, transparent: true, opacity: 0.75 }));
          t.position.copy(home); t.rotation.x = Math.PI / 2; t.userData.focusKey = key; this.dynamic.add(t);
        });
      }

      // Markets grow with how often the agents look at or trade them; the busiest get a name tag.
      const rank = new Map([...this.markets].sort((a, b) => touches.get(b.t) - touches.get(a.t)).map((m, i) => [m.t, i]));
      for (const m of this.markets) {
        m.lab.visible = this.markets.length <= LABELS || (rank.get(m.t) < LABELS && touches.get(m.t) > 0);
        const s = Math.min(5.5, 1.3 + 0.3 * Math.sqrt(touches.get(m.t))) * (0.3 + 0.7 * k);
        m.group.position.copy(P(m.home)); m.node.scale.setScalar(s); m.lab.position.set(0, s + 3.2, 0); m.size = s;
      }

      // Specks: one instanced mesh, so thousands stay cheap.
      this.specks = specks;
      if (specks.length) {
        const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 7, 5),
          new THREE.MeshStandardMaterial({ roughness: 0.6, emissiveIntensity: 0.3 }), specks.length);
        const m4 = new THREE.Matrix4();
        specks.forEach((s, i) => {
          m4.makeScale(s.size, s.size, s.size).setPosition(s.pos);
          mesh.setMatrixAt(i, m4); mesh.setColorAt(i, s.color);
        });
        mesh.userData.kind = "specks"; this.dynamic.add(mesh); this.speckMesh = mesh;
      } else this.speckMesh = null;

      // Links: one line-segments object with a colour per vertex.
      this.links = links;
      const pos = new Float32Array(links.length * 6), col = new Float32Array(links.length * 6), c = new THREE.Color();
      links.forEach((l, i) => {
        pos.set([l.a.x, l.a.y, l.a.z, l.b.x, l.b.y, l.b.z], i * 6);
      });
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
      this.linkMesh = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9,
        depthWrite: false }));
      this.dynamic.add(this.linkMesh);
      this.paint();

      const bar = this.el.querySelector(".hub-date");
      if (bar) bar.textContent = `day ${days} · ${date} · ${specks.length} points`;
      const slider = this.el.querySelector("input[type=range]");
      if (slider) { slider.max = this.dates.length - 1; slider.value = day; slider.disabled = this.dates.length < 2; }
    }

    /** Colour everything, dimming what is not part of the focused agent. */
    paint() {
      const f = this.focus, dim = (key) => f && key !== f;
      const c = new THREE.Color(), grey = new THREE.Color(css("--hub-off") || "#30353b");
      if (this.speckMesh) {
        this.specks.forEach((s, i) => this.speckMesh.setColorAt(i, dim(s.focusKey) ? grey : s.color));
        this.speckMesh.instanceColor.needsUpdate = true;
      }
      const col = this.linkMesh.geometry.getAttribute("color");
      this.links.forEach((l, i) => {
        // A fainter line is drawn closer to the background colour.
        const k = dim(l.focusKey) ? 0.06 : Math.min(1, 0.3 + (f ? 3.5 : 2.2) * l.alpha);
        c.copy(BG).lerp(new THREE.Color(l.color), k);
        col.array.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
      });
      col.needsUpdate = true;
      for (const g of this.agents) {
        const off = dim(g.a.id || g.a.key);
        g.node.material.opacity = off ? 0.25 : 1;
        if (g.shell) g.shell.material.opacity = off ? 0.2 : 0.9;
        g.halo.material.opacity = off ? 0.05 : g.halo.userData.strength * (f ? 1.4 : 1);
        g.lab.material.opacity = off ? 0.25 : 1;
      }
      this.dynamic.children.forEach(o => {
        if (o.userData.focusKey && o.material) o.material.opacity = dim(o.userData.focusKey) ? 0.1 : 0.85;
      });
    }

    setFocus(key) {
      if (this.focus === key) return;
      this.focus = key; this.paint();
    }

    bindBar() {
      const slider = this.el.querySelector("input[type=range]"), play = this.el.querySelector(".hub-play");
      if (slider) slider.addEventListener("input", () => { this.stopPlay(); this.setDay(+slider.value); });
      if (play) play.addEventListener("click", () => (this.playing ? this.stopPlay() : this.startPlay()));
    }
    startPlay() {
      const play = this.el.querySelector(".hub-play");
      this.playing = true; play.textContent = "pause";
      let d = this.day >= this.dates.length - 1 ? 0 : this.day;
      this.setDay(d);
      this.timer = setInterval(() => {
        if (++d >= this.dates.length) return this.stopPlay();
        this.setDay(d);
      }, Math.max(60, 3000 / this.dates.length));
    }
    stopPlay() {
      clearInterval(this.timer); this.playing = false;
      const play = this.el.querySelector(".hub-play"); if (play) play.textContent = "replay";
    }

    pickAt(e) {
      const el = this.renderer.domElement, r = el.getBoundingClientRect();
      const ray = this.ray || (this.ray = new THREE.Raycaster()), ndc = new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      const targets = [...this.agents.flatMap(g => g.shell ? [g.node, g.shell] : [g.node]), ...this.markets.map(m => m.node),
        ...this.dynamic.children.filter(o => o.userData.kind === "order")];
      if (this.speckMesh) targets.push(this.speckMesh);
      const hit = ray.intersectObjects(targets, false)[0];
      if (!hit) return null;
      if (hit.object === this.speckMesh) return this.specks[hit.instanceId].info;
      return hit.object.userData;
    }

    bindControls() {
      const el = this.renderer.domElement;
      let drag = null, moved = 0;
      el.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY }; moved = 0; el.setPointerCapture(e.pointerId); this.touched = true; });
      el.addEventListener("pointermove", e => {
        if (drag) {
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY }; moved += Math.abs(dx) + Math.abs(dy);
          this.view.theta += dx * 0.006; this.view.phi = Math.min(1.5, Math.max(0.2, this.view.phi - dy * 0.005));
          this.hideTip(); return;
        }
        this.hover(this.pickAt(e), e);
      });
      el.addEventListener("pointerup", e => {
        if (moved < 4) {
          const u = this.pickAt(e);
          if (u && u.agent) this.onSelect(u.agent);
          else if (e.pointerType !== "mouse") this.setFocus(null);
        }
        drag = null;
      });
      el.addEventListener("pointerleave", () => { this.hideTip(); this.setFocus(null); });
      el.addEventListener("wheel", e => {
        e.preventDefault(); this.view.radius = Math.min(520, Math.max(60, this.view.radius * Math.exp(e.deltaY * 0.001)));
      }, { passive: false });
    }

    hover(u, e) {
      this.setFocus(u && u.agent ? (u.agent.id || u.agent.key) : null);
      if (!u || !this.tip) return this.hideTip();
      const f = this.fmt, a = u.agent;
      let html;
      if (u.kind === "agent") {
        const eq = (a.equity[this.day] || a.equity[a.equity.length - 1])[1];
        const n = a.trades.filter(t => t.date <= this.dates[this.day]).length;
        html = `<b>${f.esc(a.name)}</b>${f.chf(eq)} CHF · ${f.pct(eq / this.data.initial_capital_chf - 1, 2)}<br>${n} trade${n === 1 ? "" : "s"} · click for its desk`;
      } else if (u.kind === "market") {
        const near = this.specks.filter(s => s.info.kind === "scan" && s.info.ticker === u.ticker).length;
        const held = this.data.agents.filter(x => x.positions.some(p => p.ticker === u.ticker)).map(x => f.esc(x.name));
        html = `<b>${f.esc(u.ticker)}</b>${near} near miss${near === 1 ? "" : "es"} so far<br>${held.length && this.day === this.dates.length - 1 ? "held by " + held.join(", ") : "not held"}`;
      } else if (u.kind === "scan") {
        html = `<b>${f.esc(u.ticker)} · ${f.esc(a.name)}</b>${u.date}: ${u.p >= 1 ? "buy rule met" : `about ${Math.round(u.p * 100)}% of the way to its buy rule`}`;
      } else if (u.kind === "trade") {
        html = `<b>${f.esc(u.buy.ticker)} · ${f.esc(a.name)}</b>bought ${u.buy.date} at ${u.buy.price.toFixed(2)}<br>` +
          (u.sell ? `sold ${u.sell.date}, ${f.chf(u.sell.pnl_chf)} CHF` : "still held");
      } else html = `<b>${f.esc(u.order.ticker)} · ${f.esc(a.name)}</b>${u.order.side} ${u.order.quantity} at the next open`;
      const r = this.el.getBoundingClientRect();
      this.tip.innerHTML = html; this.tip.hidden = false;
      this.tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 250) + "px"; this.tip.style.top = (e.clientY - r.top + 14) + "px";
      this.renderer.domElement.style.cursor = u.agent ? "pointer" : "";
    }
    hideTip() { if (this.tip) this.tip.hidden = true; this.renderer.domElement.style.cursor = ""; }

    resize() {
      const w = this.el.clientWidth || 1, h = this.el.clientHeight || 1;
      this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
      this.view.radius = (this.extent || 88) * (w / h < 1 ? 2.6 : 2.25);
    }

    frame() {
      this.raf = requestAnimationFrame(this.frame);
      const dt = Math.min(this.clock.getDelta(), 0.05);
      if (this.grow < 1) {                               // opening: the network grows into place
        this.grow = Math.min(1, this.grow + dt / 1.6);
        this.world.scale.setScalar(0.25 + 0.75 * (1 - Math.pow(1 - this.grow, 3)));
      }
      if (!this.touched && !matchMedia("(prefers-reduced-motion: reduce)").matches) this.view.theta += dt * 0.05;
      const v = this.view, c = this.camera;
      c.position.set(v.radius * Math.sin(v.phi) * Math.cos(v.theta), v.radius * Math.cos(v.phi), v.radius * Math.sin(v.phi) * Math.sin(v.theta));
      c.lookAt(0, -2, 0);
      this.core.lookAt(c.position);                      // the mark always faces the viewer
      this.renderer.render(this.scene, c);
    }

    dispose() {
      cancelAnimationFrame(this.raf); this.stopPlay(); this.ro.disconnect();
      this.renderer.dispose(); this.renderer.domElement.remove();
    }
  }

  window.V3Hub = Hub;
})();
