from concurrent.futures import ThreadPoolExecutor
import re
import time
import numpy as np
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from src.cache import build_cache_key, get_cached_json, set_cached_json
from src.config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_FALLBACK_MODELS,
    EMBEDDING_MODEL,
    ENGAGEMENT_BONUS_PER_EXTRA_POST,
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_MS,
    MAX_ENGAGEMENT_BONUS,
    TARGET_PERSONA_PATH,
    WEIGHT_EMBEDDING,
    WEIGHT_LLM,
)
from src.schemas import DeduplicatedCommenter, ProfileAnalysis, RankedInfluencer


def _l2_normalize(vec: list[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    return arr / norm if norm > 0 else arr


def _candidate_embedding_models() -> list[str]:
    ordered = [EMBEDDING_MODEL] if EMBEDDING_MODEL else []
    for m in EMBEDDING_FALLBACK_MODELS:
        if m not in ordered:
            ordered.append(m)
    return ordered


def _is_fatal_auth_error(exc: Exception) -> bool:
    if isinstance(exc, genai_errors.APIError):
        msg = str(exc).lower()
        if exc.code in (401, 403):
            return True
        if exc.code == 400 and ("api key" in msg or "api_key_invalid" in msg):
            return True
    return False


def _parse_retry_wait_secs(exc: Exception) -> float | None:
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), flags=re.IGNORECASE)
    if match:
        wait = float(match.group(1))
        if 0.0 < wait <= 12.0:
            return wait + 0.35
    return None


def _embed_batch_for_single_model(
    texts: list[str],
    client: genai.Client,
    model_name: str,
) -> list[np.ndarray]:
    """Embed texts using one specific model, safely handling single-item fallback if needed."""
    if not texts:
        return []

    cfg = types.EmbedContentConfig(
        task_type="SEMANTIC_SIMILARITY",
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    all_vecs: list[np.ndarray] = []

    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        chunk = texts[start : start + EMBEDDING_BATCH_SIZE]
        for attempt in range(2):
            try:
                response = client.models.embed_content(
                    model=model_name,
                    contents=chunk,
                    config=cfg,
                )
                embs = response.embeddings or []
                if len(chunk) > 1 and len(embs) == 1:
                    # Models like gemini-embedding-2 treat a list as one multipart document;
                    # embed items individually in parallel so each text gets its own vector.
                    def _embed_one(txt: str) -> np.ndarray:
                        r = client.models.embed_content(model=model_name, contents=txt, config=cfg)
                        return _l2_normalize(r.embeddings[0].values)

                    with ThreadPoolExecutor(max_workers=min(5, len(chunk))) as pool:
                        all_vecs.extend(list(pool.map(_embed_one, chunk)))
                    break

                if len(embs) != len(chunk):
                    raise RuntimeError(
                        f"Embedding model '{model_name}' returned {len(embs)} vectors for {len(chunk)} inputs."
                    )
                all_vecs.extend(_l2_normalize(item.values) for item in embs)
                break
            except Exception as exc:
                if _is_fatal_auth_error(exc):
                    raise ValueError(
                        "Gemini API authentication failed during embedding. Verify GEMINI_API_KEY."
                    ) from exc
                if attempt == 0 and isinstance(exc, genai_errors.APIError) and exc.code == 429:
                    wait_secs = _parse_retry_wait_secs(exc)
                    if wait_secs is not None:
                        time.sleep(wait_secs)
                        continue
                raise

    return all_vecs


def _embed_all_same_model(
    texts: list[str],
    client: genai.Client,
    use_cache: bool,
) -> list[np.ndarray]:
    """Ensure every text (persona + candidates) is embedded in the SAME model vector space."""
    last_exc: Exception | None = None
    for model_name in _candidate_embedding_models():
        vecs_by_idx: dict[int, np.ndarray] = {}
        missing_indices: list[int] = []
        cache_keys: dict[int, str] = {}

        for idx, txt in enumerate(texts):
            ck = build_cache_key({"model": model_name, "dim": EMBEDDING_DIMENSIONS, "text": txt})
            cache_keys[idx] = ck
            if use_cache:
                cached = get_cached_json("embed_vec", ck)
                if isinstance(cached, list) and len(cached) > 0:
                    vecs_by_idx[idx] = _l2_normalize(cached)
                    continue
            missing_indices.append(idx)

        if missing_indices:
            try:
                missing_texts = [texts[i] for i in missing_indices]
                computed = _embed_batch_for_single_model(missing_texts, client, model_name)
                if len(computed) != len(missing_indices):
                    raise RuntimeError(
                        f"Expected {len(missing_indices)} embeddings from {model_name}, got {len(computed)}."
                    )
                for idx, vec in zip(missing_indices, computed):
                    vecs_by_idx[idx] = vec
                    if use_cache:
                        set_cached_json("embed_vec", cache_keys[idx], vec.tolist())
            except ValueError:
                raise
            except Exception as exc:
                last_exc = exc
                continue

        return [vecs_by_idx[i] for i in range(len(texts))]

    raise RuntimeError(f"All Gemini embedding models failed: {last_exc}") from last_exc


def rank_commenters(
    commenters: list[DeduplicatedCommenter],
    analyses: dict[str, ProfileAnalysis],
    gemini_api_key: str | None = None,
    use_cache: bool = True,
) -> list[RankedInfluencer]:
    """Combine dense embedding cosine similarity, LLM contextual score, and multi-post engagement."""
    if not commenters:
        return []

    api_key = (GEMINI_API_KEY if gemini_api_key is None else gemini_api_key).strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for Stage 5 semantic ranking.")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=GEMINI_REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    target_persona_text = TARGET_PERSONA_PATH.read_text(encoding="utf-8").strip()

    candidate_texts: list[str] = []
    for c in commenters:
        analysis = analyses[c.profile_url]
        indicators = ", ".join(ind.value for ind in analysis.school_ecosystem_indicators)
        comments_joined = " | ".join(t.comment_snippet for t in c.commented_posts)
        candidate_texts.append(
            f"Role: {analysis.current_role}. Organization: {analysis.organization}. "
            f"Location: {analysis.location}. Headline: {c.headline}. "
            f"Indicators: {indicators}. Comments: {comments_joined}"
        )

    vectors = _embed_all_same_model(
        [target_persona_text] + candidate_texts,
        client=client,
        use_cache=use_cache,
    )
    if len(vectors) != len(commenters) + 1:
        raise RuntimeError(
            f"Embedding vector count mismatch: expected {len(commenters) + 1}, got {len(vectors)}."
        )

    persona_vec = vectors[0]
    candidate_vecs = vectors[1:]

    scored_items: list[RankedInfluencer] = []
    for commenter, cand_vec in zip(commenters, candidate_vecs):
        analysis = analyses[commenter.profile_url]

        # Cosine similarity on L2-normalized vectors in [-1, 1], clamped to [0, 1] and rescaled to [0, 100]
        raw_cos = float(np.clip(np.dot(persona_vec, cand_vec), 0.0, 1.0))
        embedding_score = round(raw_cos * 100.0, 2)

        extra_posts = max(0, commenter.engagement_count - 1)
        engagement_bonus = min(
            MAX_ENGAGEMENT_BONUS,
            round(extra_posts * ENGAGEMENT_BONUS_PER_EXTRA_POST, 2),
        )

        final_score = min(
            100.0,
            round(
                (WEIGHT_EMBEDDING * embedding_score)
                + (WEIGHT_LLM * analysis.llm_fit_score)
                + engagement_bonus,
                2,
            ),
        )

        scored_items.append(
            RankedInfluencer(
                rank=0,
                name=commenter.name,
                profile_url=commenter.profile_url,
                current_role=analysis.current_role,
                organization=analysis.organization,
                location=analysis.location,
                school_ecosystem_indicators=[
                    ind.value for ind in analysis.school_ecosystem_indicators
                ],
                embedding_similarity=embedding_score,
                llm_fit_score=round(analysis.llm_fit_score, 2),
                engagement_bonus=engagement_bonus,
                final_relevance_score=final_score,
                match_explanation=analysis.match_explanation,
                commented_post_count=commenter.engagement_count,
                commented_posts=commenter.commented_posts,
            )
        )

    scored_items.sort(
        key=lambda x: (
            x.final_relevance_score,
            x.llm_fit_score,
            x.commented_post_count,
            x.embedding_similarity,
        ),
        reverse=True,
    )
    for idx, item in enumerate(scored_items, start=1):
        item.rank = idx

    return scored_items
