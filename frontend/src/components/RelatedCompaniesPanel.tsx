"use client";

import { Building2 } from "lucide-react";
import { LinkedInIcon } from "@/components/LinkedInIcon";
import type { RelatedCompany } from "@/types/discovery";

interface RelatedCompaniesPanelProps {
  companies: RelatedCompany[];
  searchPhrase: string;
}

export function RelatedCompaniesPanel({
  companies,
  searchPhrase,
}: RelatedCompaniesPanelProps) {
  return (
    <aside className="lg:col-span-3 bg-surface rounded-lg border border-outline-border flex flex-col overflow-hidden h-[calc(100vh-242px)] min-h-[430px] max-h-[670px]">
      <div className="px-4 py-3 border-b border-outline-border flex items-center justify-between gap-2 shrink-0">
        <div className="min-w-0">
          <h3 className="font-display font-semibold text-xs text-on-surface flex items-center gap-1.5">
            <Building2 className="w-3.5 h-3.5 text-primary shrink-0" />
            <span>Related Companies ({companies.length})</span>
          </h3>
          <p className="text-[11px] text-on-surface-variant truncate mt-0.5">
            Organizations relevant to &ldquo;{searchPhrase}&rdquo;
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto clean-scroll divide-y divide-outline-border">
        {companies.length === 0 ? (
          <div className="p-6 text-center text-xs text-on-surface-variant">
            Run a discovery search to find 3–5 related companies.
          </div>
        ) : (
          companies.map((company) => (
            <div key={`${company.name}-${company.company_url}`} className="p-3.5 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div
                    className="font-semibold text-xs text-on-surface leading-snug line-clamp-1"
                    title={company.name}
                  >
                    {company.name}
                  </div>
                  <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-ground text-on-surface-variant border border-outline-border">
                    {company.category}
                  </span>
                </div>
              </div>

              {company.description && (
                <p className="text-[11px] text-on-surface-variant leading-relaxed line-clamp-2">
                  {company.description}
                </p>
              )}

              {company.related_contacts.length > 0 && (
                <div className="text-[10px] text-forest font-medium">
                  Contact: {company.related_contacts.join(", ")}
                </div>
              )}

              <div className="pt-0.5">
                <a
                  href={company.company_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-[#0A66C2]/25 bg-[#0A66C2]/5 hover:bg-[#0A66C2]/10 text-[11px] font-medium text-[#0A66C2] transition-colors"
                >
                  <LinkedInIcon className="w-3.5 h-3.5 shrink-0" />
                  <span>Open on LinkedIn</span>
                </a>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
