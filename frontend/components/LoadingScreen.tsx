"use client";

import { useState, useEffect } from "react";
import type { Product } from "@/lib/api";

interface Step {
  id: string;
  label: string;
  activeAt: number;
  doneAt: number;
}

const STEPS: Step[] = [
  { id: "setup",   label: "Setting up product profile",    activeAt: 0,  doneAt: 4   },
  { id: "queries", label: "Generating 6 buyer queries",    activeAt: 4,  doneAt: 14  },
  { id: "llm-a",  label: "Querying Llama 3.3 (70B)",      activeAt: 14, doneAt: 62  },
  { id: "llm-b",  label: "Querying Llama 3.1 (8B)",       activeAt: 14, doneAt: 62  },
  { id: "llm-c",  label: "Querying Gemini",                activeAt: 14, doneAt: 62  },
  { id: "parse",  label: "Parsing responses with AI",      activeAt: 62, doneAt: 76  },
  { id: "score",  label: "Scoring responses",              activeAt: 76, doneAt: 80  },
  { id: "recs",   label: "Generating recommendations",     activeAt: 80, doneAt: Infinity },
];

const ESTIMATED_TOTAL = 110;

type StepStatus = "pending" | "active" | "done";

function getStatus(step: Step, elapsed: number): StepStatus {
  if (elapsed >= step.doneAt)   return "done";
  if (elapsed >= step.activeAt) return "active";
  return "pending";
}

type ProductPreview = Pick<Product, "title" | "brand" | "image_url">;

export default function LoadingScreen({ product }: { product?: ProductPreview | null }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const pct = Math.min(94, Math.round((elapsed / ESTIMATED_TOTAL) * 100));

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-6 bg-white">
      {/* Product card — appears once /product resolves (~3s) */}
      <div className="w-full max-w-md mb-10 min-h-[56px]">
        {product ? (
          <div className="flex items-center gap-3">
            {product.image_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={product.image_url}
                alt={product.title}
                className="w-12 h-12 object-contain rounded-lg border border-neutral-100 flex-shrink-0"
              />
            )}
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-0.5">
                {product.brand}
              </p>
              <p className="text-sm text-neutral-700 font-medium leading-snug line-clamp-2">
                {product.title}
              </p>
            </div>
          </div>
        ) : (
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-1">
              Running diagnostic
            </p>
            <p className="text-sm text-neutral-400">Looking up product&hellip;</p>
          </div>
        )}
      </div>

      {/* Step list */}
      <div className="w-full max-w-md flex flex-col gap-3 mb-10">
        {STEPS.map((step) => {
          const status = getStatus(step, elapsed);
          return (
            <div key={step.id} className="flex items-center gap-3">
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
              <span className={
                status === "done"   ? "text-sm text-neutral-400 line-through" :
                status === "active" ? "text-sm text-neutral-900 font-medium"  :
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
          Usually 90&ndash;120 seconds depending on AI model load.
        </p>
      </div>
    </main>
  );
}
