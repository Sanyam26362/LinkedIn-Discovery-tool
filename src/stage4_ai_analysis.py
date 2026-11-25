from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import threading
import time
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
import httpx
from pydantic import BaseModel, Field
from src.cache import build_cache_key, get_cached_json, set_cached_json
from src.config import (
    ANALYSIS_BATCH_SIZE,
    ANALYSIS_MAX_WORKERS,
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_MS,
    GROQ_API_KEY,
    GROQ_FALLBACK_MODELS,
    GROQ_MODEL,
    GROQ_TIMEOUT_SECS,
    LLM_FALLBACK_MODELS,
    LLM_MODEL,
)
from src.schemas import (
    DeduplicatedCommenter,
    EcosystemIndicator,
    ProfileAnalysis,
    normalize_linkedin_url,
)

_PROMPT_CACHE_VERSION = "v3_compact"
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

_ALLOWED_INDICATORS_LIST = ", ".join(f'"{ind.value}"' for ind in EcosystemIndicator)

SYSTEM_PROMPT = f"""You are an expert B2B K12 education market analyst for EDXSO, an organization building partnerships across K12 schools.
Analyze each LinkedIn commenter's headline, location hint, and comment snippets to assess K12 school-ecosystem fit.

Scoring Calibration:
- High Relevance (75-100) — Core Target Profiles:
  * School and education consultants or academic advisors
  * Former or current Principals, Vice Principals, Academic Directors, Deans, Heads of School
  * School Owners, Founders, Managing Trustees, Society Board Members
  * Education entrepreneurs and K12 school network professionals
  * Professionals working across multiple schools or having direct relationships with school decision-makers
- Moderate Relevance (45-74) — Adjacent K12 Ecosystem Connectors:
  * K12 EdTech partnership leads, curriculum/institutional account managers, school finance or admissions outreach professionals working with K12 schools.
- Low Relevance (0-35) — Off-Target:
  * Generic B2B SaaS, banking, HR, supply-chain, telecom recruiters, higher-ed only, or profiles lacking school-ecosystem evidence.

Allowed `inds` values (choose ONLY 1-2 exact strings from this list):
[{_ALLOWED_INDICATORS_LIST}]

Rules:
- Return exactly one result per input profile, preserving the exact 1-based integer `id`.
- Extract role, org, and loc strictly from the provided text. Return empty string "" when not stated (never invent facts).
- Select ONLY the 1 to 2 most accurate `inds` from the exact allowed strings above (never invent new labels or list all enums). Use "General / Non-K12 Specific" only when score < 40.
- Keep `why` to <= 20 words citing concrete evidence from headline or comments."""


class _AuthConfigError(ValueError):
    """Fatal API authentication failure that must not trigger model fallback."""


class CompactProfileAnalysisItem(BaseModel):
    """Token-efficient structured output item keyed by short integer batch index."""

    id: int = Field(..., description="Exact 1-based profile index from the input batch")
    role: str = Field(default="", description="Current role/title, or '' if unstated")
    org: str = Field(default="", description="Current organization/school, or '' if unstated")
    loc: str = Field(default="", description="City/state/country, or '' if unstated")
    inds: list[str] = Field(
        default_factory=list,
        description="1 to 2 exact strings from the allowed EDXSO indicator list",
    )
    score: float = Field(..., ge=0.0, le=100.0, description="0-100 relevance score")
    why: str = Field(..., description="Concise <=20-word evidence-based explanation")


class CompactBatchAnalysisResponse(BaseModel):
    results: list[CompactProfileAnalysisItem]


_COMPACT_SCHEMA_DICT = CompactBatchAnalysisResponse.model_json_schema()
_IND_BY_LOWER = {ind.value.lower(): ind for ind in EcosystemIndicator}


def _clean_text_field(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned or cleaned.lower() in {"none", "null", "n/a", "na", "unknown", "not publicly listed"}:
        return "Not publicly listed"
    return cleaned


def _coerce_indicator(raw: EcosystemIndicator | str) -> EcosystemIndicator | None:
    if isinstance(raw, EcosystemIndicator):
        return raw
    txt = str(raw or "").strip()
    if not txt:
        return None
    low = txt.lower()
    if low in _IND_BY_LOWER:
        return _IND_BY_LOWER[low]
    if "principal" in low or "director" in low or "head" in low or "dean" in low:
        return EcosystemIndicator.FORMER_PRINCIPAL_DIRECTOR
    if "owner" in low or "trustee" in low or "chairman" in low or "board" in low:
        return EcosystemIndicator.OWNER_TRUSTEE
    if "consultant" in low or "advisor" in low:
        return EcosystemIndicator.CONSULTANT_ADVISOR
    if "entrepreneur" in low or "founder" in low:
        return EcosystemIndicator.EDU_ENTREPRENEUR
    if "multi" in low or "network" in low or "chain" in low:
        return EcosystemIndicator.MULTI_SCHOOL_NETWORK
    if "connector" in low or "sales" in low or "finance" in low or "k12" in low or "k-12" in low or "school" in low:
        return EcosystemIndicator.DECISION_MAKER_CONNECTOR
    if "non-k12" in low or "general" in low:
        return EcosystemIndicator.NOT_APPLICABLE
    return None


def _normalize_indicators(
    raw_inds: list[EcosystemIndicator] | list[str],
    score: float,
) -> list[EcosystemIndicator]:
    coerced = [ind for item in (raw_inds or []) if (ind := _coerce_indicator(item)) is not None]
    deduped = list(dict.fromkeys(coerced))
    if not deduped:
        if score >= 45.0:
            return [EcosystemIndicator.DECISION_MAKER_CONNECTOR]
        return [EcosystemIndicator.NOT_APPLICABLE]
    if score >= 45.0 and len(deduped) > 1:
        filtered = [ind for ind in deduped if ind != EcosystemIndicator.NOT_APPLICABLE]
        if filtered:
            deduped = filtered
    return deduped[:2]


def _hydrate_analysis(
    role: str | None,
    org: str | None,
    loc: str | None,
    inds: list[EcosystemIndicator] | list[str],
    score: float,
    why: str | None,
) -> ProfileAnalysis:
    clamped_score = min(100.0, max(0.0, float(score)))
    return ProfileAnalysis(
        current_role=_clean_text_field(role),
        organization=_clean_text_field(org),
        location=_clean_text_field(loc),
        school_ecosystem_indicators=_normalize_indicators(inds, clamped_score),
        llm_fit_score=clamped_score,
        match_explanation=(why or "").strip() or "Assessed from LinkedIn headline and comment context.",
    )


def _is_fatal_gemini_auth(exc: Exception) -> bool:
    if isinstance(exc, genai_errors.APIError):
        msg = str(exc).lower()
        if exc.code in (401, 403):
            return True
        if exc.code == 400 and ("api key" in msg or "api_key_invalid" in msg):
            return True
    return False


def _is_permanent_model_unavailable(provider: str, exc: Exception) -> bool:
    """Detect quota exhaustion (RPD=20) or missing models so we skip retrying them."""
    msg = str(exc).lower()
    if provider == "gemini" and isinstance(exc, genai_errors.APIError):
        if exc.code == 404:
            return True
        if exc.code == 429 and (
            "perday" in msg or "free_tier_requests" in msg or "per day" in msg or "limit: 0" in msg
        ):
            return True
    if "not_found" in msg or "model_not_found" in msg or "does not exist" in msg or "decommissioned" in msg:
        return True
    return False


def _is_transient_server_error(provider: str, exc: Exception) -> bool:
    msg = str(exc).lower()
    if "503" in msg or "504" in msg or "unavailable" in msg or "deadline" in msg or "timed out" in msg:
        return True
    if provider == "gemini" and isinstance(exc, genai_errors.APIError) and exc.code in (500, 502, 503, 504):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    return False


def _ordered_models(primary: str | None, defaults: tuple[str, ...]) -> list[str]:
    ordered = [primary.strip()] if primary and primary.strip() else []
    for m in defaults:
        if m not in ordered:
            ordered.append(m)
    return ordered


def _build_batch_prompt(batch: list[DeduplicatedCommenter]) -> str:
    lines: list[str] = []
    for idx, c in enumerate(batch, start=1):
        comments_summary = " | ".join(
            f"[{t.post_author}]: {t.comment_snippet[:120]}" for t in c.commented_posts
        )
        lines.append(
            f"[{idx}] Name: {c.name} | HL: {c.headline or 'None'} | "
            f"Loc: {c.location_hint or 'None'} | Cmt: {comments_summary}"
        )
    return "Analyze these LinkedIn commenters:\n" + "\n".join(lines)


def _fallback_analysis(commenter: DeduplicatedCommenter, reason: str) -> ProfileAnalysis:
    return ProfileAnalysis(
        current_role=commenter.headline or "Not publicly listed",
        organization="Not publicly listed",
        location=commenter.location_hint or "Not publicly listed",
        school_ecosystem_indicators=[EcosystemIndicator.NOT_APPLICABLE],
        llm_fit_score=25.0,
        match_explanation=f"Fallback assessment ({reason}).",
    )


def _profile_cache_key(c: DeduplicatedCommenter) -> str:
    return build_cache_key(
        {
            "v": _PROMPT_CACHE_VERSION,
            "url": c.profile_url,
            "hl": c.headline,
            "loc": c.location_hint,
            "cmts": [t.comment_snippet[:120] for t in c.commented_posts],
        }
    )


class _ModelRouter:
    """Thread-safe provider/model router tracking promoted winners and exhausted models."""

    def __init__(self, candidates: list[tuple[str, str]]) -> None:
        self._lock = threading.Lock()
        self._queue = list(candidates)
        self._dead: set[tuple[str, str]] = set()
        self.initial_candidate = candidates[0]

    def snapshot(self) -> list[tuple[str, str]]:
        with self._lock:
            return [c for c in self._queue if c not in self._dead]

    def mark_success(self, candidate: tuple[str, str]) -> None:
        with self._lock:
            if candidate in self._queue and self._queue[0] != candidate:
                self._queue.remove(candidate)
                self._queue.insert(0, candidate)

    def mark_dead(self, candidate: tuple[str, str]) -> None:
        with self._lock:
            self._dead.add(candidate)


def _extract_by_url_from_parsed(
    parsed_obj: object,
    batch: list[DeduplicatedCommenter],
) -> dict[str, ProfileAnalysis]:
    """Support both compact integer-id items and legacy profile_url items cleanly."""
    results = getattr(parsed_obj, "results", []) or []
    by_url: dict[str, ProfileAnalysis] = {}

    for item in results:
        if hasattr(item, "id"):
            idx = int(item.id) - 1
            if 0 <= idx < len(batch):
                target_url = batch[idx].profile_url
                by_url[target_url] = _hydrate_analysis(
                    role=item.role,
                    org=item.org,
                    loc=item.loc,
                    inds=item.inds,
                    score=item.score,
                    why=item.why,
                )
        elif hasattr(item, "profile_url"):
            norm_url = normalize_linkedin_url(item.profile_url)
            by_url[norm_url] = _hydrate_analysis(
                role=item.current_role,
                org=item.organization,
                loc=item.location,
                inds=item.school_ecosystem_indicators,
                score=item.llm_fit_score,
                why=item.match_explanation,
            )
    return by_url


def _call_groq_model(
    model_name: str,
    prompt: str,
    groq_client: httpx.Client,
    batch: list[DeduplicatedCommenter],
) -> dict[str, ProfileAnalysis]:
    body: dict = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "profile_batch", "schema": _COMPACT_SCHEMA_DICT},
        },
    }
    if "gpt-oss" in model_name:
        body["reasoning_effort"] = "low"
    elif "qwen" in model_name:
        body["reasoning_effort"] = "none"

    resp = groq_client.post(_GROQ_CHAT_URL, json=body)
    if resp.status_code in (401, 403):
        raise _AuthConfigError("Groq API authentication failed. Verify your GROQ_API_KEY.")
    if resp.status_code == 400 and "json_schema" in resp.text:
        # Fallback for models expecting json_object rather than strict json_schema
        body["response_format"] = {"type": "json_object"}
        resp = groq_client.post(_GROQ_CHAT_URL, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq HTTP {resp.status_code} ({model_name}): {resp.text[:240]}")

    content = resp.json()["choices"][0]["message"]["content"]
    parsed = CompactBatchAnalysisResponse.model_validate_json(content)
    return _extract_by_url_from_parsed(parsed, batch)


def _call_gemini_model(
    model_name: str,
    prompt: str,
    gemini_client: genai.Client,
    batch: list[DeduplicatedCommenter],
) -> dict[str, ProfileAnalysis]:
    response = gemini_client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=CompactBatchAnalysisResponse,
        ),
    )
    parsed = (
        response.parsed
        if response.parsed is not None
        else CompactBatchAnalysisResponse.model_validate_json(response.text)
    )
    return _extract_by_url_from_parsed(parsed, batch)


def _call_model_for_batch(
    batch: list[DeduplicatedCommenter],
    router: _ModelRouter,
    gemini_client: genai.Client | None,
    groq_client: httpx.Client | None,
) -> tuple[dict[str, ProfileAnalysis], str]:
    prompt = _build_batch_prompt(batch)
    last_exc: Exception | None = None
    candidates = router.snapshot()
    if not candidates:
        raise RuntimeError("No live LLM models remain in fallback queue.")

    for candidate in candidates:
        provider, model_name = candidate
        for attempt in range(2):
            try:
                if provider == "groq" and groq_client is not None:
                    by_url = _call_groq_model(model_name, prompt, groq_client, batch)
                elif provider == "gemini" and gemini_client is not None:
                    by_url = _call_gemini_model(model_name, prompt, gemini_client, batch)
                else:
                    break
                router.mark_success(candidate)
                return by_url, model_name
            except _AuthConfigError:
                raise
            except Exception as exc:
                if _is_fatal_gemini_auth(exc):
                    raise _AuthConfigError(
                        "Gemini API authentication failed. Verify your GEMINI_API_KEY."
                    ) from exc
                last_exc = exc
                if _is_permanent_model_unavailable(provider, exc):
                    router.mark_dead(candidate)
                    break
                if attempt == 0 and _is_transient_server_error(provider, exc):
                    time.sleep(random.uniform(0.35, 0.85))
                    continue
                # Move immediately to next model on 429 TPM burst or repeated failure
                break

    raise RuntimeError(f"All candidate LLM models failed: {last_exc}") from last_exc


def _analyze_batch_resilient(
    batch: list[DeduplicatedCommenter],
    router: _ModelRouter,
    gemini_client: genai.Client | None,
    groq_client: httpx.Client | None,
) -> tuple[dict[str, ProfileAnalysis], set[str]]:
    """Analyze a batch with missing-item re-query and recursive split on parse errors."""
    try:
        by_url, used_model = _call_model_for_batch(batch, router, gemini_client, groq_client)
        models_used = {used_model}
    except _AuthConfigError:
        raise
    except Exception as exc:
        if len(batch) > 1:
            mid = len(batch) // 2
            left, left_models = _analyze_batch_resilient(batch[:mid], router, gemini_client, groq_client)
            right, right_models = _analyze_batch_resilient(batch[mid:], router, gemini_client, groq_client)
            return {**left, **right}, left_models | right_models
        raise RuntimeError(str(exc)) from exc

    resolved: dict[str, ProfileAnalysis] = {}
    missing: list[DeduplicatedCommenter] = []
    for c in batch:
        if c.profile_url in by_url:
            resolved[c.profile_url] = by_url[c.profile_url]
        else:
            missing.append(c)

    if missing and len(missing) < len(batch):
        try:
            retry_map, retry_model = _call_model_for_batch(missing, router, gemini_client, groq_client)
            if retry_model:
                models_used.add(retry_model)
        except _AuthConfigError:
            raise
        except Exception:
            retry_map = {}
        for c in missing:
            resolved[c.profile_url] = retry_map.get(c.profile_url) or _fallback_analysis(
                c, "omitted in model response"
            )
    elif missing:
        for c in missing:
            resolved[c.profile_url] = _fallback_analysis(c, "omitted in model response")

    return resolved, models_used


def analyze_all_commenters_with_meta(
    commenters: list[DeduplicatedCommenter],
    gemini_api_key: str | None = None,
    groq_api_key: str | None = None,
    use_cache: bool = True,
) -> tuple[dict[str, ProfileAnalysis], str, list[str]]:
    """Analyze deduplicated commenters concurrently across Groq/Gemini and return metadata."""
    if not commenters:
        return {}, "", []

    resolved_groq = (GROQ_API_KEY if groq_api_key is None else groq_api_key).strip()
    resolved_gemini = (GEMINI_API_KEY if gemini_api_key is None else gemini_api_key).strip()

    if not resolved_groq and not resolved_gemini:
        raise ValueError("Either GROQ_API_KEY or GEMINI_API_KEY is required for Stage 4 AI analysis.")

    candidates: list[tuple[str, str]] = []
    if resolved_groq:
        candidates.extend(("groq", m) for m in _ordered_models(GROQ_MODEL, GROQ_FALLBACK_MODELS))
    if resolved_gemini:
        candidates.extend(("gemini", m) for m in _ordered_models(LLM_MODEL, LLM_FALLBACK_MODELS))

    analyses: dict[str, ProfileAnalysis] = {}
    warnings: list[str] = []
    uncached: list[tuple[DeduplicatedCommenter, str]] = []

    for c in commenters:
        ck = _profile_cache_key(c)
        if use_cache:
            cached = get_cached_json("profile_analysis", ck)
            if isinstance(cached, dict):
                try:
                    analyses[c.profile_url] = ProfileAnalysis(**cached)
                    continue
                except Exception:
                    pass
        uncached.append((c, ck))

    if not uncached:
        return analyses, f"{candidates[0][1]} (cached)", warnings

    router = _ModelRouter(candidates)
    gemini_client = (
        genai.Client(
            api_key=resolved_gemini,
            http_options=types.HttpOptions(
                timeout=GEMINI_REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        if resolved_gemini
        else None
    )
    groq_client = (
        httpx.Client(
            headers={"Authorization": f"Bearer {resolved_groq}", "Content-Type": "application/json"},
            timeout=GROQ_TIMEOUT_SECS,
        )
        if resolved_groq
        else None
    )

    batches = [
        uncached[i : i + ANALYSIS_BATCH_SIZE]
        for i in range(0, len(uncached), ANALYSIS_BATCH_SIZE)
    ]
    models_used_ordered: list[str] = []
    succeeded_batches = 0

    try:
        max_workers = max(1, min(ANALYSIS_MAX_WORKERS, len(batches)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(
                    _analyze_batch_resilient,
                    [pair[0] for pair in batch],
                    router,
                    gemini_client,
                    groq_client,
                ): (idx, batch)
                for idx, batch in enumerate(batches)
            }
            for fut in as_completed(future_map):
                batch_idx, batch_pairs = future_map[fut]
                try:
                    batch_result, batch_models = fut.result()
                    analyses.update(batch_result)
                    succeeded_batches += 1
                    for m in sorted(batch_models):
                        if m not in models_used_ordered:
                            models_used_ordered.append(m)
                    if use_cache:
                        for c, ck in batch_pairs:
                            analysis_item = batch_result.get(c.profile_url)
                            if (
                                analysis_item is not None
                                and not analysis_item.match_explanation.startswith("Fallback assessment")
                            ):
                                set_cached_json(
                                    "profile_analysis",
                                    ck,
                                    analysis_item.model_dump(mode="json"),
                                )
                except _AuthConfigError:
                    raise
                except Exception as exc:
                    warnings.append(
                        f"Batch {batch_idx + 1} used fallback scoring because LLMs failed: {str(exc)[:100]}"
                    )
                    for c, _ in batch_pairs:
                        analyses[c.profile_url] = _fallback_analysis(c, str(exc)[:60])

        if succeeded_batches == 0:
            raise RuntimeError(
                f"Stage 4 AI analysis failed across all candidate models: {'; '.join(warnings)}"
            )
    finally:
        if groq_client is not None:
            groq_client.close()

    model_summary = ", ".join(models_used_ordered) if models_used_ordered else candidates[0][1]
    primary_model = candidates[0][1]
    if models_used_ordered and primary_model not in models_used_ordered:
        warnings.append(
            f"Primary model '{primary_model}' was unavailable/throttled; automatically used '{model_summary}'."
        )

    return analyses, model_summary, warnings


def analyze_all_commenters(
    commenters: list[DeduplicatedCommenter],
    gemini_api_key: str | None = None,
    groq_api_key: str | None = None,
    use_cache: bool = True,
) -> dict[str, ProfileAnalysis]:
    """Analyze deduplicated commenters concurrently with Groq/Gemini fallback."""
    analyses, _, _ = analyze_all_commenters_with_meta(
        commenters=commenters,
        gemini_api_key=gemini_api_key,
        groq_api_key=groq_api_key,
        use_cache=use_cache,
    )
    return analyses
