/* Routes. Hash URLs (…/#/agents/trend) work on GitHub Pages without any
 * server setup, and every page can be linked to directly. */
import { lazy, Suspense } from "react";
import { HashRouter, Link, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { Section } from "./components/ui";
import { LiveProvider } from "./lib/data";
import Home from "./pages/Home";

const Agents = lazy(() => import("./pages/Agents"));
const AgentProfile = lazy(() => import("./pages/AgentProfile"));
const Trades = lazy(() => import("./pages/Trades"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Research = lazy(() => import("./pages/Research"));
const Methodology = lazy(() => import("./pages/Methodology"));
const Journal = lazy(() => import("./pages/Journal"));
const About = lazy(() => import("./pages/About"));
// Development only: the font picker used to choose the platform's type.
const FontLab = import.meta.env.DEV ? lazy(() => import("./dev/FontLab")) : null;

function Loading() {
  return <Section><div className="h-[60vh] animate-pulse rounded-3xl bg-surface" /></Section>;
}

function NotFound() {
  return (
    <Section>
      <div className="py-24 text-center">
        <div className="eyebrow text-gold">404</div>
        <h1 className="display mt-4 text-5xl">This page is not on the map</h1>
        <Link to="/" className="mt-8 inline-block text-gold hover:text-gold-2">Back to the live race →</Link>
      </div>
    </Section>
  );
}

export default function App() {
  return (
    <HashRouter>
      <LiveProvider>
        <Layout>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/agents/:id" element={<AgentProfile />} />
              <Route path="/trades" element={<Trades />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/research" element={<Research />} />
              <Route path="/methodology" element={<Methodology />} />
              <Route path="/journal" element={<Journal />} />
              <Route path="/about" element={<About />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
          {FontLab && <Suspense fallback={null}><FontLab /></Suspense>}
        </Layout>
      </LiveProvider>
    </HashRouter>
  );
}
