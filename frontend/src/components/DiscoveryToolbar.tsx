"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CornerDownLeft,
  FlaskConical,
  HelpCircle,
  Link2,
  Loader2,
  Play,
  RotateCcw,
  Search,
} from "lucide-react";
import type { PipelineRunResult, ProgressEvent } from "@/types/discovery";

export type WizardStep = 1 | 2 | 3;

interface DiscoveryToolbarProps {
  step: WizardStep;
  onStepChange: (step: WizardStep) => void;
  phrase: string;
  onPhraseChange: (val: string) => void;
  suppliedUrlsText: string;
  onSuppliedUrlsChange: (val: string) => void;
  useCache: boolean;
  onUseCacheChange: (val: boolean) => void;
  isRunning: boolean;
  progress: ProgressEvent | null;
  result: PipelineRunResult | null;
  onRun: () => void;
  onRunDemo: () => void;
}

function isValidLinkedInPostUrl(url: string): boolean {
  const raw = url.trim();
  if (!raw) return false;
  const normalized = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.toLowerCase();
    if (host === "lnkd.in" || host === "www.lnkd.in") {
      return path.length > 1;
    }
    if (host === "linkedin.com" || host.endsWith(".linkedin.com")) {
      return (
        path.includes("/posts/") ||
        path.includes("/feed/update/") ||
        path.includes("/pulse/")
      );
    }
    return false;
  } catch {
    return false;
  }
}

export function DiscoveryToolbar({
  step,
  onStepChange,
  phrase,
  onPhraseChange,
  suppliedUrlsText,
  onSuppliedUrlsChange,
  useCache,
  onUseCacheChange,
  isRunning,
  progress,
  result,
  onRun,
  onRunDemo,
}: DiscoveryToolbarProps) {
  const phraseInputRef = useRef<HTMLInputElement>(null);
  const urlsTextareaRef = useRef<HTMLTextAreaElement>(null);
  const [showDemoInfo, setShowDemoInfo] = useState(false);

  useEffect(() => {
    if (step === 1) {
      phraseInputRef.current?.focus();
    } else if (step === 2) {
      urlsTextareaRef.current?.focus();
    }
  }, [step]);

  const rawLines = suppliedUrlsText
    .split(/\r?\n/)
    .map((u) => u.trim())
    .filter(Boolean);
  const validUrls = rawLines.filter(isValidLinkedInPostUrl);
  const hasInvalidUrlLines = rawLines.length > 0 && validUrls.length < rawLines.length;

  const strongMatches = result
    ? result.ranked_influencers.filter((i) => i.final_relevance_score >= 75).length
    : 0;
  const hasSuppliedUrlResults = result?.source_mode === "supplied_urls";

  const advanceToStep2 = () => {
    if (!phrase.trim() || isRunning) return;
    onStepChange(2);
  };

  return (
    <section className="bg-surface rounded-lg border border-outline-border p-3.5 space-y-3">
      {/* Top 3-Step Indicator Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-outline-border">
        <nav aria-label="Search workflow steps" className="flex flex-wrap items-center gap-1.5 text-xs">
          <button
            type="button"
            disabled={isRunning}
            onClick={() => onStepChange(1)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer ${
              step === 1
                ? "bg-primary text-white"
                : step > 1
                ? "bg-primary-container/60 text-on-primary-container hover:bg-primary-container"
                : "text-on-surface-variant hover:bg-surface-ground"
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full text-[10px] font-mono font-bold inline-flex items-center justify-center ${
                step === 1
                  ? "bg-white/20 text-white"
                  : "bg-primary/15 text-primary"
              }`}
            >
              {step > 1 ? <Check className="w-2.5 h-2.5" /> : "1"}
            </span>
            <span>Enter Name / Topic</span>
          </button>

          <span className="text-outline-border text-xs">→</span>

          <button
            type="button"
            disabled={isRunning || !phrase.trim()}
            onClick={() => onStepChange(2)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
              step === 2
                ? "bg-primary text-white"
                : step === 3
                ? "bg-primary-container/60 text-on-primary-container hover:bg-primary-container"
                : "bg-surface-ground text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full text-[10px] font-mono font-bold inline-flex items-center justify-center ${
                step === 2
                  ? "bg-white/20 text-white"
                  : step === 3
                  ? "bg-primary/15 text-primary"
                  : "bg-outline-border/60 text-on-surface-variant"
              }`}
            >
              {step === 3 ? <Check className="w-2.5 h-2.5" /> : "2"}
            </span>
            <span>Paste URLs</span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                step === 2
                  ? "bg-white/20 text-white"
                  : "bg-surface text-on-surface-variant border border-outline-border"
              }`}
            >
              Optional
            </span>
          </button>

          <span className="text-outline-border text-xs">→</span>

          <button
            type="button"
            disabled={isRunning || !result}
            onClick={() => result && onStepChange(3)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
              step === 3
                ? "bg-primary text-white"
                : "bg-surface-ground text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <span
              className={`w-4 h-4 rounded-full text-[10px] font-mono font-bold inline-flex items-center justify-center ${
                step === 3
                  ? "bg-white/20 text-white"
                  : "bg-outline-border/60 text-on-surface-variant"
              }`}
            >
              3
            </span>
            <span>Results</span>
          </button>
        </nav>

        <div className="flex items-center gap-2.5">
          <label className="inline-flex items-center gap-1.5 cursor-pointer select-none text-xs text-on-surface-variant">
            <input
              type="checkbox"
              checked={useCache}
              onChange={(e) => onUseCacheChange(e.target.checked)}
              className="rounded border-outline-border accent-[#0F4C81] cursor-pointer"
            />
            <span>Fast cache</span>
          </label>

          <div className="h-3.5 w-px bg-outline-border" />

          <div className="inline-flex items-center gap-1">
            <button
              type="button"
              disabled={isRunning}
              onClick={onRunDemo}
              title="Run on 5 built-in sample posts (offline fixture) to test AI scoring without scraping LinkedIn"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-outline-border bg-surface-ground hover:bg-surface text-xs font-medium text-on-surface-variant hover:text-on-surface disabled:opacity-50 transition-colors cursor-pointer"
            >
              <FlaskConical className="w-3.5 h-3.5 text-primary" />
              <span>Demo Data</span>
            </button>
            <button
              type="button"
              onClick={() => setShowDemoInfo((v) => !v)}
              title="What is Demo Data?"
              aria-label="What is Demo Data?"
              className="p-1 rounded text-on-surface-variant hover:text-primary hover:bg-surface-ground cursor-pointer"
            >
              <HelpCircle className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {showDemoInfo && (
        <div className="rounded-md border border-primary/20 bg-primary-container/25 px-3 py-2 text-xs text-on-surface-variant leading-relaxed">
          <strong className="text-on-surface">What Demo Data does:</strong> Loads 5 pre-saved
          sample K12 LinkedIn posts &amp; commenters from <code>data/sample_dataset.json</code>{" "}
          (no live LinkedIn search or Apify scraping), then runs live AI scoring and ranking on them
          so you can preview the tool quickly without using scraping credits.
        </div>
      )}

      {/* Step 1: Type Name / Topic */}
      {step === 1 && (
        <div className="space-y-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
            <label htmlFor="step1-phrase" className="text-xs font-semibold text-on-surface">
              Step 1: Type a topic, keyword, or company name
            </label>
            <span className="text-[11px] text-on-surface-variant">
              Example: <strong>K12 B2B Sales</strong>, <strong>EDXSO</strong>, or{" "}
              <strong>School Principals</strong>
            </span>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-on-surface-variant absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                id="step1-phrase"
                ref={phraseInputRef}
                type="text"
                value={phrase}
                onChange={(e) => onPhraseChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    e.stopPropagation();
                    advanceToStep2();
                  }
                }}
                placeholder="Type topic or brand name and press Enter..."
                className="w-full pl-9 pr-3 py-2 text-sm bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface transition-colors font-medium"
              />
            </div>

            <button
              type="button"
              disabled={isRunning || !phrase.trim()}
              onClick={advanceToStep2}
              className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] disabled:opacity-55 disabled:cursor-not-allowed transition-colors cursor-pointer shrink-0"
            >
              <span>Next: Paste URL (Optional)</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <p className="text-[11px] text-on-surface-variant flex items-center gap-1.5">
            <CornerDownLeft className="w-3 h-3 text-primary" />
            <span>
              Press <strong>Enter</strong> to go to Step 2 (optional LinkedIn post URLs).
            </span>
          </p>
        </div>
      )}

      {/* Step 2: Optional Paste URLs */}
      {step === 2 && (
        <div className="space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Link2 className="w-4 h-4 text-primary" />
              <span className="text-xs font-semibold text-on-surface">
                Step 2: Paste LinkedIn post URL(s)
              </span>
              <span className="px-1.5 py-0.5 rounded bg-surface-ground border border-outline-border text-[10px] font-medium text-on-surface-variant">
                Optional
              </span>
            </div>

            <div className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant bg-surface-ground px-2.5 py-1 rounded border border-outline-border">
              <span>Name:</span>
              <strong className="text-on-surface">{phrase.trim()}</strong>
              <button
                type="button"
                onClick={() => onStepChange(1)}
                className="text-primary hover:underline font-medium ml-1 cursor-pointer"
              >
                Edit
              </button>
              {suppliedUrlsText.trim() && (
                <>
                  <span className="text-outline-border">|</span>
                  <button
                    type="button"
                    onClick={() => onSuppliedUrlsChange("")}
                    className="text-on-surface-variant hover:text-on-surface font-medium cursor-pointer"
                  >
                    Clear URLs
                  </button>
                </>
              )}
            </div>
          </div>

          <p className="text-xs text-on-surface-variant">
            Paste one or more LinkedIn post URLs below to get{" "}
            <strong>Commenter People + Similar Profiles</strong> side by side — or leave this blank
            and press <strong>Enter</strong> to search LinkedIn automatically for{" "}
            <strong>Matching Contacts &amp; Source Posts</strong>.
          </p>

          <textarea
            ref={urlsTextareaRef}
            rows={3}
            value={suppliedUrlsText}
            onChange={(e) => onSuppliedUrlsChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (!isRunning && phrase.trim() && !hasInvalidUrlLines) {
                  onRun();
                }
              }
            }}
            placeholder="Optional: paste LinkedIn post URLs here (one per line), or leave empty and press Enter..."
            className="w-full px-3 py-2 text-xs font-mono bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
          />

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="text-[11px]">
              {hasInvalidUrlLines ? (
                <span className="text-amber-accent font-medium">
                  Enter valid LinkedIn post URLs (linkedin.com/posts/..., linkedin.com/feed/update/...,
                  linkedin.com/pulse/..., or lnkd.in/...), or clear the box to auto-search.
                </span>
              ) : validUrls.length > 0 ? (
                <span className="text-forest font-medium">
                  ✓ {validUrls.length} post URL(s) pasted — will show Commenter People &amp; Similar
                  Profiles (press Enter to get results).
                </span>
              ) : (
                <span className="text-on-surface-variant">
                  Press <strong>Enter</strong> to get results (Shift+Enter for new line).
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                disabled={isRunning}
                onClick={() => onStepChange(1)}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-outline-border bg-surface hover:bg-surface-ground text-xs font-medium text-on-surface cursor-pointer"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Back</span>
              </button>

              <button
                type="button"
                disabled={isRunning || !phrase.trim() || hasInvalidUrlLines}
                onClick={onRun}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] disabled:opacity-55 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                {isRunning ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5 fill-current" />
                )}
                <span>
                  {isRunning
                    ? "Searching..."
                    : validUrls.length > 0
                    ? "Get Commenters & Similar"
                    : "Get Results"}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Active Search Summary + Live Progress / Result Stats */}
      {step === 3 && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="px-2.5 py-1 rounded bg-surface-ground border border-outline-border text-on-surface">
                <span className="text-on-surface-variant">Topic: </span>
                <strong>{isRunning ? phrase : result?.search_phrase || phrase}</strong>
              </span>

              <span className="px-2.5 py-1 rounded bg-surface-ground border border-outline-border text-on-surface-variant">
                {isRunning
                  ? validUrls.length > 0
                    ? `${validUrls.length} Pasted URL(s)`
                    : "Auto LinkedIn Search"
                  : result?.source_mode === "supplied_urls"
                  ? `${result.total_posts} Pasted URL(s)`
                  : result?.source_mode === "test_dataset"
                  ? "Demo Data (sample fixture)"
                  : "Auto LinkedIn Search"}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={isRunning}
                onClick={() => onStepChange(1)}
                className="px-2.5 py-1.5 rounded border border-outline-border bg-surface hover:bg-surface-ground text-xs font-medium text-on-surface cursor-pointer disabled:opacity-50"
              >
                New Search
              </button>

              <button
                type="button"
                disabled={isRunning}
                onClick={() => onStepChange(2)}
                className="px-2.5 py-1.5 rounded border border-outline-border bg-surface hover:bg-surface-ground text-xs font-medium text-on-surface cursor-pointer disabled:opacity-50"
              >
                {validUrls.length > 0 ? "Edit URLs" : "Paste URL"}
              </button>

              <button
                type="button"
                disabled={isRunning || !phrase.trim()}
                onClick={onRun}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] disabled:opacity-55 transition-colors cursor-pointer"
              >
                {isRunning ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="w-3.5 h-3.5" />
                )}
                <span>{isRunning ? "Searching..." : "Run Again"}</span>
              </button>
            </div>
          </div>

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
                  {hasSuppliedUrlResults ? "commenter people" : "contacts found"}
                </span>
                {hasSuppliedUrlResults && (
                  <>
                    <span className="text-outline-border">·</span>
                    <span>
                      <strong className="text-on-surface font-semibold">
                        {result.similar_profiles?.length ?? 0}
                      </strong>{" "}
                      similar profiles
                    </span>
                  </>
                )}
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
        </div>
      )}
    </section>
  );
}
