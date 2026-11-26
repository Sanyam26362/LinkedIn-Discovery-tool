from concurrent.futures import ThreadPoolExecutor
import json
import re
from google import genai
from google.genai import types
import httpx
import numpy as np
from src.cache import build_cache_key, get_cached_json, set_cached_json
from src.config import (
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_MS,
    SAMPLE_DATASET_PATH,
    SERPER_API_KEY,
    SERPER_GL,
    TARGET_PERSONA_PATH,
)
from src.schemas import RankedInfluencer, SimilarProfile, normalize_linkedin_url
from src.stage5_ranking import _embed_all_same_model

_SERPER_ENDPOINT = "https://google.serper.dev/search"
_NOT_LISTED = "not publicly listed"

_INDICATOR_QUERY_TERMS: dict[str, str] = {
    "School/Education Consultant": '("Education Consultant" OR "School Consultant" OR "School Advisor")',
    "Former Principal/Director": '("Former Principal" OR "Academic Director" OR "School Principal")',
    "School Owner/Trustee": '("School Owner" OR "Managing Trustee" OR "School Founder")',
    "Edu-Entrepreneur": '("EdTech Founder" OR "Education Founder" OR "Edupreneur")',
    "Multi-School Network Professional": '("School Network" OR "Director of Schools" OR "Head of School")',
    "Decision-Maker Connector": '("EdTech Sales" OR "K12 Sales" OR "School Partnerships")',
}

_PRIORITY_ROLE_KEYWORDS = (
    "principal",
    "director",
    "consultant",
    "advisor",
    "trustee",
    "founder",
    "owner",
    "edtech",
    "sales",
    "partnership",
    "curriculum",
    "k12",
    "k-12",
    "school",
    "education",
    "dean",
    "head",
)


def _extract_role_fragments(raw_role: str) -> list[str]:
    """Split verbose LinkedIn role strings into concise, searchable role fragments."""
    cleaned = re.sub(r"\s+", " ", (raw_role or "")).strip()
    if not cleaned or cleaned.lower() == _NOT_LISTED:
        return []

    parts = [p.strip(" -–·•,") for p in re.split(r"[|/·@]| - | – ", cleaned)]
    candidates: list[str] = []
    for part in parts:
        words = part.split()
        if not words:
            continue
        fragment = " ".join(words[:5]) if len(words) > 5 else part
        if len(fragment) >= 4 and fragment.lower() != _NOT_LISTED:
            candidates.append(fragment)

    # Prefer domain-rich role fragments first (e.g. "EdTech Sales" over "Founder")
    candidates.sort(
        key=lambda frag: (
            any(kw in frag.lower() for kw in _PRIORITY_ROLE_KEYWORDS),
            len(frag.split()),
        ),
        reverse=True,
    )
    return list(dict.fromkeys(candidates))


def _build_domain_clause(phrase: str) -> str:
    """Build concise K12 domain search filter from user phrase."""
    low = phrase.lower()
    if any(tok in low for tok in ("k12", "k-12", "school", "edtech", "education")):
        base = '("K12" OR "K-12" OR "School" OR "EdTech")'
        if "sales" in low or "b2b" in low:
            return f'{base} ("Sales" OR "Partnerships" OR "B2B" OR "Consultant")'
        return base
    return '("K12" OR "K-12" OR "School" OR "Education")'


def build_lookalike_queries(
    seed_influencers: list[RankedInfluencer],
    phrase: str,
    max_queries: int = 4,
) -> list[tuple[str, RankedInfluencer]]:
    """Build up to `max_queries` targeted `site:linkedin.com/in` queries from top commenters."""
    if not seed_influencers:
        return []

    domain_clause = _build_domain_clause(phrase)
    queries: list[tuple[str, RankedInfluencer]] = []
    seen_q: set[str] = set()

    def _add(q: str, seed: RankedInfluencer) -> None:
        if q not in seen_q and len(queries) < max_queries:
            seen_q.add(q)
            queries.append((q, seed))

    for seed in seed_influencers[:3]:
        fragments = _extract_role_fragments(seed.current_role)
        if fragments:
            _add(f'site:linkedin.com/in "{fragments[0]}" {domain_clause}', seed)

        for ind in seed.school_ecosystem_indicators:
            mapped = _INDICATOR_QUERY_TERMS.get(ind)
            if mapped:
                _add(f"site:linkedin.com/in {mapped} {domain_clause}", seed)
                break

        if len(queries) >= max_queries:
            break

    # Fallback broad domain query if seeds had only "Not publicly listed" metadata
    if not queries:
        lead_seed = seed_influencers[0]
        _add(f'site:linkedin.com/in ("Education Consultant" OR "Former Principal" OR "EdTech Sales") {domain_clause}', lead_seed)
        _add(f'site:linkedin.com/in ("School Owner" OR "Academic Director") {domain_clause}', lead_seed)

    return queries[:max_queries]


def _search_serper_profiles(queries: list[str], serper_key: str) -> list[dict]:
    """Run public LinkedIn `/in/` profile queries concurrently via Serper.dev."""
    headers = {"X-API-KEY": serper_key.strip(), "Content-Type": "application/json"}
    gl = SERPER_GL.strip().lower()

    with httpx.Client(headers=headers, timeout=15.0) as client:
        def _fetch_one(q: str) -> dict:
            body: dict = {"q": q, "num": 10}
            if gl:
                body["gl"] = gl
            resp = client.post(_SERPER_ENDPOINT, json=body)
            if resp.status_code in (401, 403):
                raise ValueError("Serper API authentication failed. Verify your SERPER_API_KEY.")
            if resp.status_code >= 400:
                raise RuntimeError(f"Serper HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()

        with ThreadPoolExecutor(max_workers=max(1, len(queries))) as pool:
            return list(pool.map(_fetch_one, queries))


def _parse_profile_title(raw_title: str) -> tuple[str, str]:
    """Extract (name, headline) from a LinkedIn `/in/` SERP title."""
    cleaned = raw_title.replace(" | LinkedIn", "").replace(" - LinkedIn", "").strip()
    cleaned = re.sub(r"\s+\.\.\.$", "", cleaned).strip()
    for sep in (" - ", " – ", " | "):
        if sep in cleaned:
            name_part, headline_part = cleaned.split(sep, 1)
            return name_part.strip()[:70], headline_part.strip()[:160]
    return cleaned[:70] or "LinkedIn Member", ""


def _split_role_and_org(headline: str) -> tuple[str, str]:
    """Extract structured (current_role, organization) from a profile headline when explicit."""
    if not headline:
        return "Not publicly listed", "Not publicly listed"
    primary = headline.split("|", 1)[0].strip()
    for sep in (" @ ", " at "):
        if sep in primary:
            role_part, org_part = primary.split(sep, 1)
            return (
                role_part.strip() or "Not publicly listed",
                org_part.strip() or "Not publicly listed",
            )
    return primary or "Not publicly listed", "Not publicly listed"


def _parse_profile_serp_candidates(
    pages_with_seeds: list[tuple[dict, RankedInfluencer]],
    exclude_urls: set[str],
) -> list[dict]:
    """Parse deduplicated LinkedIn `/in/` profile items from Serper SERP responses."""
    candidates: list[dict] = []
    seen_urls: set[str] = {normalize_linkedin_url(u) for u in exclude_urls if u}

    for page, seed in pages_with_seeds:
        for item in page.get("organic", []):
            raw_link = str(item.get("link") or item.get("url") or "").strip()
            low_link = raw_link.lower()
            if "linkedin.com/in/" not in low_link or "/dir/" in low_link:
                continue

            clean_url = normalize_linkedin_url(raw_link)
            if not clean_url or clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            name, headline = _parse_profile_title(str(item.get("title") or ""))
            if not name:
                continue
            snippet = re.sub(r"\s+", " ", str(item.get("snippet") or "")).strip()[:260]
            role, org = _split_role_and_org(headline)

            candidates.append(
                {
                    "name": name,
                    "profile_url": clean_url,
                    "headline": headline,
                    "current_role": role,
                    "organization": org,
                    "location": "Not publicly listed",
                    "snippet": snippet,
                    "seed": seed,
                }
            )

    return candidates


def _seed_profile_text(seed: RankedInfluencer) -> str:
    parts: list[str] = []
    if seed.current_role and seed.current_role.lower() != _NOT_LISTED:
        parts.append(f"Role: {seed.current_role}")
    if seed.organization and seed.organization.lower() != _NOT_LISTED:
        parts.append(f"Organization: {seed.organization}")
    if seed.match_explanation:
        parts.append(f"Profile Summary: {seed.match_explanation}")
    return ". ".join(parts) or f"Profile: {seed.name}"


def _calibrated_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    raw_cos = float(np.dot(vec_a, vec_b))
    calibrated = float(np.clip((raw_cos - 0.62) / (0.88 - 0.62), 0.0, 1.0))
    return round(calibrated * 100.0, 2)


def _rank_candidates_token_overlap(
    candidates: list[dict],
    seed_influencers: list[RankedInfluencer],
) -> list[SimilarProfile]:
    """Zero-API lexical fallback ranking when Gemini embeddings are unavailable."""
    scored: list[SimilarProfile] = []
    for cand in candidates:
        cand_tokens = set(re.findall(r"[a-z0-9]{3,}", f"{cand['headline']} {cand['snippet']}".lower()))
        best_seed = cand["seed"]
        best_overlap = 0.0
        for seed in seed_influencers:
            seed_tokens = set(
                re.findall(
                    r"[a-z0-9]{3,}",
                    f"{seed.current_role} {seed.organization} {seed.match_explanation}".lower(),
                )
            )
            if not seed_tokens or not cand_tokens:
                continue
            ratio = len(cand_tokens & seed_tokens) / max(1, len(seed_tokens | cand_tokens))
            if ratio > best_overlap:
                best_overlap = ratio
                best_seed = seed

        sim_pct = round(min(92.0, max(35.0, best_overlap * 220.0)), 2)
        seed_role_label = best_seed.current_role if best_seed.current_role.lower() != _NOT_LISTED else "K12 ecosystem peer"
        scored.append(
            SimilarProfile(
                rank=0,
                name=cand["name"],
                profile_url=cand["profile_url"],
                headline=cand["headline"] or cand["current_role"],
                current_role=cand["current_role"],
                organization=cand["organization"],
                location=cand["location"],
                snippet=cand["snippet"],
                matched_seed_name=best_seed.name,
                matched_seed_url=best_seed.profile_url,
                matched_seed_role=best_seed.current_role,
                similarity_score=sim_pct,
                seed_similarity=sim_pct,
                persona_similarity=sim_pct,
                match_reason=f"Similar LinkedIn headline & domain keywords to {best_seed.name} ({seed_role_label}).",
            )
        )
    scored.sort(key=lambda x: x.similarity_score, reverse=True)
    return scored


def load_sample_similar_profiles(limit: int = 12) -> list[SimilarProfile]:
    """Load sample similar profiles from `data/sample_dataset.json` when available."""
    raw = json.loads(SAMPLE_DATASET_PATH.read_text(encoding="utf-8"))
    items = [SimilarProfile(**item) for item in raw.get("similar_profiles", [])[:limit]]
    for idx, item in enumerate(items, start=1):
        item.rank = idx
    return items


def discover_similar_profiles(
    phrase: str,
    seed_influencers: list[RankedInfluencer],
    exclude_urls: set[str] | None = None,
    serper_api_key: str | None = None,
    gemini_api_key: str | None = None,
    use_cache: bool = True,
    limit: int = 12,
) -> tuple[list[SimilarProfile], list[str]]:
    """Discover and semantically rank LinkedIn profiles similar to top commenters."""
    if not seed_influencers:
        return [], []

    resolved_serper = (SERPER_API_KEY if serper_api_key is None else serper_api_key).strip()
    if not resolved_serper:
        return [], []

    resolved_gemini = (GEMINI_API_KEY if gemini_api_key is None else gemini_api_key).strip()
    warnings: list[str] = []

    relevant_seeds = [
        inf for inf in seed_influencers if inf.final_relevance_score >= 45.0
    ] or seed_influencers[:3]
    top_seeds = relevant_seeds[:3]

    query_pairs = build_lookalike_queries(top_seeds, phrase=phrase, max_queries=4)
    if not query_pairs:
        return [], []

    gl = SERPER_GL.strip().lower()
    queries = [q for q, _ in query_pairs]
    c_key = build_cache_key(
        {
            "type": "similar_profiles_v1",
            "queries": queries,
            "gl": gl,
        }
    )

    pages: list[dict] | None = get_cached_json("serp_similar_profiles", c_key) if use_cache else None
    if not isinstance(pages, list):
        try:
            pages = _search_serper_profiles(queries, resolved_serper)
            if use_cache and pages:
                set_cached_json("serp_similar_profiles", c_key, pages)
        except Exception as exc:
            warnings.append(f"Similar profile search skipped ({str(exc)[:80]}).")
            return [], warnings

    all_excludes = set(exclude_urls or set()) | {inf.profile_url for inf in seed_influencers}
    candidates = _parse_profile_serp_candidates(list(zip(pages, [s for _, s in query_pairs])), all_excludes)
    if not candidates:
        return [], warnings

    if not resolved_gemini:
        ranked = _rank_candidates_token_overlap(candidates, top_seeds)[:limit]
        for idx, item in enumerate(ranked, start=1):
            item.rank = idx
        return ranked, warnings

    try:
        target_persona_text = TARGET_PERSONA_PATH.read_text(encoding="utf-8").strip()
        seed_texts = [_seed_profile_text(s) for s in top_seeds]
        candidate_texts = [
            f"Headline: {c['headline']}. Bio: {c['snippet']}".strip()
            for c in candidates
        ]
        client = genai.Client(
            api_key=resolved_gemini,
            http_options=types.HttpOptions(
                timeout=GEMINI_REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        vectors = _embed_all_same_model(
            [target_persona_text] + seed_texts + candidate_texts,
            client=client,
            use_cache=use_cache,
        )
        persona_vec = vectors[0]
        seed_vecs = vectors[1 : 1 + len(top_seeds)]
        cand_vecs = vectors[1 + len(top_seeds) :]

        scored: list[SimilarProfile] = []
        for cand, cand_vec in zip(candidates, cand_vecs):
            seed_sims = [_calibrated_similarity(cand_vec, s_vec) for s_vec in seed_vecs]
            best_idx = int(np.argmax(seed_sims))
            best_seed = top_seeds[best_idx]
            seed_sim = seed_sims[best_idx]
            persona_sim = _calibrated_similarity(cand_vec, persona_vec)
            overall = round((0.65 * seed_sim) + (0.35 * persona_sim), 2)

            seed_role_label = (
                best_seed.current_role
                if best_seed.current_role.lower() != _NOT_LISTED
                else "K12 ecosystem contact"
            )
            scored.append(
                SimilarProfile(
                    rank=0,
                    name=cand["name"],
                    profile_url=cand["profile_url"],
                    headline=cand["headline"] or cand["current_role"],
                    current_role=cand["current_role"],
                    organization=cand["organization"],
                    location=cand["location"],
                    snippet=cand["snippet"],
                    matched_seed_name=best_seed.name,
                    matched_seed_url=best_seed.profile_url,
                    matched_seed_role=best_seed.current_role,
                    similarity_score=overall,
                    seed_similarity=seed_sim,
                    persona_similarity=persona_sim,
                    match_reason=(
                        f"Semantic role & K12 alignment with {best_seed.name} "
                        f"({seed_role_label}) — {seed_sim:.0f}% seed / {persona_sim:.0f}% persona match."
                    ),
                )
            )

        scored.sort(
            key=lambda x: (x.similarity_score, x.seed_similarity, x.persona_similarity),
            reverse=True,
        )
        final_list = scored[:limit]
    except Exception:
        final_list = _rank_candidates_token_overlap(candidates, top_seeds)[:limit]

    for idx, item in enumerate(final_list, start=1):
        item.rank = idx
    return final_list, warnings
