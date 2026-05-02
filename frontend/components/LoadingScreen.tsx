"use client";

import { useState, useEffect } from "react";

interface Step {
  id: string;
  label: string;
  activeAt: number;   // seconds elapsed before this step activates
  doneAt: number;     // seconds elapsed before this step shows ✓ (Infinity = stays active)
}

const STEPS: Step[] = [
  { id: "product",  label: "Fetching product data",               activeAt: 0,  doneAt: 4   },
  { id: "queries",  label: "Generating 10 buyer queries",          activeAt: 4,  doneAt: 14  },
  { id: "llm-a",   label: "Querying Llama 3.3 (70B)",             activeAt: 14, doneAt: 62  },
  { id: "llm-b",   label: "Querying Llama 3.1 (8B)",              activeAt: 14, doneAt: 62  },
  { id: "llm-c",   label: "Querying Gemini",                      activeAt: 14, doneAt: 62  },
  { id: "parse",   label: "Parsing responses with AI",            activeAt: 62, doneAt: 76  },
  { id: "score",   label: "Scoring responses",                    activeAt: 76, doneAt: 80  },
  { id: "recs",    label: "Generating recommendations",           activeAt: 80, doneAt: Infinity },
];

const ESTIMATED_TOTAL = 90; // seconds

type StepStatus = "pending" | "active" | "done";

function getStatus(step: Step, elapsed: number): StepStatus {
  if (elapsed >= step.doneAt)   return "done";
  if (elapsed >= step.activeAt) return "active";
  return "pending";
}

export default function LoadingScreen({ asin }: { asin?: string }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const pct = Math.min(94, Math.round((elapsed / ESTIMATED_TOTAL) * 100));

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-6 bg-white">
      {/* Header */}
      <div className="w-full max-w-md mb-10">
        <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3">
          Running diagnostic
        </p>
        {asin && (
          <p className="text-sm text-neutral-500 font-mono truncate">
            ASIN: {asin}
          </p>
        )}
      </div>

      {/* Step list */}
      <div className="w-full max-w-md flex flex-col gap-3 mb-10">
        {STEPS.map((step) => {
          const status = getStatus(step, elapsed);
          return (
            <div key={step.id} className="flex items-center gap-3">
              {/* Icon */}
              <div className="w-5 flex items-center justify-center flex-shrink-0">
                {status === "done" && (
                  <svg className="w-4 h-4 text-score-high" viewBox="0 0 16 16" fill="none">
                    <path d="M3 8l3.5 3.5L13 5" stroke="currentColor" strokeWidth="1.5"
                      strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
                {status === "active" && <span className="spinner" />}
                {status === "pending" && (
                  <span className="w-3 h-3 rounded-full border border-neutral-300 inline-block" />
                )}
              </div>

              {/* Label */}
              <span className={
                status === "done"    ? "text-sm text-neutral-400 line-through" :
                status === "active"  ? "text-sm text-neutral-900 font-medium" :
                                       "text-sm text-neutral-400"
              }>
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div className="w-full max-w-md">
        <div className="flex justify-between items-center mb-2">
          <span className="text-xs text-neutral-400">{elapsed}s elapsed</span>
          <span className="text-xs font-semibold text-accent">{pct}%</span>
        </div>
        <div className="h-1 w-full bg-neutral-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent rounded-full transition-all duration-1000 ease-linear"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-neutral-400 mt-3 text-center">
          Usually 30–60 seconds depending on AI model load.
        </p>
      </div>
    </main>
  );
}
