"use client";

import type { Recommendation } from "@/lib/api";

interface RecommendationCardProps {
  recommendation: Recommendation;
  index: number;
}

const PRIORITY: Record<string, { label: string; color: string }> = {
  high:   { label: "High priority",   color: "text-score-low bg-red-50" },
  medium: { label: "Medium priority", color: "text-score-mid bg-amber-50" },
  low:    { label: "Low priority",    color: "text-neutral-500 bg-neutral-100" },
};

export default function RecommendationCard({ recommendation, index }: RecommendationCardProps) {
  const p = PRIORITY[recommendation.priority] ?? PRIORITY.medium;
  return (
    <div className="border border-neutral-200 rounded-xl p-8">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex items-center gap-4">
          <span className="text-2xl font-bold text-neutral-200 leading-none tabular-nums">
            {String(index).padStart(2, "0")}
          </span>
          <h3 className="text-lg font-semibold text-neutral-900">{recommendation.title}</h3>
        </div>
        <span className={`text-xs font-semibold uppercase tracking-widest px-2.5 py-1 rounded-full flex-shrink-0 ${p.color}`}>
          {p.label}
        </span>
      </div>
      <p className="text-base text-neutral-600 leading-relaxed ml-14">
        {recommendation.description}
      </p>
    </div>
  );
}
