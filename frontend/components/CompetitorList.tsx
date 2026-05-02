"use client";

import type { Competitor } from "@/lib/api";

interface CompetitorListProps {
  competitors: Competitor[];
  totalQueries: number;
}

export default function CompetitorList({ competitors, totalQueries }: CompetitorListProps) {
  if (!competitors.length) return null;

  const maxCount = competitors[0]?.mention_count ?? 1;

  return (
    <div className="border border-neutral-200 rounded-xl p-8">
      <div className="flex flex-col gap-5">
        {competitors.map((c, i) => {
          const barPct = Math.round((c.mention_count / maxCount) * 100);
          return (
            <div key={c.brand} className="flex items-center gap-4">
              <span className="text-xs font-mono text-neutral-400 w-4 flex-shrink-0 text-right">
                {i + 1}
              </span>
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm font-medium text-neutral-900">{c.brand}</span>
                  <span className="text-xs text-neutral-400 font-mono">
                    {c.mention_count}/{totalQueries}
                  </span>
                </div>
                <div className="h-1.5 w-full bg-neutral-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent rounded-full"
                    style={{ width: `${barPct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
