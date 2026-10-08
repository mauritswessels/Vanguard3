/* Vanguard3 live hub: a 3D picture of the live paper accounts that grows
 * with them. Built from docs/data/paper.json only, so it changes every time
 * the daily run adds a session.
 *
 *   centre   the V3 mark; it grows with the number of sessions traded
 *   nodes    one per account; size follows the account's value
 *   branches one per trade, spiralling out from its account; filled while the
 *            position is open, then a small dot coloured by the result
 *   rings    one per monthly self-review of a learning agent
 *   hollow   orders queued for the next open
 *
 * The slider replays the accounts day by day since launch.
 */
(function () {
  "use strict";
  const THREE = window.THREE;
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));

  function label(text, color, size = 22) {
    const c = document.createElement("canvas"), g = c.getContext("2d");
    const font = `500 ${size * 2}px "JetBrains Mono", ui-monospace, monospace`;
    g.font = font;
    c.width = Math.ceil(g.measureText(text).width) + 16; c.height = size * 3;
    g.font = font; g.fillStyle = color; g.textBaseline = "middle"; g.fillText(text, 8, c.height / 2);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    const h = size / 5.5; sp.scale.set(h * c.width / c.height, h, 1);
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

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  class Hub {
    constructor(el, data, { onSelect, fmt } = {}) {
      this.el = el; this.data = data; this.onSelect = onSelect || (() => {}); this.fmt = fmt;
      this.dates = data.agents[0].equity.map(p => p[0]);
      this.day = this.dates.length - 1;
      this.colors = { up: css("--up"), down: css("--down"), ink: css("--ink"), muted: css("--muted"), line: css("--line") };

      const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.outputColorSpace = THREE.SRGBColorSpace;
      el.prepend(r.domElement);
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(40, 1, 1, 2000);
      this.view = { theta: -Math.PI / 2, phi: 1.1, radius: 150 };
      this.scene.add(new THREE.HemisphereLight("#d9dde2", "#1a1d21", 1.1));
      const key = new THREE.DirectionalLight("#ffffff", 1.4); key.position.set(80, 140, 120); this.scene.add(key);

      this.world = new THREE.Group(); this.scene.add(this.world);
      this.buildCore(); this.buildAgents();
      this.dynamic = new THREE.Group(); this.world.add(this.dynamic);
      this.pickables = [];
      this.tip = el.querySelector(".hub-tip");
      this.bindControls(); this.bindBar();
      this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(el); this.resize();
      this.clock = new THREE.Clock();
      this.grow = matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 0;   // 0→1 opening growth
      this.setDay(this.day);
      this.frame = this.frame.bind(this); this.raf = requestAnimationFrame(this.frame);
    }

    buildCore() {
      const mat = new THREE.MeshStandardMaterial({ color: this.colors.ink, roughness: 0.5, metalness: 0.1, emissive: this.colors.ink, emissiveIntensity: 0.18 });
      this.core = new THREE.Mesh(new THREE.TubeGeometry(markCurve(), 260, 1.25, 12, false), mat);
      this.world.add(this.core);
    }

    buildAgents() {
      const A = this.data.agents, n = A.length;
      // Learner and fixed twin sit side by side; the yardstick closes the ring.
      const order = [...A].sort((a, b) => (a.benchmark - b.benchmark) || a.key.localeCompare(b.key) || (a.fixed_twin - b.fixed_twin));
      this.agents = order.map((a, i) => {
        const color = new THREE.Color(css("--a-" + a.key) || this.colors.muted);
        const ang = -Math.PI / 2 + (i / n) * Math.PI * 2;
        const node = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 24),
          new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.1, transparent: true, opacity: a.fixed_twin ? 0.55 : 1 }));
        node.userData = { kind: "agent", agent: a };
        const group = new THREE.Group(); group.add(node); this.world.add(group);
        const lab = label(a.name.replace(" (fixed)", " · fixed"), "#" + color.getHexString(), 20); group.add(lab);
        const val = label("", this.colors.muted, 18); group.add(val);
        const spoke = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
          new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.35 }));
        this.world.add(spoke);
        return { a, ang, node, group, lab, val, spoke, color };
      });
    }

    /** Everything that depends on the chosen day. */
    setDay(day) {
      this.day = day;
      const date = this.dates[day], days = day + 1;
      this.dynamic.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
      this.dynamic.clear(); this.pickables = [];
      const k = 1 - Math.pow(1 - this.grow, 3);       // eased opening growth
      const ring = (46 + 9 * Math.log1p(days)) * (0.35 + 0.65 * k);
      this.core.scale.setScalar((0.7 + 0.12 * Math.log1p(days)) * (0.4 + 0.6 * k));

      for (const g of this.agents) {
        const a = g.a, eq = (a.equity[day] || a.equity[a.equity.length - 1])[1];
        const size = (3.2 * Math.sqrt(eq / this.data.initial_capital_chf) + 0.35 * Math.log1p(days)) * (0.3 + 0.7 * k);
        const pos = new THREE.Vector3(Math.cos(g.ang) * ring, (a.benchmark ? -6 : 0) * k, Math.sin(g.ang) * ring);
        g.group.position.copy(pos); g.node.scale.setScalar(size);
        g.lab.position.set(0, -size - 3.2, 0); g.val.position.set(0, -size - 6.4, 0);
        g.spoke.geometry.setFromPoints([new THREE.Vector3(), pos]);
        const trades = a.trades.filter(t => t.date <= date);
        g.spoke.material.opacity = Math.min(0.75, 0.22 + 0.04 * trades.length);
        this.setValueLabel(g, eq);

        // Branches: one per buy, spiralling outward in trade order.
        const buys = trades.filter(t => t.side === "BUY");
        buys.forEach((t, i) => {
          const sell = trades.find(s => s.side === "SELL" && s.ticker === t.ticker && s.date >= t.date && trades.indexOf(s) > trades.indexOf(t));
          const open = !sell;
          const ang = g.ang + i * GOLDEN, dist = size + 5 + 3 * Math.sqrt(i + 1);
          const p = pos.clone().add(new THREE.Vector3(Math.cos(ang) * dist, (i % 5 - 2) * 1.1, Math.sin(ang) * dist).multiplyScalar(k));
          const r = open ? 0.6 + 0.8 * Math.sqrt(t.value_chf / this.data.initial_capital_chf * 10) : 0.5;
          const col = open ? g.color : new THREE.Color(sell.pnl_chf >= 0 ? this.colors.up : this.colors.down);
          const m = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 10), new THREE.MeshStandardMaterial({ color: col, roughness: 0.7 }));
          m.position.copy(p); m.userData = { kind: "trade", agent: a, buy: t, sell };
          this.dynamic.add(m); this.pickables.push(m);
          this.dynamic.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([pos, p]),
            new THREE.LineBasicMaterial({ color: g.color, transparent: true, opacity: open ? 0.45 : 0.18 })));
        });

        // Queued orders (only meaningful on the latest day).
        if (day === this.dates.length - 1) a.pending_orders.forEach((o, j) => {
          const ang = g.ang + (buys.length + j) * GOLDEN, dist = size + 6 + 2.2 * Math.sqrt(buys.length + j + 1);
          const p = pos.clone().add(new THREE.Vector3(Math.cos(ang) * dist, 2, Math.sin(ang) * dist));
          const m = new THREE.Mesh(new THREE.SphereGeometry(1.3, 16, 10),
            new THREE.MeshBasicMaterial({ color: g.color, wireframe: true, transparent: true, opacity: 0.8 }));
          m.position.copy(p); m.userData = { kind: "order", agent: a, order: o };
          this.dynamic.add(m); this.pickables.push(m);
          const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints([pos, p]),
            new THREE.LineDashedMaterial({ color: g.color, dashSize: 1, gapSize: 1, transparent: true, opacity: 0.6 }));
          ln.computeLineDistances(); this.dynamic.add(ln);
        });

        // One ring per monthly review so far.
        (a.learning_log || []).filter(e => e.date <= date).forEach((e, j) => {
          const t = new THREE.Mesh(new THREE.TorusGeometry(size + 1.6 + j * 1.1, 0.12, 6, 64),
            new THREE.MeshBasicMaterial({ color: e.switched ? this.colors.ink : g.color, transparent: true, opacity: 0.7 }));
          t.position.copy(pos); t.rotation.x = Math.PI / 2; this.dynamic.add(t);
        });
        this.pickables.push(g.node);
      }
      const bar = this.el.querySelector(".hub-date");
      if (bar) bar.textContent = `day ${days} · ${date}`;
      const slider = this.el.querySelector("input[type=range]");
      if (slider) { slider.max = this.dates.length - 1; slider.value = day; slider.disabled = this.dates.length < 2; }
    }

    setValueLabel(g, eq) {
      const text = this.fmt.chf(eq) + "  " + this.fmt.pct(eq / this.data.initial_capital_chf - 1, 2);
      if (g.val.userData.text === text) return;
      g.group.remove(g.val); g.val.material.map.dispose();
      const pos = g.val.position.clone();
      g.val = label(text, this.colors.muted, 16); g.val.userData.text = text; g.val.position.copy(pos); g.group.add(g.val);
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
      }, Math.max(60, 2400 / this.dates.length));
    }
    stopPlay() {
      clearInterval(this.timer); this.playing = false;
      const play = this.el.querySelector(".hub-play"); if (play) play.textContent = "replay";
    }

    bindControls() {
      const el = this.renderer.domElement, ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
      let drag = null, moved = 0;
      const pick = e => {
        const r = el.getBoundingClientRect();
        ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
        ray.setFromCamera(ndc, this.camera);
        const hit = ray.intersectObjects(this.pickables, false)[0];
        return hit ? hit.object.userData : null;
      };
      el.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY }; moved = 0; el.setPointerCapture(e.pointerId); this.touched = true; });
      el.addEventListener("pointermove", e => {
        if (drag) {
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY }; moved += Math.abs(dx) + Math.abs(dy);
          this.view.theta += dx * 0.006; this.view.phi = Math.min(1.5, Math.max(0.25, this.view.phi - dy * 0.005));
          this.hideTip(); return;
        }
        this.hover(pick(e), e);
      });
      el.addEventListener("pointerup", e => {
        if (moved < 4) { const u = pick(e); if (u) this.onSelect(u.agent); }
        drag = null;
      });
      el.addEventListener("pointerleave", () => this.hideTip());
      el.addEventListener("wheel", e => {
        e.preventDefault(); this.view.radius = Math.min(420, Math.max(70, this.view.radius * Math.exp(e.deltaY * 0.001)));
      }, { passive: false });
    }

    hover(u, e) {
      if (!u || !this.tip) return this.hideTip();
      const f = this.fmt, a = u.agent;
      let html;
      if (u.kind === "agent") {
        const eq = (a.equity[this.day] || a.equity[a.equity.length - 1])[1];
        const n = a.trades.filter(t => t.date <= this.dates[this.day]).length;
        html = `<b>${f.esc(a.name)}</b>${f.chf(eq)} CHF · ${f.pct(eq / this.data.initial_capital_chf - 1, 2)}<br>${n} trade${n === 1 ? "" : "s"} · click for its desk`;
      } else if (u.kind === "trade") {
        html = `<b>${f.esc(u.buy.ticker)} · ${f.esc(a.name)}</b>bought ${u.buy.date} at ${u.buy.price.toFixed(2)}<br>` +
          (u.sell ? `sold ${u.sell.date}, ${f.chf(u.sell.pnl_chf)} CHF` : "still held");
      } else html = `<b>${f.esc(u.order.ticker)} · ${f.esc(a.name)}</b>${u.order.side} ${u.order.quantity} at the next open`;
      const r = this.el.getBoundingClientRect();
      this.tip.innerHTML = html; this.tip.hidden = false;
      this.tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 250) + "px"; this.tip.style.top = (e.clientY - r.top + 14) + "px";
      this.renderer.domElement.style.cursor = "pointer";
    }
    hideTip() { if (this.tip) this.tip.hidden = true; this.renderer.domElement.style.cursor = ""; }

    resize() {
      const w = this.el.clientWidth || 1, h = this.el.clientHeight || 1;
      this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
      this.view.radius = w / h < 1 ? 225 : 150;
    }

    frame() {
      this.raf = requestAnimationFrame(this.frame);
      const dt = Math.min(this.clock.getDelta(), 0.05);
      if (this.grow < 1) {                               // opening: the hub grows into place
        this.grow = Math.min(1, this.grow + dt / 1.6);
        this.setDay(this.day);
      }
      if (!this.touched && !matchMedia("(prefers-reduced-motion: reduce)").matches) this.view.theta += dt * 0.05;
      const v = this.view, c = this.camera;
      c.position.set(v.radius * Math.sin(v.phi) * Math.cos(v.theta), v.radius * Math.cos(v.phi), v.radius * Math.sin(v.phi) * Math.sin(v.theta));
      c.lookAt(0, -14, 0);
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
