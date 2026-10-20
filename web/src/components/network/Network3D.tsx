/* The live network: every account and every market in one 3D scene, built
 * only from data/paper.json.
 *
 *   centre      the Vanguard3 core, two gold rings turning around a light
 *   inner ring  the agents. Size = rank in the race (the leader is largest
 *               and wears a gold ring); fixed twins are wire shells beside
 *               their learner; the yardsticks are ivory and grey
 *   outer ring  the 107 markets, in five sectors by kind of asset. A
 *               market glows brighter the more agents hold it
 *   arcs        a position held that day, in the agent's colour, with light
 *               flowing from agent to market; dashed = an order queued for
 *               the next open (latest day only)
 *   dust        one speck per day an agent came close to buying a market
 *               (a near miss), so the space between them fills up over time
 *
 * Hover an agent to light up its part of the network; click it to open its
 * profile. The day slider replays the network since launch. */
import { Html, Line, OrbitControls, Sparkles } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { ORDER } from "../../lib/agents";
import { pct } from "../../lib/format";
import type { Agent, RunData } from "../../lib/types";

const GROUPS = ["US stocks", "Stock funds (ETFs)", "Bonds and commodities", "European stocks", "Swiss stocks"];
const R_AGENTS = 6.6;
const R_MARKETS = 12.4;

/** Agent colours as hex for the scene (the page's dark palette). */
const HEX: Record<string, string> = {
  trend: "#3987e5", reversion: "#d95926", volatility: "#199e70", manager: "#c98500", news: "#d55181",
  learner: "#1aa31a", news_opus: "#9085e9", learner_opus: "#e66767", benchmark: "#e9e1cf", monkey: "#9a9384",
};
const GOLD = "#d4b26a";

function seeded(text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => { h += 0x6d2b79f5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** A soft round sprite, shared by halos, flow lights and dust. */
let dotTexture: THREE.Texture | null = null;
function dot() {
  if (dotTexture) return dotTexture;
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d")!, grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)"); grad.addColorStop(0.35, "rgba(255,255,255,0.55)"); grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  dotTexture = new THREE.CanvasTexture(c);
  return dotTexture;
}

interface Node { agent: Agent; pos: THREE.Vector3; color: string }
interface Market { ticker: string; group: string; pos: THREE.Vector3 }

function useLayout(d: RunData) {
  return useMemo(() => {
    // Markets: five sectors around the outer ring, a little scattered in height.
    const tickers = Object.keys(d.prices);
    const byGroup = GROUPS.map((g) => tickers.filter((t) => (d.groups[t] || "US stocks") === g));
    const extra = tickers.filter((t) => !GROUPS.includes(d.groups[t] || "US stocks"));
    if (extra.length) byGroup[0].push(...extra);
    const GAP = 4, slots = tickers.length + GAP * GROUPS.length;
    const markets: Market[] = [], sectors: { name: string; pos: THREE.Vector3 }[] = [];
    let slot = 0;
    byGroup.forEach((list, gi) => {
      const first = slot;
      list.forEach((t) => {
        const r = seeded(t), ang = ((slot + 0.5) / slots) * Math.PI * 2;
        const rad = R_MARKETS + (r() - 0.5) * 1.6, y = (r() - 0.5) * 3.2;
        markets.push({ ticker: t, group: GROUPS[gi], pos: new THREE.Vector3(Math.cos(ang) * rad, y, Math.sin(ang) * rad) });
        slot++;
      });
      const mid = ((first + slot) / 2 / slots) * Math.PI * 2;
      sectors.push({ name: GROUPS[gi], pos: new THREE.Vector3(Math.cos(mid) * (R_MARKETS + 2.6), -2.4, Math.sin(mid) * (R_MARKETS + 2.6)) });
      slot += GAP;
    });
    const marketAt = new Map(markets.map((m) => [m.ticker, m]));

    // Agents: the inner ring in a fixed order; twins just outside their learner.
    const main = d.agents.filter((a) => !a.fixed_twin)
      .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
    const nodes: Node[] = [];
    main.forEach((a, i) => {
      const ang = (i / main.length) * Math.PI * 2 + 0.3;
      nodes.push({ agent: a, color: HEX[a.key] || GOLD,
        pos: new THREE.Vector3(Math.cos(ang) * R_AGENTS, Math.sin(i * 1.7) * 1.25, Math.sin(ang) * R_AGENTS) });
    });
    d.agents.filter((a) => a.fixed_twin).forEach((a) => {
      const lead = nodes.find((n) => n.agent.key === a.key && !n.agent.fixed_twin);
      const base = lead ? lead.pos : new THREE.Vector3(R_AGENTS, 0, 0);
      const ang = Math.atan2(base.z, base.x) + 0.2;
      nodes.push({ agent: a, color: HEX[a.key] || GOLD,
        pos: new THREE.Vector3(Math.cos(ang) * (R_AGENTS + 1.7), base.y - 0.9, Math.sin(ang) * (R_AGENTS + 1.7)) });
    });
    return { markets, marketAt, sectors, nodes };
  }, [d]);
}

function arc(a: THREE.Vector3, b: THREE.Vector3, lift = 1.6) {
  const mid = a.clone().add(b).multiplyScalar(0.5);
  mid.multiplyScalar(0.82).add(new THREE.Vector3(0, lift + a.distanceTo(b) * 0.06, 0));
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}

/** Positions held by an agent at the close of a date (from its round trips). */
function heldOn(a: Agent, date: string) {
  return (a.trips || []).filter((t) => t.entry_date <= date && (t.exit_date == null || t.exit_date > date)).map((t) => t.ticker);
}

/* ---------- pieces of the scene ---------- */

function Core() {
  const a = useRef<THREE.Mesh>(null), b = useRef<THREE.Mesh>(null), c = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (a.current) { a.current.rotation.x += dt * 0.35; a.current.rotation.y += dt * 0.15; }
    if (b.current) { b.current.rotation.y -= dt * 0.28; b.current.rotation.z += dt * 0.12; }
    if (c.current) c.current.scale.setScalar(1 + Math.sin(performance.now() / 900) * 0.04);
  });
  const gold = new THREE.Color(GOLD).multiplyScalar(1.8);
  return (
    <group>
      <mesh ref={a}><torusGeometry args={[1.25, 0.014, 8, 160]} /><meshBasicMaterial color={gold} toneMapped={false} /></mesh>
      <mesh ref={b} rotation={[Math.PI / 2.6, 0, 0]}><torusGeometry args={[1.0, 0.01, 8, 160]} /><meshBasicMaterial color={gold} toneMapped={false} /></mesh>
      <group ref={c}>
        <mesh><icosahedronGeometry args={[0.36, 2]} /><meshBasicMaterial color={new THREE.Color("#f6dfa4").multiplyScalar(2.2)} toneMapped={false} /></mesh>
        <sprite scale={[3.4, 3.4, 1]}><spriteMaterial map={dot()} color={GOLD} transparent opacity={0.45} depthWrite={false} blending={THREE.AdditiveBlending} /></sprite>
      </group>
    </group>
  );
}

function Markets({ markets, held, focusHeld, onHover }: {
  markets: Market[]; held: Map<string, number>; focusHeld: Set<string> | null; onHover: (t: string | null) => void;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = ref.current; if (!m) return;
    const tmp = new THREE.Object3D(), col = new THREE.Color();
    markets.forEach((mk, i) => {
      const n = held.get(mk.ticker) || 0;
      const lit = focusHeld ? focusHeld.has(mk.ticker) : n > 0;
      tmp.position.copy(mk.pos);
      tmp.scale.setScalar(0.075 + Math.min(n, 7) * 0.024 + (lit ? 0.03 : 0));
      tmp.updateMatrix();
      m.setMatrixAt(i, tmp.matrix);
      col.set(lit ? "#fbe9bd" : focusHeld ? "#4a453c" : "#a39a87").multiplyScalar(lit ? 1.6 : 1);
      m.setColorAt(i, col);
    });
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [markets, held, focusHeld]);
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, markets.length]}
      onPointerMove={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); if (e.instanceId != null) onHover(markets[e.instanceId].ticker); }}
      onPointerOut={() => onHover(null)}
    >
      <sphereGeometry args={[1, 14, 14]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

function AgentNode({ node, radius, leader, dim, onOver, onOut, onClick }: {
  node: Node; radius: number; leader: boolean; dim: boolean;
  onOver: () => void; onOut: () => void; onClick: () => void;
}) {
  const { agent, pos, color } = node;
  const ring = useRef<THREE.Mesh>(null), shell = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => {
    if (ring.current) ring.current.rotation.z += dt * 0.6;
    if (shell.current) { shell.current.rotation.y += dt * 0.3; shell.current.rotation.x += dt * 0.12; }
  });
  const glow = new THREE.Color(color).multiplyScalar(agent.benchmark ? 1.1 : 2.1);
  const events = {
    onPointerOver: (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); onOver(); },
    onPointerOut: onOut,
    onClick: (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onClick(); },
  };
  return (
    <group position={pos}>
      {agent.fixed_twin ? (
        <mesh ref={shell} {...events}>
          <icosahedronGeometry args={[radius * 0.95, 1]} />
          <meshBasicMaterial color={glow} wireframe transparent opacity={dim ? 0.15 : 0.85} toneMapped={false} />
        </mesh>
      ) : (
        <mesh {...events}>
          <sphereGeometry args={[radius, 32, 32]} />
          <meshBasicMaterial color={glow} transparent opacity={dim ? 0.25 : 1} toneMapped={false} />
        </mesh>
      )}
      {!agent.fixed_twin && (
        <sprite scale={[radius * 6, radius * 6, 1]}>
          <spriteMaterial map={dot()} color={color} transparent opacity={dim ? 0.08 : agent.benchmark ? 0.25 : 0.5} depthWrite={false} blending={THREE.AdditiveBlending} />
        </sprite>
      )}
      {leader && (
        <mesh ref={ring} rotation={[Math.PI / 2.2, 0, 0]}>
          <torusGeometry args={[radius * 1.75, 0.018, 8, 96]} />
          <meshBasicMaterial color={new THREE.Color(GOLD).multiplyScalar(2)} toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}

/** Lights that travel along every held position, from agent to market. */
function Flow({ curves }: { curves: { curve: THREE.QuadraticBezierCurve3; color: string; dim: boolean }[] }) {
  const PER = 2;
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = curves.length * PER;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    const cols = new Float32Array(n * 3), c = new THREE.Color();
    curves.forEach((k, i) => {
      c.set(k.color).multiplyScalar(k.dim ? 0.15 : 2);
      for (let j = 0; j < PER; j++) cols.set([c.r, c.g, c.b], (i * PER + j) * 3);
    });
    g.setAttribute("color", new THREE.BufferAttribute(cols, 3));
    return g;
  }, [curves]);
  const phases = useMemo(() => curves.flatMap((_, i) => Array.from({ length: PER }, (_, j) => (j / PER + seeded(String(i))() * 0.5) % 1)), [curves]);
  const tmp = useMemo(() => new THREE.Vector3(), []);
  useFrame((_, dt) => {
    const pos = geo.getAttribute("position") as THREE.BufferAttribute;
    curves.forEach((k, i) => {
      for (let j = 0; j < PER; j++) {
        const idx = i * PER + j;
        phases[idx] = (phases[idx] + dt * 0.22) % 1;
        k.curve.getPoint(phases[idx], tmp);
        pos.setXYZ(idx, tmp.x, tmp.y, tmp.z);
      }
    });
    pos.needsUpdate = true;
  });
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <points geometry={geo}>
      <pointsMaterial map={dot()} size={0.34} vertexColors transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
    </points>
  );
}

/** Near misses: specks between an agent and the markets it kept looking at. */
function Dust({ node, marketAt, upto, dim }: { node: Node; marketAt: Map<string, Market>; upto: string; dim: boolean }) {
  const geo = useMemo(() => {
    const pts: number[] = [];
    const r = seeded(node.agent.id);
    (node.agent.scans || []).filter(([date]) => date <= upto).forEach(([, near]) => {
      Object.entries(near).forEach(([t, c]) => {
        const m = marketAt.get(t); if (!m) return;
        const k = 0.3 + r() * 0.6;
        const p = node.pos.clone().lerp(m.pos, k);
        p.x += (r() - 0.5) * 0.9 * c; p.y += (r() - 0.5) * 0.9 * c + 0.4; p.z += (r() - 0.5) * 0.9 * c;
        pts.push(p.x, p.y, p.z);
      });
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, [node, marketAt, upto]);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <points geometry={geo}>
      <pointsMaterial map={dot()} size={0.13} color={node.color} transparent opacity={dim ? 0.06 : 0.42} depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

/** On wide screens the scene sits right of centre, leaving room for the
 *  headline; the camera still orbits the scene's own middle. */
function Offset({ shift, lift }: { shift: number; lift: number }) {
  const { camera, size } = useThree();
  useLayoutEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    cam.setViewOffset(size.width, size.height, -size.width * shift, size.height * lift, size.width, size.height);
    cam.updateProjectionMatrix();
  }, [camera, size, shift, lift]);
  return null;
}

function Scene({ d, day, focus, setFocus, onSelect, motion, labels }: {
  d: RunData; day: number; focus: string | null; setFocus: (id: string | null) => void;
  onSelect?: (a: Agent) => void; motion: boolean; labels: boolean;
}) {
  const { markets, marketAt, sectors, nodes } = useLayout(d);
  const dates = d.agents[0]?.equity.map((p) => p[0]) || [d.last];
  const i = Math.min(day, dates.length - 1), date = dates[i], latest = i === dates.length - 1;
  const [hoverMarket, setHoverMarket] = useState<string | null>(null);

  const state = useMemo(() => {
    const value = (a: Agent) => (a.equity[i] || a.equity[a.equity.length - 1] || [date, d.initial_capital_chf])[1];
    const rets = nodes.map((n) => value(n.agent) / d.initial_capital_chf - 1);
    const lo = Math.min(...rets), hi = Math.max(...rets);
    const racing = nodes.filter((n) => !n.agent.benchmark && !n.agent.fixed_twin);
    const leader = racing.length ? racing.reduce((x, y) => (value(y.agent) > value(x.agent) ? y : x)).agent.id : null;
    const radius = new Map(nodes.map((n, k) => [n.agent.id, 0.24 + 0.26 * (hi > lo ? (rets[k] - lo) / (hi - lo) : 0.5)]));
    const ret = new Map(nodes.map((n, k) => [n.agent.id, rets[k]]));
    const holdings = new Map(nodes.map((n) => [n.agent.id, heldOn(n.agent, date)]));
    const heldCount = new Map<string, number>();
    nodes.filter((n) => !n.agent.fixed_twin).forEach((n) => holdings.get(n.agent.id)!.forEach((t) => heldCount.set(t, (heldCount.get(t) || 0) + 1)));
    return { leader, radius, ret, holdings, heldCount };
  }, [nodes, i, date, d]);

  const edges = useMemo(() => {
    const out: { key: string; agentId: string; curve: THREE.QuadraticBezierCurve3; color: string; pending: boolean }[] = [];
    nodes.forEach((n) => {
      // Twins mostly mirror their learner: their links would only double the lines.
      if (n.agent.fixed_twin) return;
      state.holdings.get(n.agent.id)!.forEach((t) => {
        const m = marketAt.get(t); if (!m) return;
        out.push({ key: n.agent.id + t, agentId: n.agent.id, curve: arc(n.pos, m.pos), color: n.color, pending: false });
      });
      if (latest) n.agent.pending_orders.filter((o) => o.side === "BUY").forEach((o) => {
        const m = marketAt.get(o.ticker); if (!m) return;
        out.push({ key: n.agent.id + o.ticker + "p", agentId: n.agent.id, curve: arc(n.pos, m.pos, 2.4), color: n.color, pending: true });
      });
    });
    return out;
  }, [nodes, state, marketAt, latest]);

  const lines = useMemo(() => edges.map((e) => ({ ...e, points: e.curve.getPoints(40) })), [edges]);
  const flows = useMemo(() => edges.filter((e) => !e.pending).map((e) => ({ curve: e.curve, color: e.color, dim: !!focus && e.agentId !== focus })), [edges, focus]);

  const focusHeld = focus ? new Set(state.holdings.get(focus) || []) : null;
  const labelled = new Set<string>(focusHeld ? [...focusHeld] : [...state.heldCount].filter(([, n]) => n >= 3).map(([t]) => t));
  if (hoverMarket) labelled.add(hoverMarket);
  const holders = hoverMarket ? nodes.filter((n) => !n.agent.fixed_twin && state.holdings.get(n.agent.id)!.includes(hoverMarket)) : [];

  return (
    <>
      <Core />
      {motion && <Sparkles count={70} scale={[34, 12, 34]} size={1.6} speed={0.18} color={GOLD} opacity={0.35} />}
      <Markets markets={markets} held={state.heldCount} focusHeld={focusHeld} onHover={setHoverMarket} />
      {nodes.filter((n) => !n.agent.fixed_twin).map((n) => (
        <Dust key={n.agent.id} node={n} marketAt={marketAt} upto={date} dim={!!focus && focus !== n.agent.id} />
      ))}
      {lines.map((e) => (
        <Line
          key={e.key}
          points={e.points}
          color={new THREE.Color(e.color).multiplyScalar(focus === e.agentId ? 1.9 : 1.25)}
          lineWidth={focus === e.agentId ? 1.8 : 1}
          transparent
          opacity={focus ? (focus === e.agentId ? 0.95 : 0.04) : e.pending ? 0.5 : 0.22}
          dashed={e.pending}
          dashSize={0.35}
          gapSize={0.25}
          toneMapped={false}
        />
      ))}
      {motion && <Flow curves={flows} />}
      {nodes.filter((n) => n.agent.fixed_twin).map((n) => {
        const lead = nodes.find((x) => x.agent.key === n.agent.key && !x.agent.fixed_twin);
        return lead ? <Line key={n.agent.id + "twin"} points={[lead.pos, n.pos]} color={GOLD} lineWidth={0.6} transparent opacity={0.18} /> : null;
      })}
      {nodes.map((n) => (
        <AgentNode
          key={n.agent.id}
          node={n}
          radius={state.radius.get(n.agent.id)!}
          leader={n.agent.id === state.leader}
          dim={!!focus && focus !== n.agent.id}
          onOver={() => { setFocus(n.agent.id); document.body.style.cursor = "pointer"; }}
          onOut={() => { setFocus(null); document.body.style.cursor = ""; }}
          onClick={() => onSelect?.(n.agent)}
        />
      ))}
      {labels && nodes.map((n) => {
        const r = state.ret.get(n.agent.id)!;
        const on = focus === n.agent.id;
        return (
          <Html key={n.agent.id + "l"} position={[n.pos.x, n.pos.y + state.radius.get(n.agent.id)! + 0.42, n.pos.z]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
            <div className={`v3-tag ${on ? "on" : ""} ${focus && !on ? "dim" : ""} ${n.agent.fixed_twin && !on ? "off" : ""}`} style={{ ["--c" as string]: n.color }}>
              <i />{n.agent.name}<b className={r > 0 ? "up" : r < 0 ? "down" : ""}>{pct(r)}</b>
              {on && <span className="v3-tag-more">{state.holdings.get(n.agent.id)!.length} holdings · click to open</span>}
            </div>
          </Html>
        );
      })}
      {labels && markets.filter((m) => state.heldCount.has(m.ticker) || hoverMarket === m.ticker).map((m) => (
        <Html key={m.ticker} position={[m.pos.x, m.pos.y + 0.45, m.pos.z]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
          <div className={`v3-mk ${hoverMarket === m.ticker ? "on" : ""} ${labelled.has(m.ticker) ? "" : "off"}`}>
            {m.ticker}
            {hoverMarket === m.ticker && <span>{holders.length ? `held by ${holders.map((h) => h.agent.name).join(", ")}` : m.group}</span>}
          </div>
        </Html>
      ))}
      {labels && sectors.map((s) => (
        <Html key={s.name} position={s.pos} center zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
          <div className="v3-sector">{s.name}</div>
        </Html>
      ))}
    </>
  );
}

export default function Network3D({ data, day, focus, setFocus, onSelect }: {
  data: RunData; day: number; focus: string | null; setFocus: (id: string | null) => void; onSelect?: (a: Agent) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const [motion] = useState(() => !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [touch] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [wide, setWide] = useState(() => window.innerWidth >= 1024);
  useEffect(() => {
    const on = () => setWide(window.innerWidth >= 1024);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.02 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={wrap} className="absolute inset-0 isolate" aria-hidden>
      <Canvas
        frameloop={visible ? "always" : "never"}
        dpr={[1, 1.75]}
        camera={{ position: [0, 12.5, wide ? 29.5 : 35], fov: 42, near: 0.1, far: 200 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        onPointerMissed={() => setFocus(null)}
      >
        <Offset shift={wide ? 0.17 : 0} lift={wide ? -0.06 : 0.24} />
        <Scene d={data} day={day} focus={focus} setFocus={setFocus} onSelect={onSelect} motion={motion} labels={wide} />
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          enableRotate={!touch}
          autoRotate={motion && !focus}
          autoRotateSpeed={0.32}
          enableDamping
          dampingFactor={0.06}
          minPolarAngle={Math.PI * 0.22}
          maxPolarAngle={Math.PI * 0.56}
        />
        <EffectComposer multisampling={0}>
          <Bloom mipmapBlur intensity={0.95} luminanceThreshold={0.62} luminanceSmoothing={0.25} radius={0.72} />
          <Vignette offset={0.22} darkness={0.72} />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
