/* Development only: a floating panel that switches the platform's fonts
 * live, to choose a pairing on the real pages. Never part of the build. */
import { Type, X } from "lucide-react";
import { useEffect, useState } from "react";

interface Pairing { id: string; name: string; mood: string; display: string; body: string; weight: number; tracking: string }

const PAIRINGS: Pairing[] = [
  { id: "current", name: "Instrument Serif + Geist", mood: "The current look: elegant serif headlines", display: '"Instrument Serif", serif', body: '"Geist Variable", sans-serif', weight: 400, tracking: "-0.012em" },
  { id: "inter", name: "Inter Tight + Inter", mood: "Clean fintech, like Stripe or Linear", display: '"Inter Tight", sans-serif', body: '"Inter", sans-serif', weight: 600, tracking: "-0.035em" },
  { id: "manrope", name: "Manrope", mood: "Modern and premium, one family throughout", display: '"Manrope", sans-serif', body: '"Manrope", sans-serif', weight: 600, tracking: "-0.035em" },
  { id: "playfair", name: "Playfair Display + Inter", mood: "Luxury editorial, like a private bank", display: '"Playfair Display", serif', body: '"Inter", sans-serif', weight: 500, tracking: "-0.015em" },
  { id: "cormorant", name: "Cormorant Garamond + Manrope", mood: "High-end and classic, like a jeweller", display: '"Cormorant Garamond", serif', body: '"Manrope", sans-serif', weight: 600, tracking: "-0.01em" },
  { id: "grotesk", name: "Space Grotesk + DM Sans", mood: "Techy and bold, like a trading terminal", display: '"Space Grotesk", sans-serif', body: '"DM Sans", sans-serif', weight: 600, tracking: "-0.035em" },
];

const FONTS = "https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400..700;1,400..700&family=Inter+Tight:ital,wght@0,500..700;1,500..700"
  + "&family=Manrope:wght@400..700&family=Playfair+Display:ital,wght@0,400..700;1,400..700&family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500;1,600"
  + "&family=Space+Grotesk:wght@400..700&family=DM+Sans:ital,wght@0,400..700;1,400..700&display=swap";

function apply(p: Pairing) {
  const s = document.documentElement.style;
  s.setProperty("--font-display", p.display);
  s.setProperty("--font-sans", p.body);
  s.setProperty("--display-weight", String(p.weight));
  s.setProperty("--display-tracking", p.tracking);
}

export default function FontLab() {
  const [open, setOpen] = useState(true);
  const [pick, setPick] = useState(() => { try { return localStorage.getItem("v3-font-lab") || "current"; } catch { return "current"; } });
  useEffect(() => {
    if (!document.getElementById("v3-font-lab")) {
      const l = document.createElement("link");
      l.id = "v3-font-lab"; l.rel = "stylesheet"; l.href = FONTS;
      document.head.appendChild(l);
    }
  }, []);
  useEffect(() => {
    apply(PAIRINGS.find((p) => p.id === pick) || PAIRINGS[0]);
    try { localStorage.setItem("v3-font-lab", pick); } catch { /* storage unavailable */ }
  }, [pick]);
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="glass fixed bottom-4 left-4 z-[70] inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-[13px] text-ink">
        <Type size={15} className="text-gold" /> Fonts
      </button>
    );
  }
  return (
    <div className="glass fixed bottom-4 left-4 z-[70] w-[330px] rounded-2xl p-3 text-ink shadow-2xl" style={{ fontFamily: '"Geist Variable", sans-serif' }}>
      <div className="mb-2 flex items-center justify-between px-2 pt-1">
        <div>
          <div className="text-[13px] font-medium">Pick a font</div>
          <div className="text-[11px] text-muted">Preview only: the whole site switches</div>
        </div>
        <button type="button" onClick={() => setOpen(false)} aria-label="Hide" className="grid size-7 place-items-center rounded-full text-muted hover:text-ink"><X size={14} /></button>
      </div>
      <ul className="grid gap-1">
        {PAIRINGS.map((p, i) => (
          <li key={p.id}>
            <button type="button" onClick={() => setPick(p.id)} aria-pressed={pick === p.id}
              className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${pick === p.id ? "border-gold/60 bg-gold-wash" : "border-transparent hover:bg-surface-2"}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span style={{ fontFamily: p.display, fontWeight: p.weight, letterSpacing: p.tracking }} className="text-[22px] leading-tight">{i + 1}. Bargain Hunter</span>
                <span style={{ fontFamily: p.body }} className="tabular text-[13px] text-up">+2.20%</span>
              </div>
              <div style={{ fontFamily: p.body }} className="mt-0.5 text-[12px] text-ink-2">{p.name}</div>
              <div className="text-[11px] text-muted">{p.mood}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
