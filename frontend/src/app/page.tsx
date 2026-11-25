"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Info } from "lucide-react";
import {
  CredentialsModal,
  type RuntimeCredentialOverrides,
} from "@/components/CredentialsModal";
import { DiscoveredPostsGrid } from "@/components/DiscoveredPostsGrid";
import { DiscoveryToolbar } from "@/components/DiscoveryToolbar";
import { HeaderBar } from "@/components/HeaderBar";
import { InfluencersWorkbench } from "@/components/InfluencersWorkbench";
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

type ActiveTab = "contacts" | "posts";

export default function HomePage() {
  const [config, setConfig] = useState<ApiConfigResponse | null>(null);
  const [result, setResult] = useState<PipelineRunResult | null>(null);
  const [phrase, setPhrase] = useState("K12 B2B Sales");
  const [mode, setMode] = useState<DataSourceMode>("live_api");
  const [suppliedUrlsText, setSuppliedUrlsText] = useState("");
  const [useCache, setUseCache] = useState(true);
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
        }
      } catch (err) {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? `Backend API unreachable (${err.message}). Start 'python api.py' on port 8000.`
            : "Backend API unreachable. Start 'python api.py' on port 8000."
        );
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleRunDiscovery = async () => {
    setErrorMsg(null);
    setFocusedPostUrl(null);
    setIsRunning(true);
    setProgress({ step: 1, total_steps: 6, message: "Starting search..." });

    try {
      const suppliedUrls = suppliedUrlsText
        .split(/\r?\n/)
        .map((u) => u.trim())
        .filter(Boolean);

      const parsedMaxComments = overrides.max_comments_per_post.trim()
        ? Number.parseInt(overrides.max_comments_per_post.trim(), 10)
        : undefined;

      const nextResult = await runDiscoveryStream(
        {
          phrase,
          mode,
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
      setActiveTab("contacts");
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
          phrase={phrase}
          onPhraseChange={setPhrase}
          mode={mode}
          onModeChange={setMode}
          suppliedUrlsText={suppliedUrlsText}
          onSuppliedUrlsChange={setSuppliedUrlsText}
          useCache={useCache}
          onUseCacheChange={setUseCache}
          isRunning={isRunning}
          progress={progress}
          result={result}
          onRun={handleRunDiscovery}
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
              <strong>Demo Dataset Mode:</strong> Showing clearly labelled sample fixture (
              <code>data/sample_dataset.json</code>) scored live.
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
          <>
            <div className="border-b border-outline-border flex items-center gap-6">
              <button
                type="button"
                onClick={() => setActiveTab("contacts")}
                className={`pb-2.5 text-xs font-semibold border-b-2 transition-colors cursor-pointer ${
                  activeTab === "contacts"
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

            {activeTab === "contacts" ? (
              <InfluencersWorkbench
                key={result.generated_at_utc}
                influencers={result.ranked_influencers}
                focusedPostUrl={focusedPostUrl}
                onClearPostFocus={() => setFocusedPostUrl(null)}
              />
            ) : (
              <DiscoveredPostsGrid
                posts={result.posts}
                influencers={result.ranked_influencers}
                focusedPostUrl={focusedPostUrl}
                onSelectPostForFilter={(url) => {
                  setFocusedPostUrl((prev) => (prev === url ? null : url));
                  setActiveTab("contacts");
                }}
              />
            )}
          </>
        ) : (
          <div className="bg-surface rounded-lg border border-outline-border p-10 text-center space-y-2">
            <h2 className="font-display font-semibold text-sm text-on-surface">
              Find school decision-makers and education contacts
            </h2>
            <p className="text-xs text-on-surface-variant max-w-md mx-auto">
              Enter a topic phrase above (such as <strong>K12 B2B Sales</strong>) and click{" "}
              <strong>Find Contacts</strong> to discover relevant LinkedIn posts, people commenting
              on them, and related organizations.
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
