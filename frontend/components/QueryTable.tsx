"use client";

import type { QuerySummary } from "@/lib/api";

interface QueryTableProps {
  queries: QuerySummary[];
}

/**
 * Format a raw LLM query string for human display.
 * Raw queries are lowercase, terse, unit-abbreviated (e.g. "best ultrabook with 16gb ram under 80000").
 * This function applies sentence casing and fixes common tech unit capitalisation.
 */
function formatQuery(q: string): string {
  if (!q) return q;

  // Fix unit capitalisation before sentence-casing (order matters)
  const unitFixes: [RegExp, string][] = [
    [/\b(\d+)\s*gb\b/gi,   "$1GB"],
    [/\b(\d+)\s*tb\b/gi,   "$1TB"],
    [/\b(\d+)\s*mb\b/gi,   "$1MB"],
    [/\b(\d+)\s*ghz\b/gi,  "$1GHz"],
    [/\b(\d+)\s*mhz\b/gi,  "$1MHz"],
    [/\b(\d+)\s*hz\b/gi,   "$1Hz"],
    [/\b(\d+)\s*mah\b/gi,  "$1mAh"],
    [/\b(\d+)\s*mp\b/gi,   "$1MP"],
    [/\b(\d+)\s*w\b/gi,    "$1W"],
    [/\b(\d+)\s*fps\b/gi,  "$1fps"],
    [/\b(\d+)\s*ms\b/gi,   "$1ms"],
    [/\b(\d+)\s*-?\s*inch(?:es)?\b/gi, "$1-inch"],
    [/\b(\d+)\s*k\b/g,     "$1K"],   // e.g. "80000" stays, "4K" fixes "4k"
  ];

  let out = q.trim();
  for (const [pattern, replacement] of unitFixes) {
    out = out.replace(pattern, replacement);
  }

  // Sentence case: capitalise first letter only
  out = out.charAt(0).toUpperCase() + out.slice(1);

  return out;
}

function Hit({ v }: { v: boolean }) {
  return v ? (
    <svg className="w-4 h-4 text-score-high mx-auto" viewBox="0 0 16 16" fill="none">
      <path d="M3 8l3.5 3.5L13 5" stroke="currentColor" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : (
    <svg className="w-4 h-4 text-neutral-300 mx-auto" viewBox="0 0 16 16" fill="none">
      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5"
        strokeLinecap="round" />
    </svg>
  );
}

export default function QueryTable({ queries }: QueryTableProps) {
  return (
    <div className="border border-neutral-200 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="grid grid-cols-[1fr_80px_80px_80px] border-b border-neutral-200 bg-neutral-50">
        <div className="px-5 py-3 text-xs font-semibold uppercase tracking-widest text-neutral-400">
          Query
        </div>
        {["Llama 3.3", "Llama 3.1", "Gemini"].map((m) => (
          <div key={m} className="py-3 text-xs font-semibold uppercase tracking-widest text-neutral-400 text-center">
            {m}
          </div>
        ))}
      </div>

      {/* Rows */}
      {queries.map((q, i) => (
        <div
          key={i}
          className="grid grid-cols-[1fr_80px_80px_80px] border-b border-neutral-100 last:border-0"
        >
          <div className="px-5 py-4 text-sm text-neutral-700 leading-snug">
            {formatQuery(q.query)}
          </div>
          <div className="py-4 flex items-center justify-center">
            <Hit v={q.mentions.gpt4} />
          </div>
          <div className="py-4 flex items-center justify-center">
            <Hit v={q.mentions.claude} />
          </div>
          <div className="py-4 flex items-center justify-center">
            <Hit v={q.mentions.gemini} />
          </div>
        </div>
      ))}
    </div>
  );
}
