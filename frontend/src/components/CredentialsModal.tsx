"use client";

import { ShieldCheck, X } from "lucide-react";
import type { ApiConfigResponse } from "@/types/discovery";

export interface RuntimeCredentialOverrides {
  serper_api_key: string;
  groq_api_key: string;
  gemini_api_key: string;
  apify_token: string;
  max_comments_per_post: string;
}

interface CredentialsModalProps {
  open: boolean;
  onClose: () => void;
  config: ApiConfigResponse | null;
  overrides: RuntimeCredentialOverrides;
  onChange: (next: RuntimeCredentialOverrides) => void;
}

export function CredentialsModal({
  open,
  onClose,
  config,
  overrides,
  onChange,
}: CredentialsModalProps) {
  if (!open) return null;

  const fields: {
    key: keyof Omit<RuntimeCredentialOverrides, "max_comments_per_post">;
    label: string;
    role: string;
    status?: { configured: boolean; preview: string };
  }[] = [
    {
      key: "serper_api_key",
      label: "Serper API Key",
      role: "Fast (~1–3s) Stage 2 Google post discovery",
      status: config?.credentials.serper,
    },
    {
      key: "groq_api_key",
      label: "Groq API Key",
      role: "Concurrent Stage 4 structured LLM extraction",
      status: config?.credentials.groq,
    },
    {
      key: "gemini_api_key",
      label: "Gemini API Key",
      role: "Stage 5 semantic embeddings & Stage 4 fallback",
      status: config?.credentials.gemini,
    },
    {
      key: "apify_token",
      label: "Apify API Token",
      role: "Cookie-less Stage 3 comments & Stage 2 fallback",
      status: config?.credentials.apify,
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-900/25 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="API Credentials & Runtime Overrides"
        className="w-full max-w-lg bg-surface rounded-lg border border-outline-border shadow-lg overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3.5 border-b border-outline-border flex items-center justify-between">
          <div>
            <h2 className="font-display font-semibold text-sm text-on-surface">
              API Credentials &amp; Runtime Overrides
            </h2>
            <p className="text-[11px] text-on-surface-variant">
              Leave blank to use keys configured on the Python backend (.env).
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-on-surface-variant hover:text-on-surface hover:bg-surface-ground cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3.5 max-h-[75vh] overflow-y-auto">
          {fields.map((f) => (
            <div key={f.key} className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-medium text-on-surface">{f.label}</label>
                {f.status && (
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                      f.status.configured
                        ? "bg-emerald-50 text-forest border border-emerald-200"
                        : "bg-amber-50 text-amber-accent border border-amber-200"
                    }`}
                  >
                    {f.status.configured
                      ? `Env active (${f.status.preview})`
                      : "Not set in .env"}
                  </span>
                )}
              </div>
              <input
                type="password"
                value={overrides[f.key]}
                onChange={(e) => onChange({ ...overrides, [f.key]: e.target.value })}
                placeholder={`Optional override — ${f.role}`}
                className="w-full px-3 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface font-mono"
              />
            </div>
          ))}

          <div className="space-y-1 pt-1">
            <label className="text-xs font-medium text-on-surface">
              Max Comments Per Post (optional override)
            </label>
            <input
              type="number"
              min={5}
              max={200}
              value={overrides.max_comments_per_post}
              onChange={(e) =>
                onChange({ ...overrides, max_comments_per_post: e.target.value })
              }
              placeholder={`Default: ${config?.defaults.max_comments_per_post ?? 40}`}
              className="w-full px-3 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface font-mono"
            />
          </div>

          <div className="rounded border border-outline-border bg-surface-ground p-3 flex items-start gap-2.5 text-[11px] text-on-surface-variant leading-relaxed">
            <ShieldCheck className="w-4 h-4 text-forest shrink-0 mt-0.5" />
            <div>
              <strong className="text-on-surface">Responsible Access &amp; Governance:</strong>{" "}
              Uses public search indices and cookie-less Apify actors (no login/CAPTCHA bypass).
              Stores only outreach-relevant public metadata; refresh or purge exports within{" "}
              {config?.data_retention_days ?? 30} days.
            </div>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-outline-border bg-surface-ground flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
