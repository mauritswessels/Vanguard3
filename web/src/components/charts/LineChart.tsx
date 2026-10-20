/* Time-series lines on TradingView's Lightweight Charts, styled for the
 * platform: hairline grid, gold crosshair, no clutter on the price axis. The
 * legend lives outside the canvas (see RaceChart) so it can show every
 * line's value at the hovered day. */
import {
  ColorType, CrosshairMode, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Point } from "../../lib/types";
import { useChartTheme } from "./useChartTheme";

export interface Line {
  id: string;
  points: Point[];
  color: string;
  style?: "solid" | "dashed" | "dotted";
  width?: number;
  hidden?: boolean;
  markers?: { date: string; side: "BUY" | "SELL"; text?: string }[];
}

const STYLE = { solid: LineStyle.Solid, dashed: LineStyle.Dashed, dotted: LineStyle.Dotted };
const time = (d: string) => (Date.parse(d + "T00:00:00Z") / 1000) as UTCTimestamp;

export function LineChart({ lines, format, height = 380, onHover, zeroLine, className }: {
  lines: Line[];
  format: (v: number) => string;
  height?: number;
  /** The hovered date and each line's value there (null when the pointer leaves). */
  onHover?: (date: string | null, values: Map<string, number>) => void;
  zeroLine?: number;
  className?: string;
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef(new Map<string, ISeriesApi<"Line">>());
  const markers = useRef(new Map<string, ISeriesMarkersPluginApi<Time>>());
  const zero = useRef<{ series: ISeriesApi<"Line">; line: IPriceLine } | null>(null);
  const theme = useChartTheme();
  const hover = useRef(onHover);
  hover.current = onHover;
  const fmt = useRef(format);
  fmt.current = format;

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontFamily: "Geist Variable, ui-sans-serif, system-ui", fontSize: 11.5, attributionLogo: false },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: {
        borderVisible: false, fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true,
        tickMarkFormatter: (t: Time) => new Date((t as number) * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }),
      },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: false },
      localization: {
        priceFormatter: (v: number) => fmt.current(v),
        timeFormatter: (t: Time) => new Date((t as number) * 1000).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }),
      },
    });
    chart.current = c;
    c.subscribeCrosshairMove((p) => {
      if (!hover.current) return;
      if (!p.time || !p.point) { hover.current(null, new Map()); return; }
      const vals = new Map<string, number>();
      series.current.forEach((s, id) => {
        const v = p.seriesData.get(s) as { value?: number } | undefined;
        if (v && v.value != null) vals.set(id, v.value);
      });
      hover.current(new Date((p.time as number) * 1000).toISOString().slice(0, 10), vals);
    });
    return () => { c.remove(); chart.current = null; series.current.clear(); markers.current.clear(); zero.current = null; };
  }, []);

  useEffect(() => {
    chart.current?.applyOptions({
      layout: { textColor: theme.muted },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.line, style: LineStyle.Solid } },
      crosshair: {
        vertLine: { color: theme.gold, width: 1, style: LineStyle.Dashed, labelBackgroundColor: theme.gold },
        horzLine: { color: theme.faint, width: 1, style: LineStyle.Dotted, labelBackgroundColor: theme.surface },
      },
    });
  }, [theme]);

  useEffect(() => {
    const c = chart.current; if (!c) return;
    const keep = new Set(lines.map((l) => l.id));
    series.current.forEach((s, id) => {
      if (keep.has(id)) return;
      if (zero.current?.series === s) zero.current = null;
      c.removeSeries(s); series.current.delete(id); markers.current.delete(id);
    });
    lines.forEach((l) => {
      let s = series.current.get(l.id);
      if (!s) {
        s = c.addSeries(LineSeries, { priceLineVisible: false, lastValueVisible: false, crosshairMarkerRadius: 3.5, crosshairMarkerBorderWidth: 0 });
        series.current.set(l.id, s);
      }
      s.applyOptions({ color: l.color, lineWidth: (l.width ?? 2) as 1 | 2 | 3 | 4, lineStyle: STYLE[l.style || "solid"], visible: !l.hidden, pointMarkersVisible: l.points.length < 25 && !l.markers, pointMarkersRadius: 2.5 });
      s.setData(l.points.map(([d, v]) => ({ time: time(d) as Time, value: v })));
      const ms: SeriesMarker<Time>[] = (l.markers || []).map((m) => ({
          time: time(m.date) as Time,
          position: m.side === "BUY" ? "belowBar" : "aboveBar",
          shape: m.side === "BUY" ? "arrowUp" : "arrowDown",
          color: m.side === "BUY" ? theme.up : theme.down,
          text: m.text,
        }));
      const plugin = markers.current.get(l.id);
      if (plugin) plugin.setMarkers(ms);
      else if (ms.length) markers.current.set(l.id, createSeriesMarkers(s, ms));
    });
    if (zero.current) { zero.current.series.removePriceLine(zero.current.line); zero.current = null; }
    const first = series.current.values().next().value;
    if (zeroLine != null && first) {
      zero.current = { series: first, line: first.createPriceLine({ price: zeroLine, color: theme.faint, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" }) };
    }
    c.timeScale().fitContent();
  }, [lines, theme, zeroLine]);

  return <div ref={el} className={className} style={{ height }} />;
}
