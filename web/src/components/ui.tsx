/* Small shared building blocks: sections, stat tiles, agent swatches,
 * segmented controls and signed numbers. */
import type { ReactNode } from "react";
import { color } from "../lib/agents";
import { tone } from "../lib/format";
import type { Agent } from "../lib/types";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("mx-auto w-full max-w-[1240px] px-4 sm:px-6 lg:px-8", className)}>{children}</div>;
}

export function Section({ id, children, className }: { id?: string; children: ReactNode; className?: string }) {
  return (
    <section id={id} className={cx("scroll-mt-24 py-12 sm:py-16", className)}>
      <Container>{children}</Container>
    </section>
  );
}

/** Eyebrow, serif title and an optional line of context, with controls on the right. */
export function SectionHead({ eyebrow, title, intro, right }: {
  eyebrow?: string; title: ReactNode; intro?: ReactNode; right?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="max-w-2xl">
        {eyebrow && <div className="eyebrow mb-3 text-gold">{eyebrow}</div>}
        <h2 className="display text-[2.1rem] sm:text-[2.6rem]">{title}</h2>
        {intro && <p className="mt-3 text-[15px] text-ink-2">{intro}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, valueClass, accent }: {
  label: string; value: ReactNode; sub?: ReactNode; valueClass?: string; accent?: boolean;
}) {
  return (
    <div className={cx("card flex min-w-0 flex-col justify-between gap-3 p-5", accent && "ring-1 ring-gold/25")}>
      <div className="eyebrow">{label}</div>
      <div>
        <div className={cx("tabular text-[1.65rem] font-medium leading-none tracking-tight", valueClass)}>{value}</div>
        {sub && <div className="mt-2 text-[13px] text-muted">{sub}</div>}
      </div>
    </div>
  );
}

/** The agent's colour: a filled dot, or a ring for a fixed twin. */
export function Swatch({ agent, size = 10 }: { agent: Pick<Agent, "key" | "fixed_twin" | "benchmark">; size?: number }) {
  const c = color(agent.key);
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-full"
      style={{
        width: size, height: size,
        background: agent.fixed_twin ? "transparent" : c,
        border: agent.fixed_twin ? `2px solid ${c}` : undefined,
        boxShadow: agent.fixed_twin || agent.benchmark ? undefined : `0 0 10px ${c}`,
      }}
    />
  );
}

export function Badge({ children, tone: t = "neutral" }: { children: ReactNode; tone?: "neutral" | "gold" | "up" | "down" }) {
  const styles = {
    neutral: "border-line-2 text-ink-2",
    gold: "border-gold/30 bg-gold-wash text-gold",
    up: "border-up/25 bg-up-wash text-up",
    down: "border-down/25 bg-down-wash text-down",
  }[t];
  return <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11.5px] font-medium", styles)}>{children}</span>;
}

/** A signed number coloured by direction. */
export function Delta({ value, children, className }: { value: number | null | undefined; children: ReactNode; className?: string }) {
  return <span className={cx("tabular", tone(value), className)}>{children}</span>;
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: [T, string][]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full border border-line-2 bg-surface p-1">
      {options.map(([k, l]) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={k === value}
          onClick={() => onChange(k)}
          className={cx(
            "rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors",
            k === value ? "bg-gold text-gold-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-line-2 px-5 py-8 text-center text-[14px] text-muted">{children}</div>;
}

/** The Vanguard3 mark: a gold V whose right stroke rises like a chart, with the live point at its tip. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="v3g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f6dfa4" />
          <stop offset="0.55" stopColor="#d4b26a" />
          <stop offset="1" stopColor="#9c7a33" />
        </linearGradient>
      </defs>
      <path d="M4.5 7.5h4.2l7.1 15.2-2.2 4.8z" fill="url(#v3g)" opacity="0.72" />
      <path d="M13.6 27.5 25.3 4.5h3.9L16.8 27.5z" fill="url(#v3g)" />
      <circle cx="27.3" cy="4.6" r="2.1" fill="#f6dfa4" />
    </svg>
  );
}
