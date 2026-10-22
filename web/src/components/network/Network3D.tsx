/* The live network as a globe you can spin: every account and every market
 * in one 3D scene, built only from data/paper.json.
 *
 *   centre    the Vanguard3 core, two gold rings turning around a light
 *   agents    inside the globe. Size = place in the race (the leader is
 *             largest and wears a gold ring); fixed twins are wire shells
 *             beside their learner; the yardsticks are ivory and grey
 *   markets   the 107 markets on the globe's surface, in bands by kind of
 *             asset (see SECTORS); a market glows brighter the more agents
 *             hold it
 *   arcs      a position held that day, in the agent's colour, with light
 *             flowing from agent to market; dashed = an order queued for
 *             the next open (latest day only)
 *   dust      one speck per day an agent came close to buying a market
 *
 * Drag to spin it in any direction, pinch or ⌘/Ctrl + scroll to zoom (a
 * plain scroll still scrolls the page). Hover an agent to light up its part
 * of the network; click it to open its profile. */
import { Html, Line, OrbitControls, Sparkles } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { ORDER } from "../../lib/agents";
import { pct } from "../../lib/format";
import type { Agent, RunData } from "../../lib/types";

/** The globe's bands, top to bottom, with the tint of their markets. */
export const SECTORS: { name: string; color: string }[] = [
  { name: "US stocks", color: "#efe3c4" },
  { name: "Stock funds (ETFs)", color: "#d9b46c" },
  { name: "Bonds and commodities", color: "#9fb4c8" },
  { name: "European stocks", color: "#b9a7e0" },
  { name: "Swiss stocks", color: "#e79a86" },
];
const R_AGENTS = 5.2;
const R_MARKETS = 11;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const MIN_DIST = 13, MAX_DIST = 90;

/** Agent colours as hex for the scene (the page's dark palette). */
const HEX: Record<string, string> = {
  trend: "#3987e5", reversion: "#d95926", volatility: "#199e70", manager: "#c98500", news: "#d55181",
  learner: "#1aa31a", news_opus: "#9085e9", learner_opus: "#e66767", benchmark: "#e9e1cf", equal_weight: "#9fb4c8", monkey: "#9a9384",
};
const GOLD = "#d4b26a";

export interface NetworkApi { zoom: (factor: number) => void; reset: () => void }

function seeded(text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => { h += 0x6d2b79f5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Evenly spread points on a unit sphere, top to bottom (Fibonacci lattice). */
function sphere(n: number) {
  return Array.from({ length: n }, (_, i) => {
    const y = 1 - ((i + 0.5) / n) * 2, r = Math.sqrt(1 - y * y), th = i * GOLDEN;
    return new THREE.Vector3(Math.cos(th) * r, y, Math.sin(th) * r);
  });
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
interface Market { ticker: string; group: string; color: string; pos: THREE.Vector3 }

function useLayout(d: RunData) {
  return useMemo(() => {
    // Markets on the surface: the lattice runs top to bottom, so taking the
    // sectors in order gives each one its own band of the globe.
    const tickers = Object.keys(d.prices);
    const names = SECTORS.map((s) => s.name);
    const groupOf = (t: string) => (names.includes(d.groups[t]) ? d.groups[t] : "US stocks");
    const ordered = names.flatMap((g) => tickers.filter((t) => groupOf(t) === g));
    const pts = sphere(ordered.length);
    const markets: Market[] = ordered.map((t, i) => ({
      ticker: t, group: groupOf(t), color: SECTORS[names.indexOf(groupOf(t))].color,
      pos: pts[i].clone().multiplyScalar(R_MARKETS + (seeded(t)() - 0.5) * 0.5),
    }));
    const marketAt = new Map(markets.map((m) => [m.ticker, m]));

    // Agents on a smaller sphere inside, in a fixed order; twins beside their learner.
    const main = d.agents.filter((a) => !a.fixed_twin).sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
    const inner = sphere(main.length);
    const nodes: Node[] = main.map((a, i) => ({ agent: a, color: HEX[a.key] || GOLD, pos: inner[i].clone().multiplyScalar(R_AGENTS) }));
    d.agents.filter((a) => a.fixed_twin).forEach((a) => {
      const lead = nodes.find((n) => n.agent.key === a.key);
      const base = lead ? lead.pos.clone() : new THREE.Vector3(R_AGENTS, 0, 0);
      const side = new THREE.Vector3(0, 1, 0).cross(base).normalize().multiplyScalar(1.1);
      nodes.push({ agent: a, color: HEX[a.key] || GOLD, pos: base.multiplyScalar(1.28).add(side) });
    });
    return { markets, marketAt, nodes };
  }, [d]);
}

/** A curve from an agent out to a market, bowing outwards like a flight path. */
function arc(a: THREE.Vector3, b: THREE.Vector3, lift = 2.2) {
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const out = mid.length() > 0.5 ? mid.clone().normalize() : new THREE.Vector3(0, 1, 0);
  return new THREE.QuadraticBezierCurve3(a, mid.add(out.multiplyScalar(lift)), b);
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

/** A faint wire globe and its equator, so the sphere reads as a sphere. */
function Shell() {
  const geo = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(R_MARKETS * 0.985, 3), 1), []);
  const ring = useMemo(() => Array.from({ length: 129 }, (_, i) => {
    const t = (i / 128) * Math.PI * 2; return new THREE.Vector3(Math.cos(t) * R_MARKETS, 0, Math.sin(t) * R_MARKETS);
  }), []);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <>
      <lineSegments geometry={geo}><lineBasicMaterial color={GOLD} transparent opacity={0.045} depthWrite={false} /></lineSegments>
      <Line points={ring} color={GOLD} lineWidth={0.6} transparent opacity={0.16} />
    </>
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
      tmp.scale.setScalar(0.08 + Math.min(n, 7) * 0.026 + (lit ? 0.03 : 0));
      tmp.updateMatrix();
      m.setMatrixAt(i, tmp.matrix);
      col.set(mk.color).multiplyScalar(lit ? 1.7 : focusHeld ? 0.25 : 0.55);
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
        const p = arc(node.pos, m.pos).getPoint(0.3 + r() * 0.6);
        p.x += (r() - 0.5) * 0.8 * c; p.y += (r() - 0.5) * 0.8 * c; p.z += (r() - 0.5) * 0.8 * c;
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

function Scene({ d, day, focus, setFocus, onSelect, motion, labels }: {
  d: RunData; day: number; focus: string | null; setFocus: (id: string | null) => void;
  onSelect?: (a: Agent) => void; motion: boolean; labels: boolean;
}) {
  const { markets, marketAt, nodes } = useLayout(d);
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
        out.push({ key: n.agent.id + o.ticker + "p", agentId: n.agent.id, curve: arc(n.pos, m.pos, 3.2), color: n.color, pending: true });
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
      <Shell />
      {motion && <Sparkles count={90} scale={[40, 40, 40]} size={1.5} speed={0.16} color={GOLD} opacity={0.3} />}
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
          opacity={focus ? (focus === e.agentId ? 0.95 : 0.04) : e.pending ? 0.5 : 0.24}
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
      {nodes.map((n) => {
        const r = state.ret.get(n.agent.id)!;
        const on = focus === n.agent.id;
        if (!labels && !on) return null;
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
        <Html key={m.ticker} position={[m.pos.x * 1.04, m.pos.y * 1.04 + 0.3, m.pos.z * 1.04]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
          <div className={`v3-mk ${hoverMarket === m.ticker ? "on" : ""} ${labelled.has(m.ticker) ? "" : "off"}`}>
            {m.ticker}
            {hoverMarket === m.ticker && <span>{holders.length ? `held by ${holders.map((h) => h.agent.name).join(", ")}` : m.group}</span>}
          </div>
        </Html>
      ))}
    </>
  );
}

/** Frames the globe for the screen's shape, and exposes zoom and reset. */
function Rig({ controls, apiRef, wrap }: {
  controls: RefObject<OrbitControlsImpl | null>; apiRef?: RefObject<NetworkApi | null>; wrap: RefObject<HTMLDivElement | null>;
}) {
  const { camera, size } = useThree();
  const home = useRef(0);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const half = Math.tan(THREE.MathUtils.degToRad(cam.fov / 2));
    // Fit the globe (radius ~12.5) in the shorter side of the screen.
    const dist = Math.max(36, 16.2 / (half * Math.min(1, size.width / size.height)));
    if (!home.current || Math.abs(home.current - dist) > 1) {
      home.current = dist;
      cam.position.setLength(dist);
      controls.current?.update();
    }
  }, [camera, size, controls]);
  useEffect(() => {
    const zoom = (f: number) => {
      const c = controls.current; if (!c) return;
      const off = camera.position.clone().sub(c.target);
      off.setLength(THREE.MathUtils.clamp(off.length() * f, MIN_DIST, MAX_DIST));
      camera.position.copy(c.target).add(off);
      c.update();
    };
    const reset = () => {
      const c = controls.current; if (!c) return;
      c.target.set(0, 0, 0);
      camera.position.set(0, home.current * 0.3, home.current * 0.95).setLength(home.current);
      c.update();
    };
    if (apiRef) apiRef.current = { zoom, reset };
    // Pinch on a trackpad arrives as a wheel event with Ctrl held; a plain
    // scroll is left to the page.
    const el = wrap.current;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoom(Math.exp(e.deltaY * 0.01));
    };
    el?.addEventListener("wheel", onWheel, { passive: false });
    return () => el?.removeEventListener("wheel", onWheel);
  }, [camera, controls, apiRef, wrap]);
  return null;
}

export default function Network3D({ data, day, focus, setFocus, onSelect, apiRef, explore = false, labels = true }: {
  data: RunData; day: number; focus: string | null; setFocus: (id: string | null) => void; onSelect?: (a: Agent) => void;
  apiRef?: RefObject<NetworkApi | null>;
  /** On touch screens the globe only takes the finger (and stops page scrolling) in explore mode. */
  explore?: boolean;
  labels?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const controls = useRef<OrbitControlsImpl | null>(null);
  const [visible, setVisible] = useState(true);
  const [motion] = useState(() => !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [touch] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.02 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const grab = !touch || explore;
  useEffect(() => {
    // OrbitControls claims every touch on the canvas; give scrolling back
    // to the page unless the visitor is exploring.
    const el = controls.current?.domElement as HTMLElement | undefined;
    if (el) el.style.touchAction = grab ? "none" : "pan-y";
  });
  return (
    <div ref={wrap} className={`absolute inset-0 isolate ${grab ? (dragging ? "cursor-grabbing" : "cursor-grab") : ""}`} aria-hidden>
      <Canvas
        frameloop={visible ? "always" : "never"}
        dpr={[1, 1.75]}
        camera={{ position: [0, 9, 30], fov: 42, near: 0.1, far: 300 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        onPointerMissed={() => setFocus(null)}
      >
        <Scene d={data} day={day} focus={focus} setFocus={setFocus} onSelect={onSelect} motion={motion} labels={labels} />
        <OrbitControls
          ref={controls}
          makeDefault
          enableZoom={false}
          enablePan={false}
          enableRotate={grab}
          rotateSpeed={0.7}
          autoRotate={motion && !focus && !dragging}
          autoRotateSpeed={0.45}
          enableDamping
          dampingFactor={0.07}
          onStart={() => setDragging(true)}
          onEnd={() => setDragging(false)}
        />
        <Rig controls={controls} apiRef={apiRef} wrap={wrap} />
        <EffectComposer multisampling={0}>
          <Bloom mipmapBlur intensity={0.95} luminanceThreshold={0.62} luminanceSmoothing={0.25} radius={0.72} />
          <Vignette offset={0.22} darkness={0.72} />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
