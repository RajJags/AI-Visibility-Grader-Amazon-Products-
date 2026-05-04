"use client";

import { useState, useEffect } from "react";
import {
  runDiagnostic,
  type DiagnoseResponse,
  type DiagnoseRequest,
  APIError,
} from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
import LoadingScreen    from "@/components/LoadingScreen";
import ScoreHero        from "@/components/ScoreHero";
import ModelCard        from "@/components/ModelCard";
import QueryTable       from "@/components/QueryTable";
import CompetitorList   from "@/components/CompetitorList";
import RecommendationCard from "@/components/RecommendationCard";

// ── State machine ─────────────────────────────────────────────────────────────
type State =
  | { status: "idle" }
  | { status: "loading"; asin: string }
  | { status: "result"; data: DiagnoseResponse }
  | { status: "error"; message: string }
  | { status: "manual"; asin: string };

// ── Root component ────────────────────────────────────────────────────────────
export default function Home() {
  const [asin, setAsin] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });

  // Warm up the Render backend on page load to reduce cold-start delay
  useEffect(() => {
    fetch(`${API_URL}/health`).catch(() => {/* ignore - best effort warmup */});
  }, []);
  const [manualBrand, setManualBrand] = useState("");
  const [manualTitle, setManualTitle] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = asin.trim();
    if (!trimmed) return;
    setState({ status: "loading", asin: trimmed });
    try {
      const data = await runDiagnostic({ asin: trimmed });
      setState({ status: "result", data });
    } catch (err) {
      if (err instanceof APIError && err.status === 422) {
        setState({ status: "manual", asin: trimmed });
      } else {
        setState({
          status: "error",
          message: err instanceof APIError ? err.message : "Something went wrong. Check the ASIN and try again.",
        });
      }
    }
  }

  async function handleManualSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!manualBrand.trim() || !manualTitle.trim()) return;
    const currentAsin = state.status === "manual" ? state.asin : asin;
    setState({ status: "loading", asin: currentAsin });
    try {
      const req: DiagnoseRequest = { asin: currentAsin, brand: manualBrand.trim(), title: manualTitle.trim() };
      const data = await runDiagnostic(req);
      setState({ status: "result", data });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof APIError ? err.message : "Something went wrong. Try again.",
      });
    }
  }

  function reset() {
    setState({ status: "idle" });
    setAsin(""); setManualBrand(""); setManualTitle("");
  }

  // ── Loading ────────────────────────────────────────────────────────────────
  if (state.status === "loading") {
    return <LoadingScreen asin={state.asin} />;
  }

  // ── Result ─────────────────────────────────────────────────────────────────
  if (state.status === "result") {
    return <ReportView data={state.data} onReset={reset} />;
  }

  // ── Manual override ────────────────────────────────────────────────────────
  if (state.status === "manual") {
    return (
      <main className="min-h-screen flex items-center justify-center px-6 bg-white">
        <div className="w-full max-w-md">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-2">
            Product lookup failed
          </p>
          <h2 className="text-2xl font-bold text-neutral-900 mb-2">Enter product details</h2>
          <p className="text-sm text-neutral-500 mb-8 leading-relaxed">
            We couldn't fetch data for{" "}
            <code className="font-mono bg-neutral-100 px-1.5 py-0.5 rounded text-neutral-700">
              {state.asin}
            </code>
            . Enter the brand and title to continue.
          </p>
          <form onSubmit={handleManualSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-sm font-medium text-neutral-700 mb-1.5">Brand</label>
              <input
                autoFocus type="text" value={manualBrand}
                onChange={(e) => setManualBrand(e.target.value)}
                placeholder="e.g. Doctor's Best"
                className="w-full border border-neutral-200 rounded-xl px-4 h-12 text-sm text-neutral-900 placeholder-neutral-400 focus:outline-none focus:border-accent transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 mb-1.5">Product title</label>
              <input
                type="text" value={manualTitle}
                onChange={(e) => setManualTitle(e.target.value)}
                placeholder="e.g. High Absorption Magnesium Glycinate"
                className="w-full border border-neutral-200 rounded-xl px-4 h-12 text-sm text-neutral-900 placeholder-neutral-400 focus:outline-none focus:border-accent transition-colors"
              />
            </div>
            <div className="flex gap-3 pt-2">
              <button
                type="button" onClick={reset}
                className="flex-1 h-12 border border-neutral-200 rounded-xl text-sm font-medium text-neutral-600 hover:border-neutral-400 transition-colors"
              >
                ← Back
              </button>
              <button
                type="submit"
                disabled={!manualBrand.trim() || !manualTitle.trim()}
                className="flex-1 h-12 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors"
              >
                Run Diagnostic
              </button>
            </div>
          </form>
        </div>
      </main>
    );
  }

  // ── Landing ────────────────────────────────────────────────────────────────
  return (
    <main className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="border-b border-neutral-200 h-16 flex items-center px-6 md:px-10">
        <div className="max-w-content mx-auto w-full flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-5 h-5 rounded-sm bg-accent flex-shrink-0" />
            <span className="font-semibold text-neutral-900 text-sm">AI Visibility Grader</span>
          </div>
          <span className="text-xs text-neutral-400">by Pixii</span>
        </div>
      </nav>

      <div className="max-w-content mx-auto px-6 md:px-10">
        {/* Hero */}
        <section className="pt-24 pb-20 max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-6">
            AEO Diagnostic
          </p>
          <h1 className="text-display font-bold text-neutral-950 mb-6 leading-[1.05] tracking-tight">
            Is your product invisible to AI shoppers?
          </h1>
          <p className="text-lg text-neutral-600 mb-10 leading-relaxed max-w-xl">
            25% of buyers ask ChatGPT before Amazon. Find out if you're getting recommended.
          </p>

          <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3 max-w-lg">
            <input
              type="text" value={asin}
              onChange={(e) => setAsin(e.target.value)}
              placeholder="Paste Amazon ASIN or URL"
              className="flex-1 border border-neutral-200 rounded-xl px-4 h-12 text-sm text-neutral-900 placeholder-neutral-400 focus:outline-none focus:border-accent transition-colors"
            />
            <button
              type="submit" disabled={!asin.trim()}
              className="h-12 px-6 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap"
            >
              Run Diagnostic
            </button>
          </form>

          {state.status === "error" && (
            <p className="mt-4 text-sm text-score-low">{state.message}</p>
          )}

          <p className="text-xs text-neutral-400 mt-4">
            Free. No signup. Results in 60 seconds.
          </p>
        </section>

        {/* How it works */}
        <section className="py-20 border-t border-neutral-100">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-10">
            How it works
          </p>
          <div className="grid sm:grid-cols-3 gap-6">
            {[
              { n: "01", title: "Paste your ASIN", body: "We fetch your product title, brand, and key attributes directly from Amazon." },
              { n: "02", title: "3 AI models answer", body: "Llama 3.3, Llama 3.1, and Gemini each answer 10 realistic buyer queries about your category." },
              { n: "03", title: "Score + action plan", body: "Get a 0–100 AI Visibility Score, competitor analysis, and 5 specific fixes." },
            ].map(({ n, title, body }) => (
              <div key={n} className="border border-neutral-200 rounded-xl p-8">
                <p className="text-2xl font-bold text-accent mb-4">{n}</p>
                <p className="font-semibold text-neutral-900 mb-2">{title}</p>
                <p className="text-sm text-neutral-600 leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Footer */}
      <footer className="border-t border-neutral-100 py-8 px-6 md:px-10">
        <div className="max-w-content mx-auto">
          <p className="text-xs text-neutral-400">Built for the Pixii project.</p>
        </div>
      </footer>
    </main>
  );
}

// ── Report view ───────────────────────────────────────────────────────────────
function ReportView({ data, onReset }: { data: DiagnoseResponse; onReset: () => void }) {
  const { product, score, queries, top_competitors, recommendations } = data;
  const totalQueries = queries.length;

  // Per-model mention counts
  const gpt4Hits   = queries.filter((q) => q.mentions.gpt4).length;
  const claudeHits = queries.filter((q) => q.mentions.claude).length;
  const geminiHits = queries.filter((q) => q.mentions.gemini).length;

  // Overall: mentioned in at least one model
  const mentionedIn = queries.filter(
    (q) => q.mentions.gpt4 || q.mentions.claude || q.mentions.gemini
  ).length;

  return (
    <main className="min-h-screen bg-white">
      {/* Nav */}
      <nav className="border-b border-neutral-200 h-16 flex items-center px-6 md:px-10 sticky top-0 bg-white z-10">
        <div className="max-w-content mx-auto w-full flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-5 h-5 rounded-sm bg-accent flex-shrink-0" />
            <span className="font-semibold text-neutral-900 text-sm">AI Visibility Grader</span>
          </div>
          <button
            onClick={onReset}
            className="text-xs font-medium text-neutral-500 hover:text-neutral-900 transition-colors"
          >
            ← New search
          </button>
        </div>
      </nav>

      <div className="max-w-content mx-auto px-6 md:px-10 pb-24">
        {/* Product card */}
        <div className="py-8 border-b border-neutral-200 flex items-start gap-4">
          {product.image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={product.image_url} alt={product.title}
              className="w-16 h-16 object-contain rounded-lg border border-neutral-100 flex-shrink-0" />
          )}
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-1">
              {product.brand} · {product.category}
            </p>
            <p className="text-base font-medium text-neutral-900 leading-snug max-w-2xl">
              {product.title}
            </p>
          </div>
        </div>

        {/* Score hero */}
        <ScoreHero
          score={score.overall}
          brand={product.brand}
          mentionedIn={mentionedIn}
          totalQueries={totalQueries}
        />

        {/* Per-model scores */}
        <section className="py-16 border-b border-neutral-200">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-8">
            Per model
          </p>
          <div className="grid sm:grid-cols-3 gap-4">
            <ModelCard name="Llama 3.3 (70B)" score={score.gpt4}   mentionCount={gpt4Hits}   totalQueries={totalQueries} />
            <ModelCard name="Llama 3.1 (8B)"  score={score.claude} mentionCount={claudeHits} totalQueries={totalQueries} />
            <ModelCard name="Gemini"           score={score.gemini} mentionCount={geminiHits} totalQueries={totalQueries} />
          </div>
        </section>

        {/* Query breakdown */}
        <section className="py-16 border-b border-neutral-200">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-8">
            Query-level breakdown
          </p>
          <QueryTable queries={queries} />
        </section>

        {/* Competitors */}
        {top_competitors.length > 0 && (
          <section className="py-16 border-b border-neutral-200">
            <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3">
              Competitors beating you
            </p>
            <p className="text-sm text-neutral-500 mb-8">
              These brands appeared most in AI recommendations across all {totalQueries} queries.
            </p>
            <CompetitorList competitors={top_competitors} totalQueries={totalQueries} />
          </section>
        )}

        {/* Recommendations */}
        <section className="py-16 border-b border-neutral-200">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-8">
            Recommendations
          </p>
          <div className="flex flex-col gap-4">
            {recommendations.map((rec, i) => (
              <RecommendationCard key={i} recommendation={rec} index={i + 1} />
            ))}
          </div>
        </section>

        {/* CTA */}
        <div className="py-16 text-center">
          <button
            onClick={onReset}
            className="inline-flex items-center gap-2 text-sm font-semibold text-accent hover:text-accent-hover transition-colors"
          >
            Run another diagnostic →
          </button>
        </div>
      </div>
    </main>
  );
}
