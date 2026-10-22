/* The project journal: Claude's weekly reports on the race, then a timeline
 * of how Vanguard3 grew (content/journal.ts). */
import { ScrollText } from "lucide-react";
import { useState } from "react";
import { Badge, Section, cx } from "../components/ui";
import { JOURNAL, NEXT } from "../content/journal";
import { useJSON } from "../lib/data";
import { date, dateShort } from "../lib/format";
import type { WeeklyData } from "../lib/types";

/** The week in plain words: Claude's Saturday report, newest first. */
function Weekly() {
  const w = useJSON<WeeklyData>("weekly");
  const [pick, setPick] = useState(0);
  const reports = w?.reports || [];
  const r = reports[pick];
  if (w === undefined) return <div className="h-72 animate-pulse rounded-3xl bg-surface" />;
  if (!r) return null;
  const paras = r.text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  return (
    <article className="card relative overflow-hidden p-7 sm:p-10">
      <div className="pointer-events-none absolute -right-20 -top-20 size-64 rounded-full bg-gold/10 blur-3xl" />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="eyebrow flex items-center gap-2 text-gold"><ScrollText size={13} /> The week in plain words</div>
        {reports.length > 1 && (
          <div className="flex flex-wrap gap-1.5">
            {reports.map((x, i) => (
              <button key={x.week_end} type="button" onClick={() => setPick(i)} aria-pressed={i === pick}
                className={cx("rounded-full border px-3 py-1 text-[12px]", i === pick ? "border-gold/50 bg-gold-wash text-ink" : "border-line-2 text-muted hover:text-ink")}>
                {dateShort(x.week_end)}
              </button>
            ))}
          </div>
        )}
      </div>
      <h2 className="display text-[2.2rem]">{dateShort(r.week_start)} – {date(r.week_end)}</h2>
      <div className="prose-v3 mt-6 max-w-[720px] text-[16px] leading-[1.8] text-ink-2">
        <p className="text-[17px] text-ink first-letter:float-left first-letter:mr-2 first-letter:font-[family-name:var(--font-display)] first-letter:text-[3.6rem] first-letter:leading-[0.85] first-letter:text-gold">{paras[0]}</p>
        {paras.slice(1).map((p, i) => <p key={i}>{p}</p>)}
      </div>
      <p className="mt-6 border-t border-line pt-4 text-[12px] text-muted">Written by Claude every Saturday from the week's facts. It describes; it decides nothing.</p>
    </article>
  );
}

export default function Journal() {
  const months = [...new Set(JOURNAL.map((e) => e.date.slice(0, 7)))];
  return (
    <>
      <Section className="pb-6">
        <div className="max-w-3xl">
          <div className="eyebrow mb-4 text-gold">Project journal</div>
          <h1 className="display text-[3rem] sm:text-[4.2rem]">How Vanguard3 grew</h1>
          <p className="mt-5 text-[17px] leading-relaxed text-ink-2">Claude's weekly report on the race, and how the project grew from three hand-written trading rules to Claude reading the news, a broker connection and a study of luck.</p>
        </div>
      </Section>
      <Section className="pt-4">
        <Weekly />
      </Section>
      <Section className="pt-0">
        <div className="mx-auto max-w-3xl">
          <div className="eyebrow mb-8 text-gold">Timeline</div>
          {months.map((m) => (
            <div key={m}>
              <div className="display mb-6 text-[1.6rem] text-gold">{new Date(m + "-01T00:00:00Z").toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</div>
              <ol className="relative mb-12 grid gap-8 border-l border-line-2 pl-8">
                {JOURNAL.filter((e) => e.date.startsWith(m)).map((e) => (
                  <li key={e.date + e.title} className="relative">
                    <span className="absolute -left-[38px] top-1.5 grid size-[19px] place-items-center rounded-full border border-gold/50 bg-bg"><span className="size-[7px] rounded-full bg-gold" /></span>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
                      {date(e.date)} <Badge tone="gold">{e.tag}</Badge>{e.pending && <Badge>in progress</Badge>}
                    </div>
                    <h2 className="text-[19px] font-medium">{e.title}</h2>
                    <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{e.text}</p>
                  </li>
                ))}
              </ol>
            </div>
          ))}
          <div className="card p-7">
            <div className="eyebrow mb-3 text-gold">What's next</div>
            <ul className="grid gap-3 text-[15px] text-ink-2">
              {NEXT.map((n) => <li key={n} className="flex gap-3"><span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-gold" />{n}</li>)}
            </ul>
          </div>
        </div>
      </Section>
    </>
  );
}
