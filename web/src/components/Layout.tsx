/* The frame around every page: a glass navigation bar with the live status
 * and the theme switch, and a footer with the project's fine print. */
import { Menu, Moon, Sun, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router";
import { useLive } from "../lib/data";
import { dateShort } from "../lib/format";
import { Container, Logo, cx } from "./ui";

const PRIMARY: [string, string][] = [
  ["/", "Live race"], ["/agents", "Agents"], ["/trades", "Trades"], ["/analytics", "Analytics"], ["/research", "Research"],
];
const SECONDARY: [string, string][] = [["/methodology", "Methodology"], ["/journal", "Journal"], ["/about", "About"]];

export function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "dark");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f7f4ee" : "#0b0a08");
    try { localStorage.setItem("v3-theme", theme); } catch { /* storage unavailable */ }
    window.dispatchEvent(new Event("v3-theme"));
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "light" ? "dark" : "light"))] as const;
}

function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const light = theme === "light";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={light ? "Switch to dark mode" : "Switch to light mode"}
      className="grid size-9 place-items-center rounded-full border border-line-2 text-ink-2 transition-colors hover:border-gold/40 hover:text-gold"
    >
      {light ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}

function LiveStatus() {
  const d = useLive();
  if (!d) return null;
  return (
    <span className="hidden items-center gap-2 rounded-full border border-line-2 px-3 py-1.5 text-[12px] text-ink-2 sm:inline-flex" title={`Prices up to the ${d.last} close, from ${d.data_source}`}>
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-up opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-up" />
      </span>
      Live · {dateShort(d.last)} close
    </span>
  );
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cx("relative rounded-full px-3 py-1.5 text-[13.5px] font-medium transition-colors",
    isActive ? "text-ink" : "text-muted hover:text-ink");

function Nav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className={cx("sticky top-0 z-50 transition-[background,border-color] duration-300",
      scrolled || open ? "glass border-x-0 border-t-0" : "border-b border-transparent")}>
      <Container className="flex h-16 items-center gap-4">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Vanguard3 home">
          <Logo />
          <span className="text-[17px] font-semibold tracking-tight">Vanguard<span className="text-gold">3</span></span>
        </Link>
        <nav className="ml-6 hidden items-center gap-0.5 lg:flex" aria-label="Main">
          {PRIMARY.map(([to, l]) => (
            <NavLink key={to} to={to} end={to === "/"} className={linkClass}>
              {({ isActive }) => (<>{l}{isActive && <span className="absolute inset-x-3 -bottom-[13px] h-px bg-gold" />}</>)}
            </NavLink>
          ))}
          <span className="mx-2 h-4 w-px bg-line-2" />
          {SECONDARY.map(([to, l]) => (
            <NavLink key={to} to={to} className={linkClass}>
              {({ isActive }) => (<>{l}{isActive && <span className="absolute inset-x-3 -bottom-[13px] h-px bg-gold" />}</>)}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <LiveStatus />
          <ThemeToggle />
          <button
            type="button"
            className="grid size-9 place-items-center rounded-full border border-line-2 text-ink-2 lg:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </Container>
      {open && (
        <nav className="border-t border-line lg:hidden" aria-label="Main">
          <Container className="grid gap-1 py-4">
            {[...PRIMARY, ...SECONDARY].map(([to, l]) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => cx("rounded-xl px-3 py-2.5 text-[15px]", isActive ? "bg-gold-wash text-gold" : "text-ink-2")}>
                {l}
              </NavLink>
            ))}
          </Container>
        </nav>
      )}
    </header>
  );
}

function Footer() {
  const d = useLive();
  return (
    <footer className="mt-10 border-t border-line">
      <Container className="grid gap-10 py-14 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="max-w-sm">
          <div className="flex items-center gap-2.5">
            <Logo size={24} />
            <span className="font-semibold">Vanguard<span className="text-gold">3</span></span>
          </div>
          <p className="mt-4 text-[13.5px] leading-relaxed text-muted">
            A live, open experiment: can trading agents, from simple rules to large language models, beat the market and beat luck?
            Paper money only. No real orders are placed by this site, and nothing here is investment advice.
          </p>
        </div>
        <div>
          <div className="eyebrow mb-4">Explore</div>
          <ul className="grid gap-2 text-[14px] text-ink-2">
            {PRIMARY.map(([to, l]) => <li key={to}><Link className="link-underline hover:text-ink" to={to}>{l}</Link></li>)}
          </ul>
        </div>
        <div>
          <div className="eyebrow mb-4">Project</div>
          <ul className="grid gap-2 text-[14px] text-ink-2">
            {SECONDARY.map(([to, l]) => <li key={to}><Link className="link-underline hover:text-ink" to={to}>{l}</Link></li>)}
            <li><a className="link-underline hover:text-ink" href="https://github.com/mauritswessels/Vanguard3">Source code</a></li>
          </ul>
        </div>
      </Container>
      <Container className="flex flex-col gap-2 border-t border-line py-6 text-[12px] text-faint sm:flex-row sm:justify-between">
        <span>{d ? `Prices to the ${dateShort(d.last)} close · ${d.data_source} · updated every weekday after the New York close` : "Updated every weekday after the New York close"}</span>
        <span>Charts by <a className="link-underline hover:text-ink-2" href="https://www.tradingview.com/">TradingView</a> · Not affiliated with The Vanguard Group.</span>
      </Container>
    </footer>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const loc = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-lg focus:bg-gold focus:px-3 focus:py-2 focus:text-gold-ink">Skip to content</a>
      <Nav />
      <main id="main" className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
