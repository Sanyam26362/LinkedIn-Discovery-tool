"use client";

import { useMemo, useState } from "react";
import {
  Bookmark,
  Check,
  Copy,
  MapPin,
  Search,
} from "lucide-react";
import { LinkedInIcon } from "@/components/LinkedInIcon";
import type { RankedInfluencer } from "@/types/discovery";

interface InfluencersWorkbenchProps {
  influencers: RankedInfluencer[];
  focusedPostUrl: string | null;
  onClearPostFocus: () => void;
}

const INDICATOR_ORDER = [
  "School/Education Consultant",
  "Former Principal/Director",
  "School Owner/Trustee",
  "Edu-Entrepreneur",
  "Multi-School Network Professional",
  "Decision-Maker Connector",
  "General / Non-K12 Specific",
];

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

export function InfluencersWorkbench({
  influencers,
  focusedPostUrl,
  onClearPostFocus,
}: InfluencersWorkbenchProps) {
  const [query, setQuery] = useState("");
  const [activeIndicator, setActiveIndicator] = useState<string>("ALL");
  const [savedOnly, setSavedOnly] = useState(false);
  const [savedUrls, setSavedUrls] = useState<Set<string>>(new Set());
  const [selectedUrl, setSelectedUrl] = useState<string | null>(
    influencers[0]?.profile_url ?? null
  );
  const [copiedMode, setCopiedMode] = useState<"summary" | "csv" | null>(null);

  const indicatorCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const inf of influencers) {
      for (const ind of inf.school_ecosystem_indicators) {
        counts.set(ind, (counts.get(ind) ?? 0) + 1);
      }
    }
    return counts;
  }, [influencers]);

  const availableIndicators = useMemo(() => {
    const present = Array.from(indicatorCounts.keys());
    return present.sort((a, b) => {
      const ia = INDICATOR_ORDER.indexOf(a);
      const ib = INDICATOR_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }, [indicatorCounts]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return influencers.filter((inf) => {
      if (focusedPostUrl) {
        const engaged = inf.commented_posts.some((t) => t.post_url === focusedPostUrl);
        if (!engaged) return false;
      }
      if (savedOnly && !savedUrls.has(inf.profile_url)) {
        return false;
      }
      if (
        activeIndicator !== "ALL" &&
        !inf.school_ecosystem_indicators.includes(activeIndicator)
      ) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        inf.name,
        inf.current_role,
        inf.organization,
        inf.location,
        inf.match_explanation,
        ...inf.school_ecosystem_indicators,
        ...inf.commented_posts.map((t) => t.comment_snippet),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [influencers, focusedPostUrl, savedOnly, savedUrls, activeIndicator, query]);

  const activeInfluencer = useMemo(() => {
    return (
      filtered.find((inf) => inf.profile_url === selectedUrl) ??
      filtered[0] ??
      null
    );
  }, [filtered, selectedUrl]);

  const toggleSaved = (profileUrl: string) => {
    setSavedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(profileUrl)) {
        next.delete(profileUrl);
      } else {
        next.add(profileUrl);
      }
      return next;
    });
  };

  const handleCopySummary = async (inf: RankedInfluencer) => {
    const lines = [
      `#${inf.rank} ${inf.name} — Match Score: ${inf.final_relevance_score.toFixed(1)}/100`,
      `Role: ${inf.current_role} @ ${inf.organization} (${inf.location})`,
      `Category: ${inf.school_ecosystem_indicators.join(", ")}`,
      `LinkedIn: ${inf.profile_url}`,
      `Relevance: ${inf.match_explanation}`,
      ...inf.commented_posts.map(
        (t) => `- Comment on ${t.post_author}'s post (${t.post_url}): "${t.comment_snippet}"`
      ),
    ];
    await navigator.clipboard.writeText(lines.join("\n"));
    setCopiedMode("summary");
    setTimeout(() => setCopiedMode(null), 1800);
  };

  const handleCopyCsvRow = async (inf: RankedInfluencer) => {
    const csvEscape = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const row = [
      inf.rank,
      inf.name,
      inf.profile_url,
      inf.current_role,
      inf.organization,
      inf.location,
      inf.school_ecosystem_indicators.join("; "),
      inf.final_relevance_score,
      inf.commented_posts.map((t) => t.post_url).join("; "),
      inf.match_explanation,
    ]
      .map(csvEscape)
      .join(",");
    await navigator.clipboard.writeText(row);
    setCopiedMode("csv");
    setTimeout(() => setCopiedMode(null), 1800);
  };

  return (
    <section className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
      {/* Column 1: Matching Contacts List (Scrollable) */}
      <div className="lg:col-span-7 bg-surface rounded-lg border border-outline-border flex flex-col overflow-hidden h-[calc(100vh-242px)] min-h-[430px] max-h-[670px]">
        <div className="p-3 border-b border-outline-border flex flex-wrap items-center gap-2 shrink-0">
          <div className="relative flex-1 min-w-[160px]">
            <Search className="w-3.5 h-3.5 text-on-surface-variant absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name, role, school..."
              className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
            />
          </div>

          <select
            aria-label="Filter contacts by category"
            value={activeIndicator}
            onChange={(e) => setActiveIndicator(e.target.value)}
            className="px-2 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary cursor-pointer max-w-[165px]"
          >
            <option value="ALL">All categories ({influencers.length})</option>
            {availableIndicators.map((ind) => (
              <option key={ind} value={ind}>
                {ind} ({indicatorCounts.get(ind) ?? 0})
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setSavedOnly((v) => !v)}
            className={`inline-flex items-center gap-1 px-2 py-1.5 rounded border text-xs font-medium shrink-0 transition-colors cursor-pointer ${
              savedOnly
                ? "bg-amber-50 text-amber-accent border-amber-200"
                : "bg-surface text-on-surface-variant border-outline-border hover:text-on-surface hover:bg-surface-ground"
            }`}
          >
            <Bookmark className="w-3.5 h-3.5" />
            <span>{savedUrls.size}</span>
          </button>

          {focusedPostUrl && (
            <button
              type="button"
              onClick={onClearPostFocus}
              className="px-2 py-1.5 rounded text-xs font-medium bg-primary-container text-on-primary-container cursor-pointer"
            >
              Post filter ×
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto clean-scroll">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10 bg-surface-ground text-[10px] font-mono uppercase text-on-surface-variant border-b border-outline-border">
              <tr>
                <th className="py-2.5 px-2.5 w-9 text-center">#</th>
                <th className="py-2.5 px-2.5">Contact</th>
                <th className="py-2.5 px-2 w-16 text-right">Match</th>
                <th className="py-2.5 px-2 w-12 text-center">Posts</th>
                <th className="py-2.5 px-2.5 w-20 text-right">LinkedIn</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-border">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-14 text-center text-xs text-on-surface-variant">
                    No contacts match your current filter.
                  </td>
                </tr>
              ) : (
                filtered.map((inf) => {
                  const isSelected = activeInfluencer?.profile_url === inf.profile_url;
                  const tone = scoreTone(inf.final_relevance_score);
                  const subtitle =
                    inf.organization && inf.organization !== "Not publicly listed"
                      ? `${inf.current_role} @ ${inf.organization}`
                      : inf.current_role;

                  return (
                    <tr
                      key={inf.profile_url}
                      onClick={() => setSelectedUrl(inf.profile_url)}
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
                        {inf.rank}
                      </td>

                      <td className="py-2.5 px-2.5 max-w-[300px]">
                        <div className="flex items-center gap-1">
                          <span
                            className={`font-semibold truncate ${
                              isSelected ? "text-primary" : "text-on-surface"
                            }`}
                          >
                            {inf.name}
                          </span>
                          {savedUrls.has(inf.profile_url) && (
                            <Bookmark className="w-3 h-3 text-amber-accent fill-current shrink-0" />
                          )}
                        </div>
                        <div
                          className="text-[11px] text-on-surface-variant truncate mt-0.5"
                          title={subtitle}
                        >
                          {subtitle}
                        </div>
                      </td>

                      <td className="py-2.5 px-2 text-right">
                        <span
                          className={`inline-block px-1.5 py-0.5 rounded border font-mono text-[11px] font-semibold tabular-nums ${tone.pill}`}
                        >
                          {inf.final_relevance_score.toFixed(1)}
                        </span>
                      </td>

                      <td className="py-2.5 px-2 text-center font-mono tabular-nums text-on-surface-variant">
                        {inf.commented_post_count}
                      </td>

                      <td className="py-2.5 px-2.5 text-right">
                        <a
                          href={inf.profile_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          title={`Open ${inf.name} on LinkedIn`}
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

      {/* Column 2: Selected Contact Details (Scrollable) */}
      <aside className="lg:col-span-5 bg-surface rounded-lg border border-outline-border h-[calc(100vh-242px)] min-h-[430px] max-h-[670px] overflow-y-auto clean-scroll p-4 space-y-4">
        {activeInfluencer ? (
          <>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-mono font-semibold text-primary">
                  Contact #{activeInfluencer.rank} of {influencers.length}
                </span>
                <button
                  type="button"
                  onClick={() => toggleSaved(activeInfluencer.profile_url)}
                  title="Bookmark contact"
                  className={`w-7 h-7 rounded border flex items-center justify-center transition-colors cursor-pointer ${
                    savedUrls.has(activeInfluencer.profile_url)
                      ? "border-amber-300 bg-amber-50 text-amber-accent"
                      : "border-outline-border text-on-surface-variant hover:text-on-surface hover:bg-surface-ground"
                  }`}
                >
                  <Bookmark
                    className={`w-3.5 h-3.5 ${
                      savedUrls.has(activeInfluencer.profile_url) ? "fill-current" : ""
                    }`}
                  />
                </button>
              </div>

              <div>
                <h4 className="text-base font-display font-bold text-on-surface leading-snug">
                  {activeInfluencer.name}
                </h4>
                <p className="text-xs text-on-surface-variant mt-0.5 line-clamp-2">
                  {activeInfluencer.current_role}
                  {activeInfluencer.organization !== "Not publicly listed"
                    ? ` · ${activeInfluencer.organization}`
                    : ""}
                </p>
                {activeInfluencer.location !== "Not publicly listed" && (
                  <div className="inline-flex items-center gap-1 text-[11px] text-on-surface-variant mt-1">
                    <MapPin className="w-3 h-3" />
                    <span>{activeInfluencer.location}</span>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-1.5">
                {activeInfluencer.school_ecosystem_indicators.map((ind) => (
                  <span
                    key={ind}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-surface-ground text-on-surface border border-outline-border"
                  >
                    {ind}
                  </span>
                ))}
              </div>

              <a
                href={activeInfluencer.profile_url}
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
                  Overall Match
                </div>
                <div
                  className={`text-lg font-bold font-mono tabular-nums ${
                    scoreTone(activeInfluencer.final_relevance_score).text
                  }`}
                >
                  {activeInfluencer.final_relevance_score.toFixed(1)}
                </div>
              </div>
              <div className="border-x border-outline-border">
                <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                  Profile Fit
                </div>
                <div className="text-lg font-bold font-mono tabular-nums text-on-surface">
                  {activeInfluencer.llm_fit_score.toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                  Topic Match
                </div>
                <div className="text-lg font-bold font-mono tabular-nums text-on-surface">
                  {activeInfluencer.embedding_similarity.toFixed(1)}
                </div>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-semibold text-on-surface">
                Why they are relevant
              </div>
              <p className="text-xs text-on-surface-variant leading-relaxed">
                {activeInfluencer.match_explanation}
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-on-surface">
                  LinkedIn Comments ({activeInfluencer.commented_post_count})
                </span>
                {activeInfluencer.engagement_bonus > 0 && (
                  <span className="text-[11px] font-mono text-forest font-medium">
                    +{activeInfluencer.engagement_bonus.toFixed(1)} bonus
                  </span>
                )}
              </div>

              {activeInfluencer.commented_posts.map((trace, idx) => (
                <div
                  key={`${trace.post_url}-${idx}`}
                  className="rounded border border-outline-border bg-surface-ground p-3 space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="font-medium text-on-surface">On {trace.post_author}&apos;s post</span>
                    <a
                      href={trace.post_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-[#0A66C2] font-medium hover:underline shrink-0"
                    >
                      <LinkedInIcon className="w-3 h-3" />
                      <span>View post</span>
                    </a>
                  </div>
                  <p className="text-xs text-on-surface-variant leading-relaxed">
                    &ldquo;{trace.comment_snippet || "Public comment recorded on thread."}&rdquo;
                  </p>
                </div>
              ))}
            </div>

            <div className="pt-1 flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleCopySummary(activeInfluencer)}
                className="flex-1 py-1.5 px-3 rounded border border-outline-border bg-surface text-xs font-medium text-on-surface hover:bg-surface-ground transition-colors inline-flex items-center justify-center gap-1.5 cursor-pointer"
              >
                {copiedMode === "summary" ? (
                  <Check className="w-3.5 h-3.5 text-forest" />
                ) : (
                  <Copy className="w-3.5 h-3.5 text-on-surface-variant" />
                )}
                <span>{copiedMode === "summary" ? "Copied" : "Copy Summary"}</span>
              </button>

              <button
                type="button"
                onClick={() => handleCopyCsvRow(activeInfluencer)}
                className="flex-1 py-1.5 px-3 rounded bg-primary text-white text-xs font-semibold hover:bg-[#0c3f6b] transition-colors inline-flex items-center justify-center gap-1.5 cursor-pointer"
              >
                {copiedMode === "csv" ? (
                  <Check className="w-3.5 h-3.5" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
                <span>{copiedMode === "csv" ? "Copied Row" : "Copy CSV Row"}</span>
              </button>
            </div>
          </>
        ) : (
          <div className="py-16 text-center text-xs text-on-surface-variant">
            Click any row on the left to view full profile details.
          </div>
        )}
      </aside>
    </section>
  );
}
