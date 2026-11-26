"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Info } from "lucide-react";
import {
  CredentialsModal,
  type RuntimeCredentialOverrides,
} from "@/components/CredentialsModal";
import { DiscoveredPostsGrid } from "@/components/DiscoveredPostsGrid";
import { DiscoveryToolbar, type WizardStep } from "@/components/DiscoveryToolbar";
import { HeaderBar } from "@/components/HeaderBar";
import { InfluencersWorkbench } from "@/components/InfluencersWorkbench";
import { UrlComparisonWorkbench } from "@/components/UrlComparisonWorkbench";
import {
  API_BASE_URL,
  downloadExport,
  fetchConfig,
  fetchLatestResult,
  runDiscoveryStream,
} from "@/lib/api";
import type {
  ApiConfigResponse,
  DataSourceMode,
  PipelineRunResult,
  ProgressEvent,
} from "@/types/discovery";

type ActiveTab = "contacts" | "posts" | "url_comparison";

export default function HomePage() {
  const [config, setConfig] = useState<ApiConfigResponse | null>(null);
  const [result, setResult] = useState<PipelineRunResult | null>(null);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [wizardStep, setWizardStep] = useState<WizardStep>(1);
  const [phrase, setPhrase] = useState("K12 B2B Sales");
  const [suppliedUrlsText, setSuppliedUrlsText] = useState("");
  const [useCache, setUseCache] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("contacts");
  const [focusedPostUrl, setFocusedPostUrl] = useState<string | null>(null);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [exporting, setExporting] = useState<"csv" | "json" | null>(null);
  const [overrides, setOverrides] = useState<RuntimeCredentialOverrides>({
    serper_api_key: "",
    groq_api_key: "",
    gemini_api_key: "",
    apify_token: "",
    max_comments_per_post: "",
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [cfg, latest] = await Promise.all([fetchConfig(), fetchLatestResult()]);
        if (!active) return;
        setConfig(cfg);
        setPhrase(cfg.default_phrase || "K12 B2B Sales");
        setUseCache(cfg.defaults.use_cache);
        if (latest) {
          setResult(latest);
          setActiveTab(latest.source_mode === "supplied_urls" ? "url_comparison" : "contacts");
        }
      } catch (err) {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? `Backend API unreachable (${err.message}). Start 'python api.py' on port 8000.`
            : "Backend API unreachable. Start 'python api.py' on port 8000."
        );
      } finally {
        if (active) setIsInitialLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const executeDiscovery = async (requestedMode?: DataSourceMode) => {
    setErrorMsg(null);
    setFocusedPostUrl(null);
    setWizardStep(3);
    setIsRunning(true);
    setProgress({ step: 1, total_steps: 6, message: "Starting search..." });

    try {
      const suppliedUrls =
        requestedMode === "test_dataset"
          ? []
          : suppliedUrlsText
              .split(/\r?\n/)
              .map((u) => u.trim())
              .filter(Boolean);

      const effectiveMode: DataSourceMode =
        requestedMode ?? (suppliedUrls.length > 0 ? "supplied_urls" : "live_api");

      const parsedMaxComments = overrides.max_comments_per_post.trim()
        ? Number.parseInt(overrides.max_comments_per_post.trim(), 10)
        : undefined;

      const nextResult = await runDiscoveryStream(
        {
          phrase,
          mode: effectiveMode,
          supplied_urls: suppliedUrls,
          use_cache: useCache,
          max_comments_per_post: Number.isFinite(parsedMaxComments)
            ? parsedMaxComments
            : undefined,
          serper_api_key: overrides.serper_api_key.trim() || undefined,
          groq_api_key: overrides.groq_api_key.trim() || undefined,
          gemini_api_key: overrides.gemini_api_key.trim() || undefined,
          apify_token: overrides.apify_token.trim() || undefined,
        },
        (ev) => setProgress(ev)
      );
      setResult(nextResult);
      setActiveTab(nextResult.source_mode === "supplied_urls" ? "url_comparison" : "contacts");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Pipeline run failed.");
    } finally {
      setIsRunning(false);
    }
  };

  const handleExport = async (format: "csv" | "json") => {
    if (!result) return;
    setExporting(format);
    try {
      await downloadExport(format, result);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setExporting(null);
    }
  };

  const isUrlModeResult = result?.source_mode === "supplied_urls";

  return (
    <div className="min-h-screen flex flex-col bg-surface-ground">
      <HeaderBar
        config={config}
        result={result}
        onOpenCredentials={() => setCredentialsOpen(true)}
        onExportCsv={() => handleExport("csv")}
        onExportJson={() => handleExport("json")}
        exporting={exporting}
      />

      <main className="flex-1 max-w-[1440px] w-full mx-auto px-4 sm:px-6 py-4 space-y-4">
        <DiscoveryToolbar
          step={wizardStep}
          onStepChange={setWizardStep}
          phrase={phrase}
          onPhraseChange={setPhrase}
          suppliedUrlsText={suppliedUrlsText}
          onSuppliedUrlsChange={setSuppliedUrlsText}
          useCache={useCache}
          onUseCacheChange={setUseCache}
          isRunning={isRunning}
          progress={progress}
          result={result}
          onRun={() => executeDiscovery()}
          onRunDemo={() => executeDiscovery("test_dataset")}
        />

        {errorMsg && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 flex items-start gap-2 text-xs text-red-900">
            <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
            <span>{errorMsg}</span>
          </div>
        )}

        {result?.source_mode === "test_dataset" && (
          <div className="rounded-lg border border-primary/25 bg-primary-container/30 px-3.5 py-2 flex items-center gap-2 text-xs text-on-primary-container">
            <Info className="w-4 h-4 text-primary shrink-0" />
            <span>
              <strong>Demo Data Mode:</strong> Showing 5 pre-saved sample LinkedIn posts &amp;
              commenters from <code>data/sample_dataset.json</code> (no live LinkedIn scraping),
              scored live by AI ranking.
            </span>
          </div>
        )}

        {result?.warnings.map((w, idx) => (
          <div
            key={`${w}-${idx}`}
            className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2 flex items-center gap-2 text-xs text-amber-950"
          >
            <AlertCircle className="w-4 h-4 text-amber-accent shrink-0" />
            <span>{w}</span>
          </div>
        ))}

        {result ? (
          isUrlModeResult ? (
            <>
              <div className="border-b border-outline-border flex items-center gap-6">
                <button
                  type="button"
                  onClick={() => setActiveTab("url_comparison")}
                  className={`pb-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    activeTab !== "posts"
                      ? "border-primary text-primary"
                      : "border-transparent text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  Commenter People ({result.total_unique_commenters}) &amp; Similar Profiles (
                  {result.similar_profiles?.length ?? 0})
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("posts")}
                  className={`pb-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    activeTab === "posts"
                      ? "border-primary text-primary"
                      : "border-transparent text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  Source Posts ({result.total_posts})
                </button>
              </div>

              {activeTab === "posts" ? (
                <DiscoveredPostsGrid
                  posts={result.posts}
                  influencers={result.ranked_influencers}
                  focusedPostUrl={focusedPostUrl}
                  onSelectPostForFilter={(url) => {
                    setFocusedPostUrl((prev) => (prev === url ? null : url));
                    setActiveTab("url_comparison");
                  }}
                />
              ) : (
                <UrlComparisonWorkbench
                  key={result.generated_at_utc}
                  influencers={result.ranked_influencers}
                  similarProfiles={result.similar_profiles ?? []}
                  focusedPostUrl={focusedPostUrl}
                  onClearPostFocus={() => setFocusedPostUrl(null)}
                />
              )}
            </>
          ) : (
            <>
              <div className="border-b border-outline-border flex items-center gap-6">
                <button
                  type="button"
                  onClick={() => setActiveTab("contacts")}
                  className={`pb-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    activeTab !== "posts"
                      ? "border-primary text-primary"
                      : "border-transparent text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  Matching Contacts ({result.total_unique_commenters})
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("posts")}
                  className={`pb-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                    activeTab === "posts"
                      ? "border-primary text-primary"
                      : "border-transparent text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  Source Posts ({result.total_posts})
                </button>
              </div>

              {activeTab === "posts" ? (
                <DiscoveredPostsGrid
                  posts={result.posts}
                  influencers={result.ranked_influencers}
                  focusedPostUrl={focusedPostUrl}
                  onSelectPostForFilter={(url) => {
                    setFocusedPostUrl((prev) => (prev === url ? null : url));
                    setActiveTab("contacts");
                  }}
                />
              ) : (
                <InfluencersWorkbench
                  key={result.generated_at_utc}
                  influencers={result.ranked_influencers}
                  focusedPostUrl={focusedPostUrl}
                  onClearPostFocus={() => setFocusedPostUrl(null)}
                />
              )}
            </>
          )
        ) : isInitialLoading ? (
          <div className="bg-surface rounded-lg border border-outline-border p-10 text-center text-xs text-on-surface-variant">
            Loading workspace...
          </div>
        ) : (
          <div className="bg-surface rounded-lg border border-outline-border p-10 text-center space-y-2.5">
            <h2 className="font-display font-semibold text-sm text-on-surface">
              Find school decision-makers and education contacts in 3 steps
            </h2>
            <p className="text-xs text-on-surface-variant max-w-lg mx-auto leading-relaxed">
              <strong>1.</strong> Type a topic or company name above and press{" "}
              <strong>Enter</strong>. <strong>2.</strong> Optionally paste LinkedIn post URL(s)
              (to also get <strong>Similar Profiles</strong>), or leave blank. <strong>3.</strong>{" "}
              Press <strong>Enter</strong> to view ranked contacts.
            </p>
          </div>
        )}
      </main>

      <footer className="w-full bg-surface border-t border-outline-border py-2.5">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 flex flex-wrap items-center justify-between gap-2 text-[11px] text-on-surface-variant">
          <span>
            EDXSO · Public LinkedIn metadata only · {config?.data_retention_days ?? 30}-day export
            retention
          </span>
          <span className="font-mono">
            {result
              ? `${result.total_duration_secs.toFixed(2)}s · ${result.discovery_provider}`
              : `API: ${API_BASE_URL}`}
          </span>
        </div>
      </footer>

      <CredentialsModal
        open={credentialsOpen}
        onClose={() => setCredentialsOpen(false)}
        config={config}
        overrides={overrides}
        onChange={setOverrides}
      />
    </div>
  );
}
