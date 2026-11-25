"use client";

import { Code2, Download, KeyRound } from "lucide-react";
import type { ApiConfigResponse, PipelineRunResult } from "@/types/discovery";

interface HeaderBarProps {
  config: ApiConfigResponse | null;
  result: PipelineRunResult | null;
  onOpenCredentials: () => void;
  onExportCsv: () => void;
  onExportJson: () => void;
  exporting: "csv" | "json" | null;
}

export function HeaderBar({
  config,
  result,
  onOpenCredentials,
  onExportCsv,
  onExportJson,
  exporting,
}: HeaderBarProps) {
  const hasCoreKeys = Boolean(
    config?.credentials.gemini.configured &&
      (config?.credentials.serper.configured || config?.credentials.apify.configured)
  );

  return (
    <header className="sticky top-0 z-40 w-full bg-surface border-b border-outline-border">
      <div className="max-w-[1440px] mx-auto h-13 px-4 sm:px-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-6 h-6 rounded bg-primary flex items-center justify-center text-white font-display font-bold text-xs shrink-0">
            E
          </div>
          <span className="font-display font-semibold text-on-surface text-sm tracking-tight truncate">
            EDXSO · K12 Contact Discovery
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={onOpenCredentials}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-surface border border-outline-border text-xs font-medium text-on-surface-variant hover:text-on-surface hover:bg-surface-ground transition-colors cursor-pointer"
          >
            <KeyRound className="w-3.5 h-3.5" />
            <span>API Keys</span>
            {config && (
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  hasCoreKeys ? "bg-forest" : "bg-amber-accent"
                }`}
              />
            )}
          </button>

          <button
            type="button"
            disabled={!result || exporting !== null}
            onClick={onExportCsv}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-surface border border-outline-border text-xs font-medium text-on-surface hover:bg-surface-ground disabled:opacity-45 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-on-surface-variant" />
            <span>{exporting === "csv" ? "Exporting..." : "Export CSV"}</span>
          </button>

          <button
            type="button"
            disabled={!result || exporting !== null}
            onClick={onExportJson}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-surface border border-outline-border text-xs font-medium text-on-surface hover:bg-surface-ground disabled:opacity-45 disabled:cursor-not-allowed transition-colors cursor-pointer"
          >
            <Code2 className="w-3.5 h-3.5 text-on-surface-variant" />
            <span>{exporting === "json" ? "Exporting..." : "Export JSON"}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
