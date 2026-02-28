import { useEffect, useState } from "react";
import { fetchDriftInsights } from "../api";
import type { DriftInsight } from "../types";

interface DriftInsightFeedProps {
  refreshCounter: number;
}

function SparkleIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
    </svg>
  );
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-gray-100 bg-white p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-5 w-20 rounded-full bg-gray-200" />
          <div className="h-3.5 w-3.5 rounded bg-gray-100" />
        </div>
      </div>
      <div className="mt-5 h-9 w-20 rounded bg-gray-200" />
      <div className="mt-2 flex gap-3">
        <div className="h-3 w-24 rounded bg-gray-100" />
        <div className="h-3 w-20 rounded bg-gray-100" />
      </div>
      <div className="mt-5 space-y-2">
        <div className="h-3 w-full rounded bg-gray-100" />
        <div className="h-3 w-4/5 rounded bg-gray-100" />
      </div>
      <div className="mt-5 h-10 w-full rounded-lg bg-gray-100" />
    </div>
  );
}

export function DriftInsightFeed({ refreshCounter }: DriftInsightFeedProps) {
  const [insights, setInsights] = useState<DriftInsight[]>([]);
  const [period, setPeriod] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const data = await fetchDriftInsights();
        if (!cancelled) {
          setInsights(data.insights);
          setPeriod(data.period);
        }
      } catch {
        // silently ignore
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [refreshCounter]);

  if (!isLoading && !insights.length) return null;

  return (
    <section className="w-full pb-2">
      {/* Section header */}
      <div className="mb-5 flex items-center gap-2.5">
        <SparkleIcon className="h-5 w-5 text-[#004CFF]" />
        <h2 className="text-base font-semibold tracking-tight text-slate-50">
          AI Financial Insights
        </h2>
        {period && (
          <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-[0.65rem] font-medium text-slate-400">
            {period}
          </span>
        )}
        {isLoading && (
          <span className="ml-auto text-xs text-slate-500">
            Generating insights&hellip;
          </span>
        )}
      </div>

      {/* Cards grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {isLoading
          ? Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)
          : insights.map((d) => {
              const positive = d.drift_pct > 0;
              const negative = d.drift_pct < 0;

              return (
                <div
                  key={d.category}
                  className="group rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition-shadow duration-200 hover:shadow-md"
                >
                  {/* Header: category badge + sparkle */}
                  <div className="flex items-center justify-between">
                    <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[0.65rem] font-medium capitalize text-gray-600">
                      {d.category}
                    </span>
                    <SparkleIcon className="h-3.5 w-3.5 text-[#004CFF]/40 transition-colors group-hover:text-[#004CFF]/70" />
                  </div>

                  {/* Drift stat — prominent */}
                  <div className="mt-5 flex items-baseline gap-1.5">
                    <span
                      className={`text-3xl font-bold tracking-tight ${
                        positive
                          ? "text-red-500"
                          : negative
                          ? "text-emerald-500"
                          : "text-gray-400"
                      }`}
                    >
                      {positive ? "+" : ""}
                      {d.drift_pct.toFixed(0)}%
                    </span>
                    <span
                      className={`text-xl ${
                        positive
                          ? "text-red-400"
                          : negative
                          ? "text-emerald-400"
                          : "text-gray-300"
                      }`}
                    >
                      {positive ? "\u2191" : negative ? "\u2193" : "\u2192"}
                    </span>
                  </div>

                  {/* Amount comparison */}
                  <div className="mt-1.5 flex gap-3 text-[0.7rem] text-gray-400">
                    <span>${d.current_total.toFixed(2)} this month</span>
                    <span className="text-gray-300">/</span>
                    <span>${d.median_total.toFixed(2)} avg</span>
                  </div>

                  {/* Narrative insight */}
                  <p className="mt-4 text-[0.8rem] font-medium leading-relaxed text-[#000000]/70">
                    {d.insight}
                  </p>

                  {/* CTA button */}
                  {d.action && (
                    <button className="mt-5 w-full rounded-lg bg-[#004CFF] px-4 py-2.5 text-[0.75rem] font-semibold text-white transition-colors hover:bg-[#003ACC] active:bg-[#002EA0]">
                      {d.action}
                    </button>
                  )}
                </div>
              );
            })}
      </div>
    </section>
  );
}
