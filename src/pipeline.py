from concurrent.futures import ThreadPoolExecutor
import time
from collections.abc import Callable
from src.config import TARGET_POST_COUNT
from src.schemas import DataSourceMode, PipelineRunResult
from src.stage1_input import parse_search_phrase
from src.stage2_discovery import (
    discover_posts_live_with_meta,
    discover_related_companies,
    load_sample_posts,
    load_supplied_posts,
)
from src.stage3_extraction import extract_and_deduplicate_commenters
from src.stage4_ai_analysis import analyze_all_commenters_with_meta
from src.stage5_ranking import rank_commenters


def run_pipeline(
    raw_phrase: str | None = None,
    mode: DataSourceMode = DataSourceMode.LIVE_API,
    supplied_urls: list[str] | None = None,
    gemini_api_key: str | None = None,
    apify_token: str | None = None,
    serper_api_key: str | None = None,
    groq_api_key: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
    on_progress: Callable[[int, str], None] | None = None,
) -> PipelineRunResult:
    """Execute all 6 stages from search phrase to ranked results and record stage timings."""
    pipeline_start = time.perf_counter()
    stage_timings: dict[str, float] = {}
    warnings: list[str] = []

    def notify(step: int, msg: str) -> None:
        if on_progress:
            on_progress(step, msg)

    # Stage 1: Phrase Input
    t0 = time.perf_counter()
    notify(1, "Normalizing search phrase...")
    phrase = parse_search_phrase(raw_phrase)
    stage_timings["stage1_input"] = round(time.perf_counter() - t0, 2)

    # Stage 2: Post Discovery (+ prefetch LinkedIn related companies concurrently in live_api)
    t0 = time.perf_counter()
    notify(2, f"Discovering recent LinkedIn posts for '{phrase}' ({mode.value})...")
    serp_company_future = None
    company_pool: ThreadPoolExecutor | None = None
    if mode == DataSourceMode.LIVE_API:
        company_pool = ThreadPoolExecutor(max_workers=1)
        serp_company_future = company_pool.submit(
            discover_related_companies,
            phrase,
            None,
            serper_api_key,
            use_cache,
            5,
        )
        posts, discovery_provider, stage2_warnings = discover_posts_live_with_meta(
            phrase,
            apify_token=apify_token,
            limit=TARGET_POST_COUNT,
            serper_api_key=serper_api_key,
            use_cache=use_cache,
        )
        warnings.extend(stage2_warnings)
    elif mode == DataSourceMode.SUPPLIED_URLS:
        posts = load_supplied_posts(supplied_urls or [], phrase=phrase)
        discovery_provider = "Supplied URLs"
    else:
        posts = load_sample_posts(limit=TARGET_POST_COUNT)
        discovery_provider = "Test Dataset"
    stage_timings["stage2_discovery"] = round(time.perf_counter() - t0, 2)

    # Stage 3: Commenter Extraction & Deduplication
    t0 = time.perf_counter()
    notify(3, f"Extracting and deduplicating commenters across {len(posts)} posts...")
    commenters = extract_and_deduplicate_commenters(
        posts=posts,
        mode=mode,
        apify_token=apify_token,
        max_comments_per_post=max_comments_per_post,
        use_cache=use_cache,
    )
    stage_timings["stage3_extraction"] = round(time.perf_counter() - t0, 2)

    if len(posts) < TARGET_POST_COUNT:
        warnings.append(
            f"Discovered {len(posts)} post(s) instead of target {TARGET_POST_COUNT} for '{phrase}'."
        )

    # Stage 4: AI Analysis (Concurrent Groq/Gemini Structured Extraction)
    t0 = time.perf_counter()
    if commenters:
        notify(4, f"Running AI structured analysis on {len(commenters)} unique profiles...")
        analyses, llm_model_used, stage4_warnings = analyze_all_commenters_with_meta(
            commenters,
            gemini_api_key=gemini_api_key,
            groq_api_key=groq_api_key,
            use_cache=use_cache,
        )
        warnings.extend(stage4_warnings)
    else:
        notify(4, "No public comments found across discovered posts; skipping AI analysis.")
        analyses, llm_model_used = {}, ""
        warnings.append("No public commenters were returned for the discovered posts.")
    stage_timings["stage4_ai_analysis"] = round(time.perf_counter() - t0, 2)

    # Stage 5: Semantic & Hybrid Ranking
    t0 = time.perf_counter()
    if commenters:
        notify(5, "Computing embedding similarity and hybrid relevance rankings...")
        ranked = rank_commenters(
            commenters,
            analyses,
            gemini_api_key=gemini_api_key,
            use_cache=use_cache,
        )
    else:
        notify(5, "Skipping ranking (0 commenters extracted).")
        ranked = []
    stage_timings["stage5_ranking"] = round(time.perf_counter() - t0, 2)

    # Stage 6: Results Assembly (+ hydrate 3-5 related companies)
    t0 = time.perf_counter()
    notify(6, "Assembling final traceable output...")
    if serp_company_future is not None:
        try:
            prefetched_companies = serp_company_future.result()
        except Exception:
            prefetched_companies = []
        finally:
            if company_pool is not None:
                company_pool.shutdown(wait=False)
        if len(prefetched_companies) < 5:
            related_companies = discover_related_companies(
                phrase=phrase,
                ranked_influencers=ranked,
                serper_api_key=serper_api_key,
                use_cache=True,
                limit=5,
            )
        else:
            related_companies = prefetched_companies[:5]
    else:
        related_companies = discover_related_companies(
            phrase=phrase,
            ranked_influencers=ranked,
            serper_api_key="" if mode == DataSourceMode.TEST_DATASET else serper_api_key,
            use_cache=use_cache,
            limit=5,
        )

    stage_timings["stage6_assembly"] = round(time.perf_counter() - t0, 2)
    total_duration = round(time.perf_counter() - pipeline_start, 2)

    return PipelineRunResult(
        search_phrase=phrase,
        source_mode=mode,
        discovery_provider=discovery_provider,
        llm_model_used=llm_model_used,
        total_duration_secs=total_duration,
        stage_timings_secs=stage_timings,
        total_posts=len(posts),
        total_unique_commenters=len(ranked),
        posts=posts,
        ranked_influencers=ranked,
        related_companies=related_companies,
        warnings=warnings,
    )
