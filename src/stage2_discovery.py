from concurrent.futures import ThreadPoolExecutor
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import httpx
from src.apify_client import run_apify_actor_and_fetch_items
from src.cache import build_cache_key, get_cached_json, set_cached_json
from src.config import (
    APIFY_API_TOKEN,
    APIFY_GOOGLE_SEARCH_ACTOR,
    APIFY_POLL_TIMEOUT_SECS,
    SAMPLE_DATASET_PATH,
    SERPER_API_KEY,
    TARGET_POST_COUNT,
)
from src.schemas import DataSourceMode, DiscoveredPost, RankedInfluencer, RelatedCompany, normalize_linkedin_url

_MIN_LINKEDIN_EPOCH_SECS = datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp()
_MAX_LINKEDIN_EPOCH_SECS = datetime(2035, 1, 1, tzinfo=timezone.utc).timestamp()
_SERPER_ENDPOINT = "https://google.serper.dev/search"


def extract_activity_id(url: str, fallback_idx: int) -> str:
    """Extract the 15-22 digit LinkedIn activity/post ID when present."""
    match = re.search(r"(\d{15,22})", url)
    return match.group(1) if match else f"post_{fallback_idx}"


def decode_linkedin_post_timestamp(url: str) -> datetime | None:
    """Decode UTC publication datetime from LinkedIn's 64-bit Snowflake activity ID."""
    match = re.search(r"(\d{18,20})", url)
    if not match:
        return None
    try:
        activity_num = int(match.group(1))
        ts_secs = (activity_num >> 22) / 1000.0
        if _MIN_LINKEDIN_EPOCH_SECS <= ts_secs <= _MAX_LINKEDIN_EPOCH_SECS:
            return datetime.fromtimestamp(ts_secs, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return None


def _is_linkedin_post_url(url: str) -> bool:
    lowered = url.lower()
    return (
        "linkedin.com/posts/" in lowered
        or "linkedin.com/feed/update/" in lowered
        or "linkedin.com/pulse/" in lowered
    )


def _extract_date_and_sort_ts(item: dict, clean_url: str) -> tuple[str, float]:
    """Resolve publication date (YYYY-MM-DD when known) and numeric timestamp for sorting."""
    decoded = decode_linkedin_post_timestamp(clean_url)
    if decoded is not None:
        return decoded.strftime("%Y-%m-%d"), decoded.timestamp()

    explicit_date = str(item.get("date") or "").strip()
    if explicit_date:
        return explicit_date, datetime.now(timezone.utc).timestamp()

    displayed = str(item.get("displayedUrl") or item.get("displayedLink") or "")
    rel = re.search(
        r"(\d+)\s+(hour|day|week|month|year)s?\s+ago",
        displayed,
        flags=re.IGNORECASE,
    )
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2).lower()
        days_map = {"hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}
        delta = (
            timedelta(hours=amount)
            if unit == "hour"
            else timedelta(days=amount * days_map[unit])
        )
        approx_dt = datetime.now(timezone.utc) - delta
        return f"~{rel.group(0)}", approx_dt.timestamp()

    return "Recent", 0.0


def _extract_author_name(item: dict, clean_url: str) -> str:
    """Extract author name reliably from SERP websiteTitle, title, or LinkedIn URL slug."""
    website_title = str(item.get("websiteTitle") or "").replace("\xa0", " ").strip()
    if "·" in website_title:
        parts = [p.strip() for p in website_title.split("·") if p.strip()]
        non_brand = [
            p
            for p in parts
            if p.lower() != "linkedin"
            and "|" not in p
            and len(p) <= 60
            and "community for" not in p.lower()
            and "read our rules" not in p.lower()
        ]
        if non_brand:
            return non_brand[-1]

    title = str(item.get("title") or "").strip()
    if " on LinkedIn:" in title:
        return title.split(" on LinkedIn:", 1)[0].strip()

    posted_match = re.search(
        r"(?:\|\s*)?([^|]+?)\s+posted(?:\s+on\b|\s*\.\.\.|$)",
        title,
        flags=re.IGNORECASE,
    )
    if posted_match:
        candidate = posted_match.group(1).strip()
        if candidate and candidate.lower() != "linkedin":
            return candidate

    # Handle Serper titles truncated right after the author name: "... | Brittany Miller, M.Ed. ..."
    pipe_trunc_match = re.search(r"\|\s*([^|]+?)\s+\.\.\.$", title)
    if pipe_trunc_match:
        candidate = pipe_trunc_match.group(1).strip()
        if (
            candidate
            and candidate.lower() != "linkedin"
            and len(candidate) <= 45
            and len(candidate.split()) <= 6
            and "#" not in candidate
        ):
            return candidate

    possessive_match = re.match(r"^(.+?)(?:'s|’s)\s+Post\b", title, flags=re.IGNORECASE)
    if possessive_match:
        return possessive_match.group(1).strip()

    if " - " in title:
        prefix = title.split(" - ", 1)[0].strip()
        if prefix and len(prefix) <= 60 and prefix.lower() != "linkedin":
            return prefix

    slug_match = re.search(r"linkedin\.com/posts/([^_/]+)", clean_url, flags=re.IGNORECASE)
    if slug_match:
        raw_slug = slug_match.group(1)
        tokens = [
            t
            for t in raw_slug.split("-")
            if not re.fullmatch(r"[0-9a-f]{5,}", t.lower())
            and not re.fullmatch(r"\d+", t)
        ]
        if tokens:
            return " ".join(tokens).title()

    return "LinkedIn Author"


def _normalize_match_text(text: str) -> str:
    """Normalize punctuation and common variants like K-12 -> K12 for matching."""
    lowered = text.lower()
    lowered = re.sub(r"(?<![a-z0-9])k-12(?![a-z0-9])", "k12", lowered)
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _relevance_key(phrase: str, text_blob: str, sort_ts: float) -> tuple[int, float, float]:
    """Rank candidates by topic completeness, exact-phrase preference, and recency."""
    norm_phrase = _normalize_match_text(phrase)
    norm_blob = _normalize_match_text(text_blob)
    tokens = [t for t in norm_phrase.split() if len(t) >= 2]

    exact_match = 1 if norm_phrase and norm_phrase in norm_blob else 0
    if tokens:
        matched_tokens = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", norm_blob))
        all_tokens = 1 if matched_tokens == len(tokens) else 0
        coverage = matched_tokens / len(tokens)
    else:
        all_tokens = 1
        coverage = 1.0

    # Within full-match posts, prefer newer posts while giving exact phrase matches a 90-day boost.
    effective_ts = sort_ts + (90 * 86400.0 if exact_match and sort_ts > 0 else 0.0)
    return (all_tokens, round(coverage, 3), effective_ts)


def parse_serp_pages_to_posts(
    serp_pages: list[dict],
    phrase: str,
    limit: int = TARGET_POST_COUNT,
) -> list[DiscoveredPost]:
    """Parse, deduplicate, and rank Apify or Serper Google SERP results into DiscoveredPost items."""
    candidates: list[tuple[tuple[int, float, float], DiscoveredPost]] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()

    for page in serp_pages:
        organic_items = page.get("organicResults")
        if organic_items is None:
            organic_items = page.get("organic", [])

        for item in organic_items:
            raw_url = str(item.get("url") or item.get("link") or "")
            if not _is_linkedin_post_url(raw_url):
                continue

            clean_url = normalize_linkedin_url(raw_url)
            post_id = extract_activity_id(clean_url, len(candidates) + 1)
            if clean_url in seen_urls or (not post_id.startswith("post_") and post_id in seen_ids):
                continue
            seen_urls.add(clean_url)
            seen_ids.add(post_id)

            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or item.get("snippet") or "").strip()
            author = _extract_author_name(item, clean_url)
            published_date, sort_ts = _extract_date_and_sort_ts(item, clean_url)
            snippet = (description or title or phrase).strip()[:320]

            post = DiscoveredPost(
                post_id=post_id,
                post_url=clean_url,
                author_name=author,
                published_date=published_date,
                snippet=snippet,
                source_mode=DataSourceMode.LIVE_API,
            )
            score_key = _relevance_key(
                phrase=phrase,
                text_blob=f"{title} {description} {clean_url}",
                sort_ts=sort_ts,
            )
            candidates.append((score_key, post))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [post for _, post in candidates[:limit]]


def _build_serp_queries(phrase: str) -> list[str]:
    return [
        f'(site:linkedin.com/posts OR site:linkedin.com/feed/update) "{phrase}"',
        f"(site:linkedin.com/posts OR site:linkedin.com/feed/update) {phrase}",
    ]


def _search_serper_pages(phrase: str, serper_key: str) -> list[dict]:
    """Run exact and broad Google queries concurrently via Serper.dev REST API (~1-3s)."""
    queries = _build_serp_queries(phrase)
    headers = {"X-API-KEY": serper_key.strip(), "Content-Type": "application/json"}

    with httpx.Client(headers=headers, timeout=15.0) as client:
        def _fetch_one(q: str) -> dict:
            resp = client.post(_SERPER_ENDPOINT, json={"q": q, "num": 10})
            if resp.status_code in (401, 403):
                raise ValueError("Serper API authentication failed. Verify your SERPER_API_KEY.")
            if resp.status_code >= 400:
                raise RuntimeError(f"Serper HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()

        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            return list(pool.map(_fetch_one, queries))


def _search_serper_companies(phrase: str, serper_key: str) -> list[dict]:
    """Query Google via Serper.dev for real LinkedIn company pages matching the topic."""
    headers = {"X-API-KEY": serper_key.strip(), "Content-Type": "application/json"}
    try:
        with httpx.Client(headers=headers, timeout=12.0) as client:
            resp = client.post(
                _SERPER_ENDPOINT,
                json={"q": f"site:linkedin.com/company {phrase}", "num": 6},
            )
            if resp.status_code >= 400:
                return []
            return list(resp.json().get("organic", []))
    except Exception:
        return []


def _parse_company_name_from_title(raw_title: str) -> str:
    cleaned = raw_title.replace(" | LinkedIn", "").replace(" - LinkedIn", "").strip()
    if " | " in cleaned:
        cleaned = cleaned.split(" | ", 1)[0].strip()
    return cleaned[:80] or "LinkedIn Company"


def _infer_company_category(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("consult", "advis", "agency", "coaching", "strategy")):
        return "Sales & Education Advisory"
    if any(k in low for k in ("school", "district", "academy", "trust", "prek", "k12", "k-12")):
        return "School Network / Provider"
    if any(k in low for k in ("edtech", "platform", "software", "vendor", "curriculum")):
        return "K12 EdTech / Vendor"
    return "Education Ecosystem"


def discover_related_companies(
    phrase: str,
    ranked_influencers: list[RankedInfluencer] | None = None,
    serper_api_key: str | None = None,
    use_cache: bool = True,
    limit: int = 5,
) -> list[RelatedCompany]:
    """Return 3-5 real related companies from LinkedIn's company index and top contact orgs."""
    resolved_serper = (SERPER_API_KEY if serper_api_key is None else serper_api_key).strip()
    serper_items: list[dict] = []

    if resolved_serper:
        c_key = build_cache_key({"type": "companies", "phrase": phrase.lower(), "limit": limit})
        cached = get_cached_json("serp_companies", c_key) if use_cache else None
        if isinstance(cached, list):
            serper_items = cached
        else:
            serper_items = _search_serper_companies(phrase, resolved_serper)
            if use_cache and serper_items:
                set_cached_json("serp_companies", c_key, serper_items)

    companies: list[RelatedCompany] = []
    seen_names: set[str] = set()
    seen_urls: set[str] = set()

    for item in serper_items:
        raw_link = str(item.get("link") or item.get("url") or "")
        if "linkedin.com/company/" not in raw_link.lower():
            continue
        clean_url = normalize_linkedin_url(raw_link)
        name = _parse_company_name_from_title(str(item.get("title") or ""))
        if not name or name.lower() in seen_names or clean_url in seen_urls:
            continue
        seen_names.add(name.lower())
        seen_urls.add(clean_url)
        snippet = str(item.get("snippet") or item.get("description") or "").strip()[:180]
        companies.append(
            RelatedCompany(
                name=name,
                company_url=clean_url,
                category=_infer_company_category(f"{name} {snippet}"),
                description=snippet or f"Relevant LinkedIn organization for {phrase}.",
                related_contacts=[],
                source="LinkedIn Company Index",
            )
        )
        if len(companies) >= limit:
            break

    # Supplement up to `limit` (or populate in Supplied URLs / Test Dataset mode) using
    # real organizations extracted from the highest-ranked ecosystem contacts.
    if len(companies) < limit and ranked_influencers:
        for inf in ranked_influencers:
            org = (inf.organization or "").strip()
            if not org or org.lower() == "not publicly listed":
                continue
            low_org = org.lower()
            if low_org in seen_names:
                continue
            # Avoid duplicates if Serper already captured the same company
            matched_existing = next(
                (c for c in companies if low_org in c.name.lower() or c.name.lower() in low_org),
                None,
            )
            if matched_existing:
                if inf.name not in matched_existing.related_contacts:
                    matched_existing.related_contacts.append(inf.name)
                continue

            seen_names.add(low_org)
            companies.append(
                RelatedCompany(
                    name=org,
                    company_url=f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(org)}",
                    category=_infer_company_category(f"{org} {inf.current_role} {inf.match_explanation}"),
                    description=f"Organization of #{inf.rank} contact {inf.name} ({inf.current_role}).",
                    related_contacts=[inf.name],
                    source="Top Contact Organization",
                )
            )
            if len(companies) >= limit:
                break

    return companies[:limit]


def _search_apify_serp_pages(phrase: str, apify_token: str) -> list[dict]:
    """Query public Google SERP index via cookie-less Apify actor (fallback when Serper is absent)."""
    payload = {
        "queries": "\n".join(_build_serp_queries(phrase)),
        "maxPagesPerQuery": 1,
        "saveHtmlToKeyValueStore": False,
    }
    return run_apify_actor_and_fetch_items(
        actor_id=APIFY_GOOGLE_SEARCH_ACTOR,
        payload=payload,
        token=apify_token,
        timeout_secs=APIFY_POLL_TIMEOUT_SECS,
    )


def discover_posts_live_with_meta(
    phrase: str,
    apify_token: str | None = None,
    limit: int = TARGET_POST_COUNT,
    serper_api_key: str | None = None,
    use_cache: bool = True,
) -> tuple[list[DiscoveredPost], str, list[str]]:
    """Discover recent LinkedIn posts using Serper.dev (fast) with Apify SERP fallback."""
    resolved_serper = (SERPER_API_KEY if serper_api_key is None else serper_api_key).strip()
    resolved_apify = (APIFY_API_TOKEN if apify_token is None else apify_token).strip()
    warnings: list[str] = []

    if use_cache:
        c_key = build_cache_key({"phrase": phrase.lower(), "limit": limit})
        cached = get_cached_json("serp_posts", c_key)
        if isinstance(cached, dict) and cached.get("posts"):
            posts = [DiscoveredPost(**item) for item in cached["posts"]]
            provider = str(cached.get("provider") or "Cache")
            return posts[:limit], f"{provider} (cached)", warnings

    if not resolved_serper and not resolved_apify:
        raise ValueError(
            "Either SERPER_API_KEY or APIFY_API_TOKEN is required for Live API post discovery."
        )

    serp_pages: list[dict] = []
    provider_used = ""

    if resolved_serper:
        try:
            serp_pages = _search_serper_pages(phrase, resolved_serper)
            provider_used = "Serper.dev"
        except ValueError:
            if not resolved_apify:
                raise
            warnings.append("Serper authentication failed; fell back to Apify Google SERP.")
        except Exception as exc:
            if not resolved_apify:
                raise RuntimeError(f"Serper search failed: {exc}") from exc
            warnings.append(
                f"Serper search failed ({str(exc)[:80]}); fell back to Apify Google SERP."
            )

    if not serp_pages and resolved_apify:
        serp_pages = _search_apify_serp_pages(phrase, resolved_apify)
        provider_used = "Apify SERP"

    posts = parse_serp_pages_to_posts(serp_pages, phrase=phrase, limit=limit)
    if not posts:
        raise RuntimeError(
            f"No public LinkedIn post URLs were found for '{phrase}'. "
            "Try a broader phrase or switch to Supplied Post URLs / Test Dataset mode."
        )

    if use_cache:
        c_key = build_cache_key({"phrase": phrase.lower(), "limit": limit})
        set_cached_json(
            "serp_posts",
            c_key,
            {
                "provider": provider_used,
                "posts": [p.model_dump(mode="json") for p in posts],
            },
        )

    return posts, provider_used, warnings


def discover_posts_live(
    phrase: str,
    apify_token: str | None = None,
    limit: int = TARGET_POST_COUNT,
    serper_api_key: str | None = None,
    use_cache: bool = True,
) -> list[DiscoveredPost]:
    """Discover recent LinkedIn posts without touching LinkedIn's auth wall."""
    posts, _, _ = discover_posts_live_with_meta(
        phrase=phrase,
        apify_token=apify_token,
        limit=limit,
        serper_api_key=serper_api_key,
        use_cache=use_cache,
    )
    return posts


def load_supplied_posts(post_urls: list[str], phrase: str) -> list[DiscoveredPost]:
    """Build DiscoveredPost records from user-supplied LinkedIn post URLs."""
    posts: list[DiscoveredPost] = []
    seen: set[str] = set()
    for raw_url in post_urls:
        clean_url = normalize_linkedin_url(raw_url)
        if not clean_url or clean_url in seen:
            continue
        if not _is_linkedin_post_url(clean_url):
            continue
        seen.add(clean_url)
        decoded_dt = decode_linkedin_post_timestamp(clean_url)
        posts.append(
            DiscoveredPost(
                post_id=extract_activity_id(clean_url, len(posts) + 1),
                post_url=clean_url,
                author_name="Supplied Post Author",
                published_date=decoded_dt.strftime("%Y-%m-%d") if decoded_dt else "User Supplied",
                snippet=f"User-supplied LinkedIn post for phrase: '{phrase}'",
                source_mode=DataSourceMode.SUPPLIED_URLS,
            )
        )
    if not posts:
        raise ValueError(
            "Please supply at least one valid LinkedIn post URL "
            "(containing linkedin.com/posts/, linkedin.com/feed/update/, or linkedin.com/pulse/)."
        )
    return posts[:TARGET_POST_COUNT]


def load_sample_posts(limit: int = TARGET_POST_COUNT) -> list[DiscoveredPost]:
    """Load the clearly labelled reference test dataset."""
    raw = json.loads(SAMPLE_DATASET_PATH.read_text(encoding="utf-8"))
    posts = [
        DiscoveredPost(**item, source_mode=DataSourceMode.TEST_DATASET)
        for item in raw.get("posts", [])[:limit]
    ]
    return posts
