"use client";

interface ScoreHeroProps {
  score: number;
  productTitle: string;
  mentionedIn: number;   // how many queries the product was mentioned in
  totalQueries: number;
  queriesUsed?: number;  // actual queries scored (may be < totalQueries if timeout hit)
}

function scoreColor(s: number) {
  if (s >= 70) return "text-score-high";
  if (s >= 40) return "text-score-mid";
  return "text-score-low";
}

function scoreLabel(s: number) {
  if (s >= 70) return "Strong visibility";
  if (s >= 40) return "Moderate visibility";
  return "Low visibility";
}

export default function ScoreHero({ score, productTitle, mentionedIn, totalQueries, queriesUsed }: ScoreHeroProps) {
  const partial = queriesUsed !== undefined && queriesUsed < totalQueries;

  return (
    <div className="py-16 border-b border-neutral-200 text-center">
      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-8">
        AI Visibility Score
      </p>

      {/* Giant number */}
      <div className="flex items-baseline justify-center gap-1 mb-4">
        <span className={`text-[9rem] font-bold leading-none ${scoreColor(score)}`}>
          {score}
        </span>
        <span className="text-2xl text-neutral-400 font-normal mb-2">/100</span>
      </div>

      <p className={`text-lg font-semibold mb-2 ${scoreColor(score)}`}>
        {scoreLabel(score)}
      </p>

      <p className="text-lg text-neutral-600 max-w-sm mx-auto leading-relaxed">
        {productTitle} is recommended in{" "}
        <strong className="text-neutral-900">{mentionedIn} of {totalQueries}</strong>{" "}
        buyer searches across all AI models.
      </p>

      {partial && (
        <p className="text-xs text-neutral-400 mt-3">
          Scored on {queriesUsed} of {totalQueries} queries (high demand — run again for full results)
        </p>
      )}
    </div>
  );
}
