"use client";

import type { QuerySummary } from "@/lib/api";

interface QueryTableProps {
  queries: QuerySummary[];
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
          <div className="px-5 py-4 text-sm text-neutral-700 leading-snug">{q.query}</div>
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
