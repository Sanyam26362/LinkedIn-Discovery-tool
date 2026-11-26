"use client";

import { useMemo, useState } from "react";
import { Check, Copy, Search, Users } from "lucide-react";
import { LinkedInIcon } from "@/components/LinkedInIcon";
import type { SimilarProfile } from "@/types/discovery";

interface SimilarProfilesTabProps {
  profiles: SimilarProfile[];
  seedFilterUrl: string | null;
  onClearSeedFilter: () => void;
}

function scoreTone(score: number) {
  if (score >= 75) {
    return {
      text: "text-forest",
      pill: "bg-emerald-50 text-forest border-emerald-200",
    };
  }
  if (score >= 45) {
    return {
      text: "text-amber-accent",
      pill: "bg-amber-50 text-amber-accent border-amber-200",
    };
  }
  return {
    text: "text-on-surface-variant",
    pill: "bg-surface-ground text-on-surface-variant border-outline-border",
  };
}

export function SimilarProfilesTab({
  profiles,
  seedFilterUrl,
  onClearSeedFilter,
}: SimilarProfilesTabProps) {
  const [query, setQuery] = useState("");
  const [selectedSeedName, setSelectedSeedName] = useState<string>("ALL");
  const [selectedUrl, setSelectedUrl] = useState<string | null>(
    profiles[0]?.profile_url ?? null
  );
  const [copied, setCopied] = useState(false);

  const seedNames = useMemo(() => {
    return Array.from(new Set(profiles.map((p) => p.matched_seed_name).filter(Boolean)));
  }, [profiles]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return profiles.filter((p) => {
      if (seedFilterUrl && p.matched_seed_url !== seedFilterUrl) {
        return false;
      }
      if (selectedSeedName !== "ALL" && p.matched_seed_name !== selectedSeedName) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        p.name,
        p.headline,
        p.current_role,
        p.organization,
        p.snippet,
        p.matched_seed_name,
        p.match_reason,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [profiles, seedFilterUrl, selectedSeedName, query]);

  const activeProfile = useMemo(() => {
    return (
      filtered.find((p) => p.profile_url === selectedUrl) ??
      filtered[0] ??
      null
    );
  }, [filtered, selectedUrl]);

  const handleCopySummary = async (profile: SimilarProfile) => {
    const lines = [
      `#${profile.rank} ${profile.name} — Similarity: ${profile.similarity_score.toFixed(1)}%`,
      `Headline: ${profile.headline || profile.current_role}`,
      `Matched Seed Contact: ${profile.matched_seed_name} (${profile.matched_seed_role})`,
      `LinkedIn: ${profile.profile_url}`,
      `Reason: ${profile.match_reason}`,
    ];
    await navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (profiles.length === 0) {
    return (
      <div className="bg-surface rounded-lg border border-outline-border p-10 text-center space-y-2">
        <Users className="w-6 h-6 text-on-surface-variant mx-auto" />
        <h3 className="font-display font-semibold text-sm text-on-surface">
          No similar profiles discovered yet
        </h3>
        <p className="text-xs text-on-surface-variant max-w-md mx-auto">
          Run a search with <strong>SERPER_API_KEY</strong> configured, or open any contact in{" "}
          <strong>Matching Contacts</strong> and click <strong>Find Similar Profiles</strong>.
        </p>
      </div>
    );
  }

  return (
    <section className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
      {/* Left: Scrollable Similar Profiles Table */}
      <div className="lg:col-span-7 bg-surface rounded-lg border border-outline-border flex flex-col overflow-hidden h-[calc(100vh-242px)] min-h-[430px] max-h-[670px]">
        <div className="p-3 border-b border-outline-border flex flex-wrap items-center gap-2 shrink-0">
          <div className="relative flex-1 min-w-[160px]">
            <Search className="w-3.5 h-3.5 text-on-surface-variant absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search similar profiles, role, org..."
              className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
            />
          </div>

          <select
            aria-label="Filter similar profiles by seed contact"
            value={selectedSeedName}
            onChange={(e) => setSelectedSeedName(e.target.value)}
            className="px-2 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary cursor-pointer max-w-[190px]"
          >
            <option value="ALL">All seed contacts ({profiles.length})</option>
            {seedNames.map((seed) => (
              <option key={seed} value={seed}>
                Similar to {seed}
              </option>
            ))}
          </select>

          {seedFilterUrl && (
            <button
              type="button"
              onClick={onClearSeedFilter}
              className="px-2 py-1.5 rounded text-xs font-medium bg-primary-container text-on-primary-container cursor-pointer"
            >
              Seed filter ×
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto clean-scroll">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface-ground text-[10px] font-mono uppercase text-on-surface-variant border-b border-outline-border">
              <tr>
                <th className="py-2.5 px-2.5 w-9 text-center">#</th>
                <th className="py-2.5 px-2.5">Similar Profile</th>
                <th className="py-2.5 px-2 w-16 text-right">Match</th>
                <th className="py-2.5 px-2 w-28">Similar To</th>
                <th className="py-2.5 px-2.5 w-20 text-right">LinkedIn</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-border">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-14 text-center text-xs text-on-surface-variant">
                    No similar profiles match your current filter.
                  </td>
                </tr>
              ) : (
                filtered.map((profile, idx) => {
                  const isSelected = activeProfile?.profile_url === profile.profile_url;
                  const tone = scoreTone(profile.similarity_score);

                  return (
                    <tr
                      key={profile.profile_url}
                      onClick={() => setSelectedUrl(profile.profile_url)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-primary/5 border-l-3 border-l-primary"
                          : "hover:bg-surface-ground/70"
                      }`}
                    >
                      <td
                        className={`py-2.5 px-2.5 font-mono text-center ${
                          isSelected ? "text-primary font-bold" : "text-on-surface-variant"
                        }`}
                      >
                        {idx + 1}
                      </td>

                      <td className="py-2.5 px-2.5 max-w-[270px]">
                        <div
                          className={`font-semibold truncate ${
                            isSelected ? "text-primary" : "text-on-surface"
                          }`}
                        >
                          {profile.name}
                        </div>
                        <div
                          className="text-[11px] text-on-surface-variant truncate mt-0.5"
                          title={profile.headline || profile.current_role}
                        >
                          {profile.headline || profile.current_role}
                        </div>
                      </td>

                      <td className="py-2.5 px-2 text-right">
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded border font-mono text-[11px] font-semibold tabular-nums ${tone.pill}`}
                        >
                          {profile.similarity_score.toFixed(1)}
                        </span>
                      </td>

                      <td className="py-2.5 px-2 text-[11px] text-on-surface-variant truncate max-w-[120px]">
                        {profile.matched_seed_name}
                      </td>

                      <td className="py-2.5 px-2.5 text-right">
                        <a
                          href={profile.profile_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          title={`Open ${profile.name} on LinkedIn`}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded border border-[#0A66C2]/25 bg-[#0A66C2]/5 hover:bg-[#0A66C2]/15 text-[#0A66C2] text-[11px] font-medium transition-colors"
                        >
                          <LinkedInIcon className="w-3.5 h-3.5 shrink-0" />
                          <span>Profile</span>
                        </a>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: Similar Profile Details Inspector */}
      <aside className="lg:col-span-5 bg-surface rounded-lg border border-outline-border h-[calc(100vh-242px)] min-h-[430px] max-h-[670px] overflow-y-auto clean-scroll p-4 space-y-4">
        {activeProfile ? (
          <>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-mono font-semibold text-primary">
                  Lookalike Profile #{activeProfile.rank}
                </span>
                <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-surface-ground text-on-surface border border-outline-border">
                  Similar to {activeProfile.matched_seed_name}
                </span>
              </div>

              <div>
                <h4 className="text-base font-display font-bold text-on-surface leading-snug">
                  {activeProfile.name}
                </h4>
                <p className="text-xs text-on-surface-variant mt-0.5">
                  {activeProfile.headline || activeProfile.current_role}
                </p>
              </div>

              <a
                href={activeProfile.profile_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded border border-[#0A66C2]/30 bg-[#0A66C2]/5 hover:bg-[#0A66C2]/10 text-xs font-semibold text-[#0A66C2] transition-colors w-full"
              >
                <LinkedInIcon className="w-4 h-4 shrink-0" />
                <span>Open LinkedIn Profile</span>
              </a>
            </div>

            <div className="h-px bg-outline-border" />

            <div className="grid grid-cols-3 gap-2 text-center bg-surface-ground rounded border border-outline-border p-2.5">
              <div>
                <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                  Similarity
                </div>
                <div
                  className={`text-lg font-bold font-mono tabular-nums ${
                    scoreTone(activeProfile.similarity_score).text
                  }`}
                >
                  {activeProfile.similarity_score.toFixed(1)}
                </div>
              </div>
              <div className="border-x border-outline-border">
                <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                  Seed Match
                </div>
                <div className="text-lg font-bold font-mono tabular-nums text-on-surface">
                  {activeProfile.seed_similarity.toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                  Persona Fit
                </div>
                <div className="text-lg font-bold font-mono tabular-nums text-on-surface">
                  {activeProfile.persona_similarity.toFixed(1)}
                </div>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-semibold text-on-surface">Why they match</div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {activeProfile.match_reason}
              </p>
            </div>

            {activeProfile.snippet && (
              <div className="rounded border border-outline-border bg-surface-ground p-3 space-y-1">
                <div className="text-[11px] font-medium text-on-surface">
                  Public LinkedIn Snippet
                </div>
                <p className="text-xs text-on-surface-variant leading-relaxed">
                  {activeProfile.snippet}
                </p>
              </div>
            )}

            <button
              type="button"
              onClick={() => handleCopySummary(activeProfile)}
              className="w-full py-1.5 px-3 rounded border border-outline-border bg-surface text-xs font-medium text-on-surface hover:bg-surface-ground transition-colors inline-flex items-center justify-center gap-1.5 cursor-pointer"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-forest" />
              ) : (
                <Copy className="w-3.5 h-3.5 text-on-surface-variant" />
              )}
              <span>{copied ? "Copied Summary" : "Copy Summary"}</span>
            </button>
          </>
        ) : (
          <div className="py-16 text-center text-xs text-on-surface-variant">
            Click any profile on the left to inspect match details.
          </div>
        )}
      </aside>
    </section>
  );
}
