"use client";

import { Loader2, Play, Search } from "lucide-react";
import type { DataSourceMode, PipelineRunResult, ProgressEvent } from "@/types/discovery";

interface DiscoveryToolbarProps {
  phrase: string;
  onPhraseChange: (val: string) => void;
  mode: DataSourceMode;
  onModeChange: (val: DataSourceMode) => void;
  suppliedUrlsText: string;
  onSuppliedUrlsChange: (val: string) => void;
  useCache: boolean;
  onUseCacheChange: (val: boolean) => void;
  isRunning: boolean;
  progress: ProgressEvent | null;
  result: PipelineRunResult | null;
  onRun: () => void;
}

const MODE_OPTIONS: { value: DataSourceMode; label: string }[] = [
  { value: "live_api", label: "Live Search" },
  { value: "supplied_urls", label: "Paste URLs" },
  { value: "test_dataset", label: "Demo Data" },
];

export function DiscoveryToolbar({
  phrase,
  onPhraseChange,
  mode,
  onModeChange,
  suppliedUrlsText,
  onSuppliedUrlsChange,
  useCache,
  onUseCacheChange,
  isRunning,
  progress,
  result,
  onRun,
}: DiscoveryToolbarProps) {
  const strongMatches = result
    ? result.ranked_influencers.filter((i) => i.final_relevance_score >= 75).length
    : 0;

  return (
    <section className="bg-surface rounded-lg border border-outline-border p-3.5 space-y-2.5">
      <div className="flex flex-col md:flex-row md:items-center gap-2.5">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-on-surface-variant absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            value={phrase}
            onChange={(e) => onPhraseChange(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && !isRunning) {
                e.preventDefault();
                onRun();
              }
            }}
            placeholder="Enter a topic phrase (e.g., K12 B2B Sales)..."
            className="w-full pl-9 pr-3 py-2 text-sm bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface transition-colors font-medium"
          />
        </div>

        <div className="flex items-center justify-between md:justify-end gap-2.5 flex-wrap">
          <div
            role="radiogroup"
            aria-label="Data source mode"
            className="inline-flex items-center p-0.5 rounded bg-surface-ground border border-outline-border text-xs font-medium text-on-surface-variant"
          >
            {MODE_OPTIONS.map((opt) => {
              const selected = mode === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onModeChange(opt.value)}
                  className={`px-2.5 py-1.5 rounded transition-colors cursor-pointer ${
                    selected
                      ? "bg-surface text-primary font-semibold border border-outline-border/60"
                      : "hover:text-on-surface"
                  }`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>

          <label className="inline-flex items-center gap-1.5 cursor-pointer select-none px-1 text-xs text-on-surface-variant">
            <input
              type="checkbox"
              checked={useCache}
              onChange={(e) => onUseCacheChange(e.target.checked)}
              className="rounded border-outline-border accent-[#0F4C81] cursor-pointer"
            />
            <span>Fast cache</span>
          </label>

          <button
            type="button"
            disabled={isRunning || !phrase.trim()}
            onClick={onRun}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] disabled:opacity-55 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            {isRunning ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{isRunning ? "Searching..." : "Find Contacts"}</span>
          </button>
        </div>
      </div>

      {mode === "supplied_urls" && (
        <div className="pt-2 border-t border-outline-border">
          <textarea
            rows={2}
            value={suppliedUrlsText}
            onChange={(e) => onSuppliedUrlsChange(e.target.value)}
            placeholder="Paste up to 5 LinkedIn post URLs (one per line)..."
            className="w-full px-3 py-2 text-xs font-mono bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
          />
        </div>
      )}

      {isRunning && progress ? (
        <div className="pt-1 flex items-center gap-3">
          <div className="flex-1 h-1.5 bg-surface-ground rounded-full overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-300"
              style={{ width: `${Math.round((progress.step / progress.total_steps) * 100)}%` }}
            />
          </div>
          <span className="text-xs font-mono text-primary shrink-0">
            Step {progress.step}/{progress.total_steps}: {progress.message}
          </span>
        </div>
      ) : result ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-on-surface-variant pt-0.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              <strong className="text-on-surface font-semibold">{result.total_posts}</strong>{" "}
              LinkedIn posts
            </span>
            <span className="text-outline-border">·</span>
            <span>
              <strong className="text-on-surface font-semibold">
                {result.total_unique_commenters}
              </strong>{" "}
              contacts found
            </span>
            <span className="text-outline-border">·</span>
            <span>
              <strong className="text-forest font-semibold">{strongMatches}</strong> strong fits
              (≥75)
            </span>
          </div>

          <span className="font-mono text-[11px]">
            Completed in {result.total_duration_secs.toFixed(2)}s
          </span>
        </div>
      ) : null}
    </section>
  );
}
