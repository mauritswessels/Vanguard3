/* Loading the bots' JSON files from data/ (served by GitHub Pages next to
 * the app). The live race is checked again every 5 minutes, so a page left
 * open picks up the evening run and the midday check by itself. */
import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from "react";
import type { RunData } from "./types";

/** Round trips may name the fills that opened and closed them (to keep the
 *  file small): attach those fills' decisions. */
export function hydrate<T extends { agents?: RunData["agents"] }>(d: T): T {
  (d?.agents || []).forEach((a) => {
    const byId = new Map(a.trades.map((t) => [t.id, t]));
    const dec = (id?: number) => (id == null ? null : byId.get(id)?.decision ?? null);
    (a.trips || []).forEach((t) => {
      if (t.entry === undefined) t.entry = dec(t.entry_fill);
      if (t.exit === undefined) t.exit = dec(t.exit_fill);
    });
  });
  return d;
}

const memo = new Map<string, Promise<unknown>>();

/** Fetch data/<name>.json once per page load (or again with fresh). Missing
 *  files resolve to null, so a page can say "not yet" instead of failing. */
export function loadJSON<T>(name: string, fresh = false): Promise<T | null> {
  if (fresh || !memo.has(name)) {
    memo.set(name, fetch(`data/${name}.json`, { cache: fresh ? "no-store" : "default" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => (j && j.agents ? hydrate(j) : j))
      .catch(() => null));
  }
  return memo.get(name) as Promise<T | null>;
}

/** A JSON file from another site (GitHub serves raw files to any page).
 *  Missing or unreachable resolves to null. */
export function useRemoteJSON<T>(url: string): T | null | undefined {
  const [v, setV] = useState<T | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    if (!memo.has(url)) memo.set(url, fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null));
    (memo.get(url) as Promise<T | null>).then((j) => { if (live) setV(j); });
    return () => { live = false; };
  }, [url]);
  return v;
}

/** Where the cloud server publishes the IBKR paper account's summary (README, "Simulation vs reality"). */
export const IBKR_URL = "https://raw.githubusercontent.com/mauritswessels/vanguard3-ibkr-data/ibkr-data/ibkr.json";

/** A data file for one page; undefined while loading (or while name is
 *  null, for a file only loaded on request), null when missing. */
export function useJSON<T>(name: string | null): T | null | undefined {
  const [v, setV] = useState<T | null | undefined>(undefined);
  useEffect(() => {
    if (!name) { setV(undefined); return; }
    let live = true;
    loadJSON<T>(name).then((j) => { if (live) setV(j); });
    return () => { live = false; };
  }, [name]);
  return v;
}

interface Live { data: RunData | null | undefined; updated: number }
const LiveContext = createContext<Live>({ data: undefined, updated: 0 });

export function LiveProvider({ children }: { children: ReactNode }) {
  const [live, setLive] = useState<Live>({ data: undefined, updated: 0 });
  useEffect(() => {
    let current = "";
    const check = async (fresh: boolean) => {
      if (document.hidden && current) return;
      const d = await loadJSON<RunData>("paper", fresh);
      if (!d) { if (!current) setLive({ data: null, updated: Date.now() }); return; }
      if (d.generated_utc !== current) {
        current = d.generated_utc;
        setLive({ data: d, updated: Date.now() });
      }
    };
    check(false);
    const timer = setInterval(() => check(true), 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, []);
  return createElement(LiveContext.Provider, { value: live }, children);
}

/** The live paper-trading race (data/paper.json). */
export const useLive = () => useContext(LiveContext).data;
