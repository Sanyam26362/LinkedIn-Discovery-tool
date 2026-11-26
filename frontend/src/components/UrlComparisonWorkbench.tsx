"use client";

import { useMemo, useState } from "react";
import {
  Bookmark,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Filter,
  MapPin,
  MessageSquare,
  Search,
  Users,
} from "lucide-react";
import { LinkedInIcon } from "@/components/LinkedInIcon";
import type { RankedInfluencer, SimilarProfile } from "@/types/discovery";

interface UrlComparisonWorkbenchProps {
  influencers: RankedInfluencer[];
  similarProfiles: SimilarProfile[];
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

export function UrlComparisonWorkbench({
  influencers,
  similarProfiles,
  focusedPostUrl,
  onClearPostFocus,
}: UrlComparisonWorkbenchProps) {
  // Column 1: Commenter People state
  const [commenterQuery, setCommenterQuery] = useState("");
  const [activeIndicator, setActiveIndicator] = useState<string>("ALL");
  const [savedOnly, setSavedOnly] = useState(false);
  const [savedUrls, setSavedUrls] = useState<Set<string>>(new Set());
  const [expandedCommenterUrl, setExpandedCommenterUrl] = useState<string | null>(
    influencers[0]?.profile_url ?? null
  );
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Column 2: Similar Profiles state
  const [similarQuery, setSimilarQuery] = useState("");
  const [seedFilterUrl, setSeedFilterUrl] = useState<string>("ALL");
  const [expandedSimilarUrl, setExpandedSimilarUrl] = useState<string | null>(
    similarProfiles[0]?.profile_url ?? null
  );

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
    return Array.from(indicatorCounts.keys()).sort((a, b) => {
      const ia = INDICATOR_ORDER.indexOf(a);
      const ib = INDICATOR_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }, [indicatorCounts]);

  const filteredCommenters = useMemo(() => {
    const q = commenterQuery.trim().toLowerCase();
    return influencers.filter((inf) => {
      if (focusedPostUrl && !inf.commented_posts.some((t) => t.post_url === focusedPostUrl)) {
        return false;
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
  }, [influencers, focusedPostUrl, savedOnly, savedUrls, activeIndicator, commenterQuery]);

  const seedOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const sp of similarProfiles) {
      if (sp.matched_seed_url && !seen.has(sp.matched_seed_url)) {
        seen.set(sp.matched_seed_url, sp.matched_seed_name);
      }
    }
    return Array.from(seen.entries()).map(([url, name]) => ({ url, name }));
  }, [similarProfiles]);

  const filteredSimilar = useMemo(() => {
    const q = similarQuery.trim().toLowerCase();
    return similarProfiles.filter((sp) => {
      if (seedFilterUrl !== "ALL" && sp.matched_seed_url !== seedFilterUrl) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        sp.name,
        sp.headline,
        sp.current_role,
        sp.organization,
        sp.snippet,
        sp.matched_seed_name,
        sp.match_reason,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [similarProfiles, seedFilterUrl, similarQuery]);

  const toggleSaved = (profileUrl: string) => {
    setSavedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(profileUrl)) next.delete(profileUrl);
      else next.add(profileUrl);
      return next;
    });
  };

  const copyText = async (key: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1600);
  };

  const handleCopyCommenterSummary = (inf: RankedInfluencer) => {
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
    void copyText(`c-sum-${inf.profile_url}`, lines.join("\n"));
  };

  const handleCopySimilarSummary = (sp: SimilarProfile) => {
    const lines = [
      `#${sp.rank} ${sp.name} — Similarity: ${sp.similarity_score.toFixed(1)}%`,
      `Headline: ${sp.headline || sp.current_role}`,
      `Matched Seed Contact: ${sp.matched_seed_name} (${sp.matched_seed_role})`,
      `LinkedIn: ${sp.profile_url}`,
      `Reason: ${sp.match_reason}`,
    ];
    void copyText(`s-sum-${sp.profile_url}`, lines.join("\n"));
  };

  return (
    <section className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
      {/* Column 1: Commenter People */}
      <div className="bg-surface rounded-lg border border-outline-border flex flex-col overflow-hidden h-[calc(100vh-265px)] min-h-[440px] max-h-[700px]">
        <div className="px-3.5 py-2.5 border-b border-outline-border bg-surface-ground/60 flex items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-primary" />
            <h3 className="font-display font-semibold text-xs text-on-surface">
              Commenter People
            </h3>
            <span className="px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-mono text-[11px] font-semibold">
              {filteredCommenters.length}
            </span>
          </div>
          <span className="text-[11px] text-on-surface-variant">From pasted post URL(s)</span>
        </div>

        <div className="p-2.5 border-b border-outline-border flex flex-wrap items-center gap-2 shrink-0">
          <div className="relative flex-1 min-w-[140px]">
            <Search className="w-3.5 h-3.5 text-on-surface-variant absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={commenterQuery}
              onChange={(e) => setCommenterQuery(e.target.value)}
              placeholder="Search commenter, role, comment..."
              className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
            />
          </div>

          <select
            aria-label="Filter commenters by category"
            value={activeIndicator}
            onChange={(e) => setActiveIndicator(e.target.value)}
            className="px-2 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary cursor-pointer max-w-[155px]"
          >
            <option value="ALL">All roles ({influencers.length})</option>
            {availableIndicators.map((ind) => (
              <option key={ind} value={ind}>
                {ind} ({indicatorCounts.get(ind) ?? 0})
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setSavedOnly((v) => !v)}
            title="Show bookmarked commenters"
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

        <div className="flex-1 overflow-y-auto clean-scroll divide-y divide-outline-border">
          {filteredCommenters.length === 0 ? (
            <div className="py-16 px-4 text-center text-xs text-on-surface-variant">
              {influencers.length === 0
                ? "No public comments were found on the pasted post URL(s)."
                : "No commenters match your current filter."}
            </div>
          ) : (
            filteredCommenters.map((inf) => {
              const isExpanded = expandedCommenterUrl === inf.profile_url;
              const tone = scoreTone(inf.final_relevance_score);
              const subtitle =
                inf.organization && inf.organization !== "Not publicly listed"
                  ? `${inf.current_role} @ ${inf.organization}`
                  : inf.current_role;
              const firstSnippet = inf.commented_posts[0]?.comment_snippet;
              const hasMatchingSimilar = similarProfiles.some(
                (sp) => sp.matched_seed_url === inf.profile_url
              );

              return (
                <div
                  key={inf.profile_url}
                  className={`transition-colors ${
                    isExpanded ? "bg-primary/[0.03]" : "hover:bg-surface-ground/60"
                  }`}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() =>
                      setExpandedCommenterUrl((prev) =>
                        prev === inf.profile_url ? null : inf.profile_url
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setExpandedCommenterUrl((prev) =>
                          prev === inf.profile_url ? null : inf.profile_url
                        );
                      }
                    }}
                    className="p-3 flex items-start justify-between gap-2.5 cursor-pointer"
                  >
                    <div className="flex items-start gap-2.5 min-w-0 flex-1">
                      <span
                        className={`font-mono text-xs w-6 text-center shrink-0 pt-0.5 ${
                          isExpanded ? "text-primary font-bold" : "text-on-surface-variant"
                        }`}
                      >
                        #{inf.rank}
                      </span>

                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs font-semibold truncate ${
                              isExpanded ? "text-primary" : "text-on-surface"
                            }`}
                          >
                            {inf.name}
                          </span>
                          {savedUrls.has(inf.profile_url) && (
                            <Bookmark className="w-3 h-3 text-amber-accent fill-current shrink-0" />
                          )}
                        </div>
                        <div className="text-[11px] text-on-surface-variant truncate" title={subtitle}>
                          {subtitle}
                        </div>
                        {firstSnippet && (
                          <div className="text-[11px] text-on-surface-variant/90 line-clamp-1 italic">
                            &ldquo;{firstSnippet}&rdquo;
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded border font-mono text-[11px] font-semibold tabular-nums ${tone.pill}`}
                      >
                        {inf.final_relevance_score.toFixed(1)}
                      </span>

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

                      <span className="text-on-surface-variant p-0.5">
                        {isExpanded ? (
                          <ChevronUp className="w-3.5 h-3.5" />
                        ) : (
                          <ChevronDown className="w-3.5 h-3.5" />
                        )}
                      </span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="px-3 pb-3 pt-1 ml-8 space-y-2.5 border-t border-outline-border/60">
                      <div className="flex flex-wrap items-center justify-between gap-2 pt-1.5">
                        <div className="flex flex-wrap gap-1.5">
                          {inf.school_ecosystem_indicators.map((ind) => (
                            <span
                              key={ind}
                              className="px-2 py-0.5 rounded text-[10px] font-medium bg-surface-ground text-on-surface border border-outline-border"
                            >
                              {ind}
                            </span>
                          ))}
                          {inf.location !== "Not publicly listed" && (
                            <span className="inline-flex items-center gap-1 text-[11px] text-on-surface-variant">
                              <MapPin className="w-3 h-3" />
                              {inf.location}
                            </span>
                          )}
                        </div>

                        <button
                          type="button"
                          onClick={() => toggleSaved(inf.profile_url)}
                          className={`px-2 py-0.5 rounded border text-[11px] inline-flex items-center gap-1 cursor-pointer ${
                            savedUrls.has(inf.profile_url)
                              ? "border-amber-300 bg-amber-50 text-amber-accent"
                              : "border-outline-border text-on-surface-variant hover:text-on-surface"
                          }`}
                        >
                          <Bookmark className="w-3 h-3" />
                          <span>{savedUrls.has(inf.profile_url) ? "Saved" : "Save"}</span>
                        </button>
                      </div>

                      <div className="grid grid-cols-3 gap-2 text-center bg-surface-ground rounded border border-outline-border p-2">
                        <div>
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Overall
                          </div>
                          <div className={`text-sm font-bold font-mono tabular-nums ${tone.text}`}>
                            {inf.final_relevance_score.toFixed(1)}
                          </div>
                        </div>
                        <div className="border-x border-outline-border">
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Profile Fit
                          </div>
                          <div className="text-sm font-bold font-mono tabular-nums text-on-surface">
                            {inf.llm_fit_score.toFixed(0)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Topic Match
                          </div>
                          <div className="text-sm font-bold font-mono tabular-nums text-on-surface">
                            {inf.embedding_similarity.toFixed(1)}
                          </div>
                        </div>
                      </div>

                      <p className="text-xs text-on-surface-variant leading-relaxed">
                        <strong className="text-on-surface font-semibold">Relevance: </strong>
                        {inf.match_explanation}
                      </p>

                      <div className="space-y-1.5">
                        {inf.commented_posts.map((trace, idx) => (
                          <div
                            key={`${trace.post_url}-${idx}`}
                            className="rounded border border-outline-border bg-surface-ground p-2 text-xs space-y-1"
                          >
                            <div className="flex items-center justify-between gap-2 text-[11px]">
                              <span className="font-medium text-on-surface">
                                Commented on {trace.post_author}&apos;s post
                              </span>
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
                            <p className="text-on-surface-variant">
                              &ldquo;{trace.comment_snippet || "Public comment recorded."}&rdquo;
                            </p>
                          </div>
                        ))}
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        {hasMatchingSimilar && (
                          <button
                            type="button"
                            onClick={() =>
                              setSeedFilterUrl((prev) =>
                                prev === inf.profile_url ? "ALL" : inf.profile_url
                              )
                            }
                            className={`px-2.5 py-1 rounded border text-[11px] font-medium inline-flex items-center gap-1 cursor-pointer ${
                              seedFilterUrl === inf.profile_url
                                ? "bg-primary text-white border-primary"
                                : "bg-surface text-primary border-primary/30 hover:bg-primary/5"
                            }`}
                          >
                            <Filter className="w-3 h-3" />
                            <span>
                              {seedFilterUrl === inf.profile_url
                                ? "Showing Similar →"
                                : "Filter Similar →"}
                            </span>
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => handleCopyCommenterSummary(inf)}
                          className="px-2.5 py-1 rounded border border-outline-border bg-surface text-[11px] font-medium text-on-surface hover:bg-surface-ground inline-flex items-center gap-1 cursor-pointer"
                        >
                          {copiedKey === `c-sum-${inf.profile_url}` ? (
                            <Check className="w-3 h-3 text-forest" />
                          ) : (
                            <Copy className="w-3 h-3 text-on-surface-variant" />
                          )}
                          <span>
                            {copiedKey === `c-sum-${inf.profile_url}` ? "Copied" : "Copy Summary"}
                          </span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Column 2: Similar Profiles */}
      <div className="bg-surface rounded-lg border border-outline-border flex flex-col overflow-hidden h-[calc(100vh-265px)] min-h-[440px] max-h-[700px]">
        <div className="px-3.5 py-2.5 border-b border-outline-border bg-surface-ground/60 flex items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-forest" />
            <h3 className="font-display font-semibold text-xs text-on-surface">
              Similar Profiles
            </h3>
            <span className="px-1.5 py-0.5 rounded-full bg-emerald-50 text-forest border border-emerald-200 font-mono text-[11px] font-semibold">
              {filteredSimilar.length}
            </span>
          </div>
          <span className="text-[11px] text-on-surface-variant">
            Lookalike LinkedIn profiles
          </span>
        </div>

        <div className="p-2.5 border-b border-outline-border flex flex-wrap items-center gap-2 shrink-0">
          <div className="relative flex-1 min-w-[140px]">
            <Search className="w-3.5 h-3.5 text-on-surface-variant absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={similarQuery}
              onChange={(e) => setSimilarQuery(e.target.value)}
              placeholder="Search similar profile, role, org..."
              className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary focus:bg-surface"
            />
          </div>

          <select
            aria-label="Filter similar profiles by commenter"
            value={seedFilterUrl}
            onChange={(e) => setSeedFilterUrl(e.target.value)}
            className="px-2 py-1.5 text-xs bg-surface-ground text-on-surface rounded border border-outline-border focus:outline-none focus:border-primary cursor-pointer max-w-[180px]"
          >
            <option value="ALL">All commenters ({similarProfiles.length})</option>
            {seedOptions.map((opt) => (
              <option key={opt.url} value={opt.url}>
                Similar to {opt.name}
              </option>
            ))}
          </select>

          {seedFilterUrl !== "ALL" && (
            <button
              type="button"
              onClick={() => setSeedFilterUrl("ALL")}
              className="px-2 py-1.5 rounded text-xs font-medium bg-primary-container text-on-primary-container cursor-pointer"
            >
              Reset ×
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto clean-scroll divide-y divide-outline-border">
          {filteredSimilar.length === 0 ? (
            <div className="py-16 px-4 text-center space-y-1.5">
              <Users className="w-5 h-5 text-on-surface-variant mx-auto" />
              <p className="text-xs font-medium text-on-surface">
                {similarProfiles.length === 0
                  ? "No similar profiles found for these commenters"
                  : "No similar profiles match your current filter."}
              </p>
              <p className="text-[11px] text-on-surface-variant max-w-xs mx-auto">
                {similarProfiles.length === 0
                  ? "Make sure SERPER_API_KEY is configured in API Keys and that the pasted post has public commenters."
                  : "Clear the search or commenter filter above to view all similar profiles."}
              </p>
            </div>
          ) : (
            filteredSimilar.map((profile, idx) => {
              const isExpanded = expandedSimilarUrl === profile.profile_url;
              const tone = scoreTone(profile.similarity_score);

              return (
                <div
                  key={profile.profile_url}
                  className={`transition-colors ${
                    isExpanded ? "bg-primary/[0.03]" : "hover:bg-surface-ground/60"
                  }`}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() =>
                      setExpandedSimilarUrl((prev) =>
                        prev === profile.profile_url ? null : profile.profile_url
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setExpandedSimilarUrl((prev) =>
                          prev === profile.profile_url ? null : profile.profile_url
                        );
                      }
                    }}
                    className="p-3 flex items-start justify-between gap-2.5 cursor-pointer"
                  >
                    <div className="flex items-start gap-2.5 min-w-0 flex-1">
                      <span
                        className={`font-mono text-xs w-6 text-center shrink-0 pt-0.5 ${
                          isExpanded ? "text-primary font-bold" : "text-on-surface-variant"
                        }`}
                      >
                        #{idx + 1}
                      </span>

                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={`text-xs font-semibold truncate ${
                              isExpanded ? "text-primary" : "text-on-surface"
                            }`}
                          >
                            {profile.name}
                          </span>
                          <span className="px-1.5 py-0.5 rounded bg-surface-ground border border-outline-border text-[10px] text-on-surface-variant truncate max-w-[160px]">
                            Similar to {profile.matched_seed_name}
                          </span>
                        </div>
                        <div
                          className="text-[11px] text-on-surface-variant truncate"
                          title={profile.headline || profile.current_role}
                        >
                          {profile.headline || profile.current_role}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded border font-mono text-[11px] font-semibold tabular-nums ${tone.pill}`}
                      >
                        {profile.similarity_score.toFixed(1)}
                      </span>

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

                      <span className="text-on-surface-variant p-0.5">
                        {isExpanded ? (
                          <ChevronUp className="w-3.5 h-3.5" />
                        ) : (
                          <ChevronDown className="w-3.5 h-3.5" />
                        )}
                      </span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="px-3 pb-3 pt-1 ml-8 space-y-2.5 border-t border-outline-border/60">
                      <div className="grid grid-cols-3 gap-2 text-center bg-surface-ground rounded border border-outline-border p-2 mt-1.5">
                        <div>
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Similarity
                          </div>
                          <div className={`text-sm font-bold font-mono tabular-nums ${tone.text}`}>
                            {profile.similarity_score.toFixed(1)}
                          </div>
                        </div>
                        <div className="border-x border-outline-border">
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Seed Match
                          </div>
                          <div className="text-sm font-bold font-mono tabular-nums text-on-surface">
                            {profile.seed_similarity.toFixed(0)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-mono uppercase text-on-surface-variant">
                            Persona Fit
                          </div>
                          <div className="text-sm font-bold font-mono tabular-nums text-on-surface">
                            {profile.persona_similarity.toFixed(1)}
                          </div>
                        </div>
                      </div>

                      <p className="text-xs text-on-surface-variant leading-relaxed">
                        <strong className="text-on-surface font-semibold">Why they match: </strong>
                        {profile.match_reason}
                      </p>

                      {profile.snippet && (
                        <div className="rounded border border-outline-border bg-surface-ground p-2 text-xs text-on-surface-variant leading-relaxed">
                          {profile.snippet}
                        </div>
                      )}

                      <button
                        type="button"
                        onClick={() => handleCopySimilarSummary(profile)}
                        className="px-2.5 py-1 rounded border border-outline-border bg-surface text-[11px] font-medium text-on-surface hover:bg-surface-ground inline-flex items-center gap-1 cursor-pointer"
                      >
                        {copiedKey === `s-sum-${profile.profile_url}` ? (
                          <Check className="w-3 h-3 text-forest" />
                        ) : (
                          <Copy className="w-3 h-3 text-on-surface-variant" />
                        )}
                        <span>
                          {copiedKey === `s-sum-${profile.profile_url}`
                            ? "Copied"
                            : "Copy Summary"}
                        </span>
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}
