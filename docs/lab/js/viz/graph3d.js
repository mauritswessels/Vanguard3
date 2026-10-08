/* Visualization layer · the 3D component network.
 *
 * Plain three.js (r160): a small 3D force layout, custom orbit / zoom / pan
 * controls, node dragging, hover and click picking, glowing nodes, link
 * particles, and the animated 9-stage decision flow. It knows nothing about
 * trading; the UI feeds it decisions and status text.
 */
(function () {
  "use strict";
  const V3 = window.V3;
  const THREE = window.THREE;

  function glowTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"), grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.18, "rgba(255,255,255,.55)");
    grd.addColorStop(0.45, "rgba(255,255,255,.12)"); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }

  function textSprite(text, { size = 26, color = "#cfd8e3", weight = 500, font = "JetBrains Mono", spacing = 0 } = {}) {
    const c = document.createElement("canvas"), g = c.getContext("2d");
    const label = text;
    g.font = `${weight} ${size * 2}px "${font}", "Arial Narrow", sans-serif`;
    const w = Math.ceil(g.measureText(label).width + label.length * spacing * 2 + 24);
    c.width = w; c.height = size * 3;
    g.font = `${weight} ${size * 2}px "${font}", "Arial Narrow", sans-serif`;
    g.fillStyle = color; g.textBaseline = "middle";
    let x = 12;
    for (const ch of label) { g.fillText(ch, x, c.height / 2); x += g.measureText(ch).width + spacing * 2; }
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, fog: false }));
    sp.scale.set(w / c.height * 5.6, 5.6, 1);
    sp.userData.aspect = w / c.height;
    return sp;
  }

  class Graph3D {
    constructor(container, { getStatus, onSelect, viewRect } = {}) {
      this.el = container; this.getStatus = getStatus || (() => ""); this.onSelect = onSelect || (() => {});
      this.viewRect = viewRect || null; this.fitR = 270; this.fitted = false;
      this.onStage = () => {};
      this.autoRotate = true; this.paused = false; this.energy = 1; this.flowDuration = 1500;
      this.selected = null; this.filterSet = null; this.particles = []; this.pulses = [];
      this.flowBusy = false; this.clock = new THREE.Clock();

      const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
      r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
      r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.NoToneMapping;
      container.appendChild(r.domElement);

      const scene = this.scene = new THREE.Scene();
      this.bg = new THREE.Color("#0f1113");
      scene.background = this.bg.clone();
      scene.fog = new THREE.FogExp2(this.bg.clone(), 0.0016);
      this.camera = new THREE.PerspectiveCamera(48, 1, 1, 3000);
      this.view = { theta: 0.6, phi: 1.18, radius: 270, target: new THREE.Vector3() };
      this.tween = null; this.follow = null;

      scene.add(new THREE.HemisphereLight("#7d93b8", "#0a0e14", 0.55));
      const key = new THREE.DirectionalLight("#cfe0ff", 1.1);
      key.position.set(60, 220, 90); key.castShadow = true;
      key.shadow.mapSize.set(1024, 1024);
      Object.assign(key.shadow.camera, { left: -170, right: 170, top: 170, bottom: -170, near: 10, far: 500 });
      key.shadow.radius = 6; scene.add(key);
      this.coreLight = new THREE.PointLight("#e8e4dc", 25, 260, 1); scene.add(this.coreLight);

      const floor = new THREE.Mesh(new THREE.PlaneGeometry(1400, 1400), new THREE.ShadowMaterial({ opacity: 0.38 }));
      floor.rotation.x = -Math.PI / 2; floor.position.y = -78; floor.receiveShadow = true; scene.add(floor);
      const grid = new THREE.GridHelper(1400, 70, "#1b2a3d", "#101a27");
      grid.position.y = -77.9; grid.material.transparent = true; grid.material.opacity = 0.45; scene.add(grid);
      this.addDust();

      this.glowTex = glowTexture();
      this.buildGraph();
      this.bindControls();
      new ResizeObserver(() => this.resize()).observe(container);
      this.resize();
      this.loop = this.loop.bind(this);
      requestAnimationFrame(this.loop);
    }

    addDust() {
      const n = 900, pos = new Float32Array(n * 3), rnd = V3.rng(3);
      for (let i = 0; i < n; i++) {
        const r = 120 + 420 * rnd(), t = rnd() * Math.PI * 2, p = Math.acos(2 * rnd() - 1);
        pos.set([r * Math.sin(p) * Math.cos(t), r * Math.cos(p) * 0.6, r * Math.sin(p) * Math.sin(t)], i * 3);
      }
      const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      this.dust = new THREE.Points(geo, new THREE.PointsMaterial({ color: "#4f6280", size: 1.3, transparent: true, opacity: 0.5, depthWrite: false }));
      this.scene.add(this.dust);
    }

    buildGraph() {
      const rnd = V3.rng(5);
      this.nodes = V3.NODES.map(def => {
        const color = new THREE.Color(V3.CAT_COLORS[def.cat]);
        const core = def.cat === "core";
        const group = new THREE.Group();
        const mat = new THREE.MeshStandardMaterial({ color: color.clone().multiplyScalar(core ? 0.3 : 0.22), emissive: color,
          emissiveIntensity: core ? 0.75 : 0.6, roughness: 0.35, metalness: 0.2, transparent: true });
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(def.size, 48, 32), mat);
        mesh.castShadow = true; group.add(mesh);
        const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color, transparent: true, opacity: core ? 0.95 : 0.6,
          blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
        glow.scale.setScalar(def.size * (core ? 6.5 : 5)); group.add(glow);
        const hit = new THREE.Mesh(new THREE.SphereGeometry(def.size * 1.7, 12, 8), new THREE.MeshBasicMaterial({ visible: false }));
        group.add(hit);
        const label = textSprite(def.name, { size: core ? 30 : 24, color: core ? "#e8e4dc" : "#9aa1a8", weight: 500 });
        label.position.y = -(def.size + (core ? 9 : 6.5));
        if (core) label.scale.multiplyScalar(1.45);
        group.add(label);
        const extras = [];
        if (core) {
          const ico = new THREE.Mesh(new THREE.IcosahedronGeometry(def.size * 1.35, 1),
            new THREE.MeshBasicMaterial({ color: "#e8e4dc", wireframe: true, transparent: true, opacity: 0.16 }));
          group.add(ico); extras.push(ico);
          [1.9, 2.35].forEach((k, j) => {
            const ring = new THREE.Mesh(new THREE.TorusGeometry(def.size * k, 0.18, 8, 160),
              new THREE.MeshBasicMaterial({ color: j ? "#a99bd6" : "#d3a75f", transparent: true, opacity: 0.55 }));
            ring.rotation.x = Math.PI / 2 + (j ? 0.5 : -0.3); group.add(ring); extras.push(ring);
          });
        }
        const pos = core ? new THREE.Vector3() : new THREE.Vector3((rnd() - 0.5) * 160, (rnd() - 0.5) * 120, (rnd() - 0.5) * 160);
        group.position.copy(pos);
        this.scene.add(group);
        hit.userData.nodeId = def.id;
        return { ...def, color, group, mesh, glow, hit, label, extras, vel: new THREE.Vector3(), fixed: core, pulse: 0, pulseColor: color.clone(), dim: 1 };
      });
      this.byId = Object.fromEntries(this.nodes.map(n => [n.id, n]));
      this.links = V3.LINKS.map(([a, b]) => {
        const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
        const c = this.byId[a].color.clone().lerp(this.byId[b].color, 0.5);
        const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: 0.28, depthWrite: false }));
        this.scene.add(line);
        return { a: this.byId[a], b: this.byId[b], line, color: c, acc: Math.random() };
      });
      this.linkIndex = Object.fromEntries(this.links.map(l => [l.a.id + ">" + l.b.id, l]));
      // Settle the layout before the first frame.
      for (let i = 0; i < 400; i++) this.physics(1);

      // Decision label above the core.
      this.decisionSprite = null;
    }

    // --------------------------------------------------------- physics --
    physics(dt) {
      const N = this.nodes;
      for (let i = 0; i < N.length; i++) for (let j = i + 1; j < N.length; j++) {
        const d = new THREE.Vector3().subVectors(N[i].group.position, N[j].group.position);
        const dist2 = Math.max(d.lengthSq(), 25), f = 5200 / dist2;
        d.normalize().multiplyScalar(f * dt);
        N[i].vel.add(d); N[j].vel.sub(d);
      }
      for (const l of this.links) {
        const d = new THREE.Vector3().subVectors(l.b.group.position, l.a.group.position);
        const len = d.length() || 1, rest = 40 + l.a.size + l.b.size;
        const f = (len - rest) * 0.018 * dt;
        d.multiplyScalar(f / len);
        l.a.vel.add(d); l.b.vel.sub(d);
      }
      for (const n of N) {
        n.vel.addScaledVector(n.group.position, -0.0025 * dt);
        n.vel.y -= n.group.position.y * 0.0016 * dt;                // keep the cloud slightly flat
        n.vel.multiplyScalar(0.82);
        if (n.fixed || n === this.dragging) { n.vel.set(0, 0, 0); continue; }
        if (n.vel.length() > 6) n.vel.setLength(6);
        n.group.position.addScaledVector(n.vel, dt);
      }
    }

    // -------------------------------------------------------- controls --
    bindControls() {
      const el = this.renderer.domElement, ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
      const pointers = new Map(); let mode = null, start = null, moved = 0, pinch = 0, downNode = null;
      const plane = new THREE.Plane(), hitPoint = new THREE.Vector3(), offset = new THREE.Vector3();
      this.tooltip = document.getElementById("tooltip");

      const pick = (e) => {
        const rect = el.getBoundingClientRect();
        ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
        ray.setFromCamera(ndc, this.camera);
        const hits = ray.intersectObjects(this.nodes.map(n => n.hit), false);
        return hits.length ? this.byId[hits[0].object.userData.nodeId] : null;
      };

      el.addEventListener("pointerdown", e => {
        el.setPointerCapture(e.pointerId);
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        start = { x: e.clientX, y: e.clientY }; moved = 0; this.interacting = true; this.tween = null;
        if (pointers.size === 2) { mode = "pinch"; const [a, b] = [...pointers.values()]; pinch = Math.hypot(a.x - b.x, a.y - b.y); return; }
        downNode = pick(e);
        if (downNode && e.button === 0 && !e.shiftKey) {
          mode = "drag"; this.dragging = downNode;
          plane.setFromNormalAndCoplanarPoint(this.camera.getWorldDirection(new THREE.Vector3()), downNode.group.position);
          ray.ray.intersectPlane(plane, hitPoint); offset.subVectors(downNode.group.position, hitPoint);
          el.style.cursor = "grabbing";
        } else mode = (e.button === 2 || e.shiftKey) ? "pan" : "orbit";
      });

      el.addEventListener("pointermove", e => {
        const p = pointers.get(e.pointerId);
        if (!p) { this.hover(pick(e), e); return; }
        const dx = e.clientX - p.x, dy = e.clientY - p.y;
        p.x = e.clientX; p.y = e.clientY; moved += Math.abs(dx) + Math.abs(dy);
        if (mode === "pinch" && pointers.size === 2) {
          const [a, b] = [...pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
          this.zoom(pinch / d); pinch = d; return;
        }
        if (mode === "orbit") {
          this.view.theta -= dx * 0.0055; this.view.phi = Math.min(2.9, Math.max(0.15, this.view.phi - dy * 0.0055));
          this.follow = null;
        } else if (mode === "pan") {
          const k = this.view.radius / 600, right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 0), up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrix, 1);
          this.view.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k); this.follow = null;
        } else if (mode === "drag" && this.dragging) {
          const rect = el.getBoundingClientRect();
          ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
          ray.setFromCamera(ndc, this.camera);
          if (ray.ray.intersectPlane(plane, hitPoint)) this.dragging.group.position.copy(hitPoint.add(offset));
          this.hideTooltip();
        }
      });

      const end = e => {
        pointers.delete(e.pointerId);
        if (pointers.size) return;
        if (moved < 5) this.select(downNode ? downNode.id : null, true);
        if (this.dragging && this.dragging.id !== "agent") this.dragging.fixed = false;
        this.dragging = null; mode = null; downNode = null; this.interacting = false; el.style.cursor = "";
      };
      el.addEventListener("pointerup", end); el.addEventListener("pointercancel", end);
      el.addEventListener("pointerleave", () => this.hideTooltip());
      el.addEventListener("contextmenu", e => e.preventDefault());
      el.addEventListener("wheel", e => { e.preventDefault(); this.tween = null; this.zoom(Math.exp(e.deltaY * 0.0012)); }, { passive: false });
    }

    zoom(k) { this.view.radius = Math.min(700, Math.max(45, this.view.radius * k)); }

    hover(node, e) {
      this.renderer.domElement.style.cursor = node ? "pointer" : "";
      if (!node || !this.tooltip) return this.hideTooltip();
      const rect = this.el.getBoundingClientRect();
      this.tooltip.innerHTML = `<b>${V3.esc(node.name)}</b><span>${this.getStatus(node.id)}</span>`;
      this.tooltip.style.transform = `translate(${e.clientX - rect.left + 14}px, ${e.clientY - rect.top + 14}px)`;
      this.tooltip.hidden = false;
    }
    hideTooltip() { if (this.tooltip) this.tooltip.hidden = true; }

    // --------------------------------------------------------- commands --
    select(id, fromClick = false) {
      this.selected = id ? this.byId[id] : null;
      this.applyDimming();
      if (fromClick) this.onSelect(id);
    }

    filter(query) {
      const q = (query || "").trim().toLowerCase();
      this.filterSet = q ? new Set(this.nodes.filter(n => n.name.toLowerCase().includes(q) || n.cat.includes(q)).map(n => n.id)) : null;
      this.applyDimming();
      return this.filterSet ? [...this.filterSet] : null;
    }

    applyDimming() {
      const sel = this.selected, near = new Set();
      if (sel) { near.add(sel.id); this.links.forEach(l => { if (l.a === sel) near.add(l.b.id); if (l.b === sel) near.add(l.a.id); }); }
      for (const n of this.nodes) {
        const on = (!sel || near.has(n.id)) && (!this.filterSet || this.filterSet.has(n.id));
        n.dim = on ? 1 : 0.18;
      }
      for (const l of this.links) {
        const on = (!sel || l.a === sel || l.b === sel) && (!this.filterSet || (this.filterSet.has(l.a.id) && this.filterSet.has(l.b.id)));
        l.line.material.opacity = on ? (sel ? 0.7 : this.linkOpacity()) : 0.05;
      }
    }

    linkOpacity() { return this.regime && this.regime.trend === "Trending" ? 0.36 : 0.26; }

    focus(id) {
      const n = this.byId[id]; if (!n) return;
      this.follow = n;
      this.tween = { from: this.view.target.clone(), fromR: this.view.radius, toR: n.cat === "core" ? 120 : 85, t: 0 };
      this.select(id);
    }

    resetCamera() {
      this.follow = null; this.select(null);
      this.tween = { from: this.view.target.clone(), to: new THREE.Vector3(), fromR: this.view.radius, toR: this.fitR, t: 0 };
      this.view.phi = 1.18;
    }

    setAutoRotate(on) { this.autoRotate = on; }
    setPaused(p) { this.paused = p; }

    /** React to the simulated market regime: pace, link intensity, fog tint. */
    setRegime(reg) {
      this.regime = reg;
      const hv = reg.vol === "High volatility", lv = reg.vol === "Low volatility";
      this.energy = (hv ? 1.6 : lv ? 0.65 : 1) * (reg.trend === "Trending" ? 1.15 : 0.9);
      const tint = hv ? new THREE.Color("#120a10") : lv ? new THREE.Color("#050b12") : new THREE.Color("#060a11");
      this.fogTarget = tint;
      this.applyDimming();
    }

    // ------------------------------------------------------- particles --
    emit(a, b, { color, size = 1.4, speed = 1, bright = false, onArrive } = {}) {
      const link = this.linkIndex[a + ">" + b] || this.linkIndex[b + ">" + a];
      if (!link) { if (onArrive) onArrive(); return; }
      const reverse = link.a.id !== a;
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glowTex, color: color || link.color, transparent: true,
        opacity: bright ? 1 : 0.75, blending: THREE.AdditiveBlending, depthWrite: false, fog: false }));
      sp.scale.setScalar(size * (bright ? 7 : 4.2));
      this.scene.add(sp);
      this.particles.push({ sp, link, reverse, t: 0, speed, onArrive, bright });
    }

    pulse(id, color, strength = 1) {
      const n = this.byId[id]; if (!n) return;
      n.pulse = Math.max(n.pulse, strength); n.pulseColor = new THREE.Color(color || n.color);
    }

    setFlowDuration(ms) { this.flowDuration = ms; }

    /** Animate one decision through the 9 pipeline stages. */
    playDecision(rec) {
      if (this.flowBusy) return false;
      this.flowBusy = true;
      const stages = V3.PIPELINE, per = this.flowDuration / stages.length;
      const action = rec.risk.action, ac = V3.ACTION_COLORS[rec.decision.name];
      const riskColor = !rec.risk.approved ? "#e27466" : rec.risk.event ? "#d9a441" : "#6cc391";
      const colorFor = k => ({ analyse: "#d3a75f", decide: ac, risk: riskColor, exec: V3.ACTION_COLORS[action], portfolio: "#6cc391",
        reward: rec.reward >= 0 ? "#6cc391" : "#e27466", learn: "#a99bd6" }[k] || "#c9cdd2");
      let i = 0;
      const next = () => {
        if (i >= stages.length) { this.flowBusy = false; this.onStage(-1, rec); return; }
        const st = stages[i++];
        this.onStage(i - 1, rec);
        const col = colorFor(st.key);
        if (st.pulse) this.pulse(st.pulse, col, 1);
        if (st.key === "decide") this.showDecision(rec);
        if (st.key === "data") this.pulse("data", "#7fa7d9", 0.8);
        if (!st.hops.length) { setTimeout(next, per); return; }
        let left = st.hops.length;
        st.hops.forEach(([a, b]) => this.emit(a, b, { color: col, bright: true, speed: 1000 / Math.max(per, 60),
          onArrive: () => { this.pulse(b, col, 0.7); if (--left === 0) next(); } }));
      };
      next();
      return true;
    }

    showDecision(rec) {
      if (this.decisionSprite) { this.scene.remove(this.decisionSprite); this.decisionSprite.material.map.dispose(); }
      const name = rec.decision.name, conf = Math.round(rec.decision.confidence * 100);
      const sp = textSprite(`${name} ${conf}%`, { size: 30, color: V3.ACTION_COLORS[name], weight: 700, spacing: 4 });
      sp.scale.multiplyScalar(1.6);
      sp.position.copy(this.byId.agent.group.position).add(new THREE.Vector3(0, 34, 0));
      sp.userData.life = 1;
      this.scene.add(sp); this.decisionSprite = sp;
    }

    // ------------------------------------------------------------ frame --
    /** Centre the projection on the part of the canvas not covered by panels. */
    resize() {
      const w = this.el.clientWidth || 1, h = this.el.clientHeight || 1;
      this.renderer.setSize(w, h, false); this.camera.aspect = w / h;
      const r = this.viewRect && this.viewRect();
      if (r && r.w > 100 && r.h > 100) {
        this.camera.setViewOffset(w, h, w / 2 - (r.x + r.w / 2), h / 2 - (r.y + r.h / 2), w, h);
        this.fitR = Math.min(600, Math.max(260, 250 * Math.max(h / r.h * 0.9, (w / r.w) * 1.0)));
      } else { this.camera.clearViewOffset(); this.fitR = w / h < 1.2 ? Math.min(620, 380 / (w / h)) : 270; }
      this.camera.updateProjectionMatrix();
      if (!this.fitted) { this.view.radius = this.fitR; this.fitted = true; }
    }

    loop() {
      requestAnimationFrame(this.loop);
      const dt = Math.min(this.clock.getDelta(), 0.05), t = this.clock.elapsedTime;
      this.physics(dt * 60 * 0.6);

      // Camera.
      if (this.tween) {
        const tw = this.tween; tw.t = Math.min(1, tw.t + dt / 0.9);
        const e = tw.t < 0.5 ? 2 * tw.t * tw.t : 1 - Math.pow(-2 * tw.t + 2, 2) / 2;
        const to = this.follow ? this.follow.group.position : tw.to;
        this.view.target.lerpVectors(tw.from, to, e); this.view.radius = tw.fromR + (tw.toR - tw.fromR) * e;
        if (tw.t >= 1) this.tween = null;
      } else if (this.follow) this.view.target.lerp(this.follow.group.position, 0.08);
      if (this.autoRotate && !this.interacting) this.view.theta += dt * 0.07;
      const v = this.view, c = this.camera;
      c.position.set(v.target.x + v.radius * Math.sin(v.phi) * Math.cos(v.theta), v.target.y + v.radius * Math.cos(v.phi),
        v.target.z + v.radius * Math.sin(v.phi) * Math.sin(v.theta));
      c.lookAt(v.target);

      // Fog follows the regime tint slowly.
      if (this.fogTarget) { this.scene.fog.color.lerp(this.fogTarget, 0.02); this.scene.background.lerp(this.fogTarget, 0.02); }

      // Nodes.
      for (const n of this.nodes) {
        n.pulse = Math.max(0, n.pulse - dt * 1.6);
        const breathe = n.cat === "core" ? 1 + Math.sin(t * 1.6) * 0.035 * this.energy : 1;
        n.mesh.scale.setScalar(breathe + n.pulse * 0.25);
        n.mesh.material.emissiveIntensity = (n.cat === "core" ? 0.75 : 0.6) + n.pulse * 1.2;
        n.mesh.material.emissive.copy(n.color).lerp(n.pulseColor, Math.min(1, n.pulse));
        n.glow.material.color.copy(n.mesh.material.emissive);
        n.glow.material.opacity = (n.cat === "core" ? 0.22 : 0.12) * n.dim + n.pulse * 0.3;
        n.mesh.material.opacity = 0.35 + 0.65 * n.dim;
        n.label.material.opacity = 0.25 + 0.75 * n.dim;
        if (n.extras.length) {
          const spin = 0.25 * this.energy * (this.paused ? 0.2 : 1);
          n.extras[0].rotation.y += dt * spin * 0.6; n.extras[0].rotation.x += dt * spin * 0.3;
          n.extras[1].rotation.z += dt * spin * 1.2; n.extras[2].rotation.z -= dt * spin * 0.9;
        }
      }
      this.coreLight.position.copy(this.byId.agent.group.position);
      this.coreLight.intensity = 25 + this.byId.agent.pulse * 40;

      // Links follow their nodes.
      for (const l of this.links) {
        const p = l.line.geometry.attributes.position;
        p.setXYZ(0, ...l.a.group.position.toArray()); p.setXYZ(1, ...l.b.group.position.toArray()); p.needsUpdate = true;
        if (!this.paused) {
          l.acc += dt * 0.32 * this.energy;
          if (l.acc >= 1) { l.acc -= 1 + Math.random() * 0.6; this.emit(l.a.id, l.b.id, { speed: 0.35 * this.energy, size: 1 }); }
        }
      }

      // Particles.
      for (let i = this.particles.length - 1; i >= 0; i--) {
        const p = this.particles[i];
        p.t += dt * p.speed * (p.bright ? 1 : (this.paused ? 0.3 : 1));
        const A = p.reverse ? p.link.b : p.link.a, B = p.reverse ? p.link.a : p.link.b;
        p.sp.position.lerpVectors(A.group.position, B.group.position, Math.min(p.t, 1));
        if (p.t >= 1) {
          this.scene.remove(p.sp); p.sp.material.dispose(); this.particles.splice(i, 1);
          if (p.onArrive) p.onArrive();
        }
      }

      if (this.decisionSprite) {
        const s = this.decisionSprite; s.userData.life -= dt * Math.max(0.45, 1000 / (this.flowDuration * 2.5));
        s.material.opacity = Math.min(1, s.userData.life * 2);
        s.position.copy(this.byId.agent.group.position).add(new THREE.Vector3(0, 34 + (1 - s.userData.life) * 6, 0));
        if (s.userData.life <= 0) { this.scene.remove(s); s.material.map.dispose(); this.decisionSprite = null; }
      }
      this.dust.rotation.y += dt * 0.004;
      this.renderer.render(this.scene, this.camera);
    }
  }

  V3.Graph3D = Graph3D;
})();
