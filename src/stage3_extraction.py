import json
import logging
import re
from collections import OrderedDict
from urllib.parse import urlparse
from src.apify_client import run_apify_actor_and_fetch_items
from src.cache import build_cache_key, get_cached_json, set_cached_json
from src.config import (
    APIFY_API_TOKEN,
    APIFY_LINKEDIN_COMMENTS_ACTOR,
    APIFY_POLL_TIMEOUT_SECS,
    APIFY_PROFILE_SCRAPER_MODE,
    APIFY_SCRAPE_REPLIES,
    MAX_COMMENTS_PER_POST,
    SAMPLE_DATASET_PATH,
)
from src.schemas import (
    DataSourceMode,
    DeduplicatedCommenter,
    DiscoveredPost,
    PostTrace,
    RawComment,
    normalize_linkedin_url,
)


logger = logging.getLogger(__name__)


def _match_comment_to_post(
    comment_item: dict,
    posts: list[DiscoveredPost],
) -> DiscoveredPost | None:
    """Resolve an Apify comment item back to its exact source DiscoveredPost."""
    query_post = str((comment_item.get("query") or {}).get("post") or "").strip()
    if query_post:
        norm_query = normalize_linkedin_url(query_post)
        query_path = urlparse(norm_query).path.rstrip("/")
        for post in posts:
            if post.post_url == norm_query or (query_path and urlparse(post.post_url).path.rstrip("/") == query_path):
                return post
        query_id_match = re.search(r"(\d{15,22})", norm_query)
        if query_id_match:
            qid = query_id_match.group(1)
            for post in posts:
                if qid in post.post_url or post.post_id == qid:
                    return post

    post_id = str(comment_item.get("postId") or "").strip()
    if post_id:
        pid_digits = re.search(r"(\d{15,22})", post_id)
        digit_str = pid_digits.group(1) if pid_digits else post_id
        for post in posts:
            if digit_str in post.post_url or post.post_id == digit_str or post_id in post.post_url:
                return post

    comment_permalink = str(comment_item.get("linkedinUrl") or "").strip()
    if comment_permalink:
        base_permalink = normalize_linkedin_url(comment_permalink)
        id_match = re.search(r"(\d{15,22})", base_permalink)
        if id_match:
            extracted_id = id_match.group(1)
            for post in posts:
                if extracted_id in post.post_url or post.post_id == extracted_id:
                    return post

    return posts[0] if len(posts) == 1 else None


def _extract_actor_location(actor: dict) -> str:
    """Extract location string when returned by enriched profile scraper modes."""
    loc = actor.get("location")
    if isinstance(loc, dict):
        parts = [str(loc.get(k) or "").strip() for k in ("city", "state", "country", "linkedinText")]
        return ", ".join(p for p in parts if p)
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    parts = [str(actor.get(k) or "").strip() for k in ("city", "country")]
    return ", ".join(p for p in parts if p)


def parse_apify_comments(
    items: list[dict],
    posts: list[DiscoveredPost],
    *,
    include_replies: bool | None = None,
    stats_out: dict[str, int] | None = None,
) -> tuple[list[RawComment], dict[str, str]]:
    """Parse Apify comment dataset items into RawComment models and optional location hints."""
    raw_comments: list[RawComment] = []
    location_hints: dict[str, str] = {}
    allow_replies = APIFY_SCRAPE_REPLIES if include_replies is None else include_replies
    allowed_types = {None, "comment", "reply"} if allow_replies else {None, "comment"}
    unmatched_count = 0

    for item in items:
        raw_type = item.get("type")
        norm_type = str(raw_type).strip().lower() if raw_type is not None else None
        if norm_type not in allowed_types:
            continue
        actor = item.get("actor") or {}
        if actor.get("author") is True:
            # Skip the post author replying to their own post
            continue
        if str(actor.get("type") or "").lower() == "company":
            continue

        profile_url = str(actor.get("linkedinUrl") or "").strip()
        name = str(actor.get("name") or "").strip()
        if not profile_url or not name:
            continue
        if "/company/" in profile_url.lower():
            continue

        matched_post = _match_comment_to_post(item, posts)
        if not matched_post:
            unmatched_count += 1
            continue

        comment = RawComment(
            post_url=matched_post.post_url,
            commenter_name=name,
            profile_url=profile_url,
            headline=str(actor.get("position") or "").strip(),
            comment_text=str(item.get("commentary") or "").strip(),
        )
        raw_comments.append(comment)

        loc_hint = _extract_actor_location(actor)
        if loc_hint and comment.profile_url not in location_hints:
            location_hints[comment.profile_url] = loc_hint

    if unmatched_count > 0:
        logger.warning(
            "Stage 3 skipped %d comment item(s) that could not be matched to any discovered post.",
            unmatched_count,
        )
    if stats_out is not None:
        stats_out["unmatched_count"] = unmatched_count

    return raw_comments, location_hints


def fetch_comments_via_apify(
    posts: list[DiscoveredPost],
    apify_token: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
    warnings_out: list[str] | None = None,
) -> tuple[list[RawComment], dict[str, str]]:
    """Fetch public post comments via cookie-less Apify actor with optional TTL caching."""
    token = (APIFY_API_TOKEN if apify_token is None else apify_token).strip()
    if not token:
        raise ValueError("APIFY_API_TOKEN is required to extract LinkedIn comments.")

    if not posts:
        return [], {}

    max_items = max_comments_per_post or MAX_COMMENTS_PER_POST
    cache_payload = {
        "posts": sorted(p.post_url for p in posts),
        "max_items": max_items,
        "profile_mode": APIFY_PROFILE_SCRAPER_MODE,
        "scrape_replies": APIFY_SCRAPE_REPLIES,
    }
    if use_cache:
        c_key = build_cache_key(cache_payload)
        cached = get_cached_json("apify_comments", c_key)
        if isinstance(cached, dict) and "raw_comments" in cached:
            unmatched_cached = int(cached.get("unmatched_count") or 0)
            if unmatched_cached > 0 and warnings_out is not None:
                warnings_out.append(
                    f"Stage 3 skipped {unmatched_cached} comment(s) whose post ID/URL could not be matched."
                )
            return (
                [RawComment(**rc) for rc in cached["raw_comments"]],
                dict(cached.get("location_hints") or {}),
            )

    # Note: harvestapi~linkedin-post-comments applies `maxItems` per post URL rather than run-wide,
    # so one high-engagement post does not starve the remaining posts in a multi-post batch.
    payload = {
        "posts": [p.post_url for p in posts],
        "maxItems": max_items,
        "scrapeReplies": APIFY_SCRAPE_REPLIES,
        "profileScraperMode": APIFY_PROFILE_SCRAPER_MODE,
    }

    items = run_apify_actor_and_fetch_items(
        actor_id=APIFY_LINKEDIN_COMMENTS_ACTOR,
        payload=payload,
        token=token,
        timeout_secs=APIFY_POLL_TIMEOUT_SECS,
    )
    stats: dict[str, int] = {}
    raw_comments, location_hints = parse_apify_comments(items, posts, stats_out=stats)
    unmatched_count = stats.get("unmatched_count", 0)
    if unmatched_count > 0 and warnings_out is not None:
        warnings_out.append(
            f"Stage 3 skipped {unmatched_count} comment(s) whose post ID/URL could not be matched."
        )

    if use_cache:
        c_key = build_cache_key(cache_payload)
        set_cached_json(
            "apify_comments",
            c_key,
            {
                "raw_comments": [rc.model_dump(mode="json") for rc in raw_comments],
                "location_hints": location_hints,
                "unmatched_count": unmatched_count,
            },
        )

    return raw_comments, location_hints


def load_sample_comments(posts: list[DiscoveredPost]) -> list[RawComment]:
    """Load comments from the labelled test dataset matching discovered post URLs."""
    raw = json.loads(SAMPLE_DATASET_PATH.read_text(encoding="utf-8"))
    valid_urls = {p.post_url for p in posts}
    return [
        RawComment(**c)
        for c in raw.get("comments", [])
        if normalize_linkedin_url(c.get("post_url", "")) in valid_urls
    ]


def extract_and_deduplicate_commenters_with_meta(
    posts: list[DiscoveredPost],
    mode: DataSourceMode,
    apify_token: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
) -> tuple[list[DeduplicatedCommenter], list[str]]:
    """Extract all commenters across posts, deduplicate by profile URL, and collect warnings."""
    location_hints: dict[str, str] = {}
    warnings: list[str] = []
    if mode == DataSourceMode.TEST_DATASET:
        raw_comments = load_sample_comments(posts)
    else:
        raw_comments, location_hints = fetch_comments_via_apify(
            posts,
            apify_token=apify_token,
            max_comments_per_post=max_comments_per_post,
            use_cache=use_cache,
            warnings_out=warnings,
        )

    post_lookup = {p.post_url: p for p in posts}
    grouped: OrderedDict[str, DeduplicatedCommenter] = OrderedDict()

    for comment in raw_comments:
        key = comment.profile_url
        source_post = post_lookup.get(comment.post_url)
        author_label = source_post.author_name if source_post else "LinkedIn Author"

        trace = PostTrace(
            post_url=comment.post_url,
            post_author=author_label,
            comment_snippet=comment.comment_text[:240],
        )

        if key not in grouped:
            grouped[key] = DeduplicatedCommenter(
                profile_url=key,
                name=comment.commenter_name,
                headline=comment.headline,
                location_hint=location_hints.get(key, ""),
                commented_posts=[trace],
            )
        else:
            existing = grouped[key]
            if not existing.headline and comment.headline:
                existing.headline = comment.headline
            if not existing.location_hint and location_hints.get(key):
                existing.location_hint = location_hints[key]
            already_traced = {t.post_url for t in existing.commented_posts}
            if comment.post_url not in already_traced:
                existing.commented_posts.append(trace)

    return list(grouped.values()), warnings


def extract_and_deduplicate_commenters(
    posts: list[DiscoveredPost],
    mode: DataSourceMode,
    apify_token: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
) -> list[DeduplicatedCommenter]:
    """Extract all commenters across posts and deduplicate by canonical profile URL."""
    commenters, _ = extract_and_deduplicate_commenters_with_meta(
        posts=posts,
        mode=mode,
        apify_token=apify_token,
        max_comments_per_post=max_comments_per_post,
        use_cache=use_cache,
    )
    return commenters
