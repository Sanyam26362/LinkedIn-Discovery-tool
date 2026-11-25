import json
import re
from collections import OrderedDict
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


def _match_comment_to_post(
    comment_item: dict,
    posts: list[DiscoveredPost],
) -> DiscoveredPost | None:
    """Resolve an Apify comment item back to its exact source DiscoveredPost."""
    query_post = str((comment_item.get("query") or {}).get("post") or "").strip()
    if query_post:
        norm_query = normalize_linkedin_url(query_post)
        for post in posts:
            if post.post_url == norm_query:
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
) -> tuple[list[RawComment], dict[str, str]]:
    """Parse Apify comment dataset items into RawComment models and optional location hints."""
    raw_comments: list[RawComment] = []
    location_hints: dict[str, str] = {}

    for item in items:
        if item.get("type") not in (None, "comment"):
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

    return raw_comments, location_hints


def fetch_comments_via_apify(
    posts: list[DiscoveredPost],
    apify_token: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
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
            return (
                [RawComment(**rc) for rc in cached["raw_comments"]],
                dict(cached.get("location_hints") or {}),
            )

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
    raw_comments, location_hints = parse_apify_comments(items, posts)

    if use_cache:
        c_key = build_cache_key(cache_payload)
        set_cached_json(
            "apify_comments",
            c_key,
            {
                "raw_comments": [rc.model_dump(mode="json") for rc in raw_comments],
                "location_hints": location_hints,
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


def extract_and_deduplicate_commenters(
    posts: list[DiscoveredPost],
    mode: DataSourceMode,
    apify_token: str | None = None,
    max_comments_per_post: int | None = None,
    use_cache: bool = True,
) -> list[DeduplicatedCommenter]:
    """Extract all commenters across posts and deduplicate by canonical profile URL."""
    location_hints: dict[str, str] = {}
    if mode == DataSourceMode.TEST_DATASET:
        raw_comments = load_sample_comments(posts)
    else:
        raw_comments, location_hints = fetch_comments_via_apify(
            posts,
            apify_token=apify_token,
            max_comments_per_post=max_comments_per_post,
            use_cache=use_cache,
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

    return list(grouped.values())
