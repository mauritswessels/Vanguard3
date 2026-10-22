/* Chart canvases cannot read CSS variables, so charts read the resolved
 * colours here and redraw when the visitor switches theme. */
import { useEffect, useState } from "react";

export interface ChartTheme {
  text: string; muted: string; faint: string; line: string; gold: string; up: string; down: string; surface: string;
  series: (key: string) => string;
}

function read(): ChartTheme {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    text: v("--text"), muted: v("--muted"), faint: v("--faint"), line: v("--line-2"), gold: v("--gold"),
    up: v("--up"), down: v("--down"), surface: v("--surface"),
    series: (key) => v(`--s-${key}`) || v("--muted"),
  };
}

export function useChartTheme() {
  const [t, setT] = useState(read);
  useEffect(() => {
    const on = () => setT(read());
    window.addEventListener("v3-theme", on);
    return () => window.removeEventListener("v3-theme", on);
  }, []);
  return t;
}
