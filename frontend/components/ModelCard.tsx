"use client";

interface ModelCardProps {
  name: string;
  score: number;
  mentionCount: number;
  totalQueries: number;
}

function scoreColor(s: number) {
  if (s >= 70) return "text-score-high";
  if (s >= 40) return "text-score-mid";
  return "text-score-low";
}

export default function ModelCard({ name, score, mentionCount, totalQueries }: ModelCardProps) {
  return (
    <div className="border border-neutral-200 rounded-xl p-8">
      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-6">
        {name}
      </p>
      <p className={`text-5xl font-bold mb-1 ${scoreColor(score)}`}>{score}</p>
      <p className="text-sm text-neutral-400">
        {mentionCount}/{totalQueries} queries
      </p>
    </div>
  );
}
