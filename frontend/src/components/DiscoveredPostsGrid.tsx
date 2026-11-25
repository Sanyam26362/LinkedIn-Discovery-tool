"use client";

import { ArrowRight } from "lucide-react";
import { LinkedInIcon } from "@/components/LinkedInIcon";
import type { DiscoveredPost, RankedInfluencer } from "@/types/discovery";

interface DiscoveredPostsGridProps {
  posts: DiscoveredPost[];
  influencers: RankedInfluencer[];
  focusedPostUrl: string | null;
  onSelectPostForFilter: (postUrl: string) => void;
}

export function DiscoveredPostsGrid({
  posts,
  influencers,
  focusedPostUrl,
  onSelectPostForFilter,
}: DiscoveredPostsGridProps) {
  const commentCountsByPost = new Map<string, number>();
  for (const inf of influencers) {
    for (const trace of inf.commented_posts) {
      commentCountsByPost.set(
        trace.post_url,
        (commentCountsByPost.get(trace.post_url) ?? 0) + 1
      );
    }
  }

  return (
    <section className="bg-surface rounded-lg border border-outline-border overflow-hidden">
      <div className="divide-y divide-outline-border max-h-[calc(100vh-250px)] overflow-y-auto clean-scroll">
        {posts.map((post, index) => {
          const count = commentCountsByPost.get(post.post_url) ?? 0;
          const isFocused = focusedPostUrl === post.post_url;

          return (
            <div
              key={post.post_url}
              className={`p-4 sm:px-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-colors ${
                isFocused ? "bg-primary/5" : "hover:bg-surface-ground/60"
              }`}
            >
              <div className="space-y-1.5 min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono text-on-surface-variant">#{index + 1}</span>
                  <span className="font-semibold text-on-surface">{post.author_name}</span>
                  <span className="text-outline-border">·</span>
                  <span className="font-mono text-on-surface-variant">{post.published_date}</span>
                  <span className="text-outline-border">·</span>
                  <span className="font-mono text-forest font-medium">
                    {count} {count === 1 ? "contact" : "contacts"}
                  </span>
                </div>
                <p className="text-xs text-on-surface-variant leading-relaxed">
                  {post.snippet}
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => onSelectPostForFilter(post.post_url)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded border text-xs font-medium transition-colors cursor-pointer ${
                    isFocused
                      ? "bg-primary text-white border-primary"
                      : "bg-surface text-on-surface border-outline-border hover:bg-surface-ground"
                  }`}
                >
                  <span>{isFocused ? "Clear Filter" : "Show Commenters"}</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>

                <a
                  href={post.post_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-[#0A66C2]/25 bg-[#0A66C2]/5 hover:bg-[#0A66C2]/10 text-xs font-medium text-[#0A66C2] transition-colors"
                >
                  <LinkedInIcon className="w-3.5 h-3.5" />
                  <span>Open Post</span>
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
