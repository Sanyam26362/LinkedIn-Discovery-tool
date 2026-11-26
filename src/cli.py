import argparse
import re
import sys
from src.config import DATA_RETENTION_DAYS, DEFAULT_SEARCH_PHRASE, OUTPUTS_DIR
from src.pipeline import run_pipeline
from src.schemas import DataSourceMode
from src.stage6_export import save_outputs


def _configure_utf8_stdio() -> None:
    """Prevent Windows cp1252 console encoding errors when printing LinkedIn Unicode text."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="EDXSO LinkedIn School Influencer Discovery Tool"
    )
    parser.add_argument(
        "--phrase",
        type=str,
        default=DEFAULT_SEARCH_PHRASE,
        help='Search phrase to discover LinkedIn posts (default: "K12 B2B Sales")',
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in DataSourceMode],
        default=DataSourceMode.LIVE_API.value,
        help="Data retrieval mode: live_api, supplied_urls, or test_dataset",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        default=[],
        help="Optional list of LinkedIn post URLs when using --mode supplied_urls",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=None,
        help="Optional override for maximum comments scraped per post",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the local TTL cache to force fresh live API calls",
    )
    args = parser.parse_args()

    mode = DataSourceMode(args.mode)
    result = run_pipeline(
        raw_phrase=args.phrase,
        mode=mode,
        supplied_urls=args.urls,
        max_comments_per_post=args.max_comments,
        use_cache=not args.no_cache,
        on_progress=lambda step, msg: print(f"[Stage {step}/6] {msg}"),
    )

    slug = re.sub(r"[^a-z0-9]+", "_", result.search_phrase.lower()).strip("_") or "results"
    json_path, csv_path = save_outputs(result, OUTPUTS_DIR, file_prefix=f"{slug}_results")

    if result.source_mode == DataSourceMode.TEST_DATASET:
        print("\n[NOTE] Running on the clearly labelled offline reference test dataset.")

    if result.warnings:
        print("\n=== PIPELINE NOTICES ===")
        for w in result.warnings:
            print(f"- {w}")

    print("\n=== DISCOVERED POSTS ===")
    for idx, p in enumerate(result.posts, start=1):
        print(f"{idx}. [{p.author_name}] ({p.published_date}) -> {p.post_url}")
        print(f"   Snippet: {p.snippet}")

    print("\n=== RANKED SCHOOL ECOSYSTEM INFLUENCERS ===")
    if not result.ranked_influencers:
        print("No public commenters extracted for these posts.")
    for inf in result.ranked_influencers:
        print(
            f"#{inf.rank} {inf.name} | Score: {inf.final_relevance_score}/100 "
            f"(LLM: {inf.llm_fit_score}, Emb: {inf.embedding_similarity}, Bonus: +{inf.engagement_bonus}) | "
            f"{inf.current_role} @ {inf.organization} | {inf.location}"
        )
        print(f"   Profile: {inf.profile_url}")
        print(f"   Indicators: {', '.join(inf.school_ecosystem_indicators)}")
        print(f"   Why: {inf.match_explanation}")
        print(
            f"   Commented on ({inf.commented_post_count}): "
            f"{', '.join(t.post_url for t in inf.commented_posts)}\n"
        )

    if result.similar_profiles:
        print("\n=== SIMILAR LINKEDIN PROFILES (LOOKALIKES) ===")
        for sp in result.similar_profiles:
            print(
                f"#{sp.rank} {sp.name} | Match: {sp.similarity_score:.1f}% "
                f"(Seed: {sp.seed_similarity:.0f}%, Persona: {sp.persona_similarity:.0f}%) "
                f"| Similar to {sp.matched_seed_name}"
            )
            print(f"   Role: {sp.headline or sp.current_role}")
            print(f"   Profile: {sp.profile_url}")
            if sp.match_reason:
                print(f"   Why: {sp.match_reason}")

    if result.related_companies:
        print("\n=== RELATED COMPANIES ===")
        for idx, comp in enumerate(result.related_companies, start=1):
            print(f"{idx}. {comp.name} [{comp.category}] -> {comp.company_url}")
            if comp.description:
                print(f"   {comp.description}")

    timings_str = " | ".join(f"{k}={v:.2f}s" for k, v in result.stage_timings_secs.items())
    print(f"Saved JSON -> {json_path}")
    print(f"Saved CSV  -> {csv_path}")
    print(
        f"Runtime: {result.total_duration_secs:.2f}s "
        f"[Discovery: {result.discovery_provider or 'N/A'}, LLM: {result.llm_model_used or 'N/A'}]"
    )
    if timings_str:
        print(f"Stage Timings: {timings_str}")
    print(
        f"Data Governance: Outreach-relevant fields only; max retention {DATA_RETENTION_DAYS} days."
    )


if __name__ == "__main__":
    main()
