/* Number and date formatting, in one place so every page reads the same:
 * Swiss-style CHF amounts (100’000), signed percentages, short dates. */

const chf0 = new Intl.NumberFormat("de-CH", { maximumFractionDigits: 0 });
const chf2f = new Intl.NumberFormat("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

const ok = (v: number | null | undefined): v is number => v != null && isFinite(v);

export const chf = (v: number | null | undefined) => (ok(v) ? chf0.format(v) : "–");
export const chf2 = (v: number | null | undefined) => (ok(v) ? chf2f.format(v) : "–");
export const signedChf = (v: number | null | undefined) => (ok(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + chf0.format(Math.abs(v)) : "–");
export const num = (v: number | null | undefined, d = 2) => (ok(v) ? v.toFixed(d) : "–");
export const big = (v: number) => compact.format(v);

/** +2.20% / −1.90% (a true minus sign, so columns line up). */
export const pct = (v: number | null | undefined, d = 2) =>
  ok(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%" : "–";
/** 42% / 4.2% without a sign. */
export const share = (v: number | null | undefined, d = 0) => (ok(v) ? (v * 100).toFixed(d) + "%" : "–");

/** "up" / "down" / "" for colouring a change. */
export const tone = (v: number | null | undefined) => (!ok(v) || v === 0 ? "" : v > 0 ? "text-up" : "text-down");

const ts = (d: string) => Date.parse(d.length === 10 ? d + "T00:00:00Z" : d);
export const date = (d: string | null | undefined) =>
  d ? new Date(ts(d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "–";
export const dateShort = (d: string | null | undefined) =>
  d ? new Date(ts(d)).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : "–";
export const weekday = (d: string) =>
  new Date(ts(d)).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
export const swissTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Zurich" });

/** Trading days between two ISO dates, counting the equity points. */
export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;

/** The next evening run: weekdays after the New York close (about 22:40 in
 *  Zurich), shown in the visitor's own time zone. */
export function nextRun(now = new Date()) {
  const t = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 20, 40));
  // Winter time in New York: the close is an hour later in UTC.
  const ny = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", timeZoneName: "short" }).format(now);
  if (ny.includes("EST")) t.setUTCHours(21);
  if (t <= now) t.setUTCDate(t.getUTCDate() + 1);
  while ([0, 6].includes(t.getUTCDay())) t.setUTCDate(t.getUTCDate() + 1);
  return t;
}
export const nextRunLabel = (now = new Date()) =>
  nextRun(now).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
