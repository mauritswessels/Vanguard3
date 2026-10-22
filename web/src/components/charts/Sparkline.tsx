/* A tiny inline line of an account's value, ending in a dot. */
import { useId } from "react";
import type { Point } from "../../lib/types";

export function Sparkline({ points, color, width = 112, height = 32, fill = true }: {
  points: Point[]; color: string; width?: number; height?: number; fill?: boolean;
}) {
  const id = useId();
  if (points.length < 2) return <svg width={width} height={height} aria-hidden />;
  const ys = points.map((p) => p[1]), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const X = (i: number) => 2 + (i * (width - 6)) / (points.length - 1);
  const Y = (v: number) => height - 3 - ((v - lo) * (height - 6)) / span;
  const d = ys.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="overflow-visible">
      {fill && (
        <>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={color} stopOpacity="0.22" />
              <stop offset="1" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={`${d}L${X(ys.length - 1)},${height}L${X(0)},${height}Z`} fill={`url(#${id})`} />
        </>
      )}
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={X(ys.length - 1)} cy={Y(ys[ys.length - 1])} r="2.6" fill={color} />
    </svg>
  );
}
