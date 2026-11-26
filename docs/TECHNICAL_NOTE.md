# Technical Note — EDXSO LinkedIn School Influencer Discovery Tool

## 1. Architecture Overview
The application executes a low-latency 6-stage pipeline (`src/pipeline.py`) exposed via a Next.js + Starlette web workbench (`api.py`, `frontend/`), a CLI (`src/cli.py`), and a Streamlit prototype (`app.py`):

1. **Stage 1 — Phrase Input (`src/stage1_input.py`)**: Normalizes whitespace and validates the user's topic phrase (default: `"K12 B2B Sales"`).
2. **Stage 2 — Post & Company Discovery (`src/stage2_discovery.py`)**: Discovers 5 recent relevant LinkedIn posts across three compliant modes (`live_api`, `supplied_urls`, `test_dataset`), decoding exact UTC dates (`YYYY-MM-DD`) from `postedAt.date` or LinkedIn's 64-bit Snowflake activity IDs (`activity_id >> 22`). In `live_api` mode, when `APIFY_API_TOKEN` is configured, primary discovery runs cookie-less LinkedIn post search (`harvestapi~linkedin-post-search`, `maxPosts=15`, prioritizing posts with `engagement.comments > 0` and automatically widening `postedLimit` when `< 5` posts match niche brands). Automatic fallbacks run concurrent **Serper.dev** queries (`after:` 90-day and 365-day filters, optional `SERPER_GL` region, `num=10`) and cookie-less `apify~google-search-scraper`.
3. **Stage 3 — Commenter Extraction & Deduplication (`src/stage3_extraction.py`)**: Extracts public commenters via `harvestapi~linkedin-post-comments` (`maxItems` applied per post so one viral thread does not starve others; supports top-level comments and optional `APIFY_SCRAPE_REPLIES=true` replies), normalizes LinkedIn `/in/` profile URLs, warns when any item fails post-matching, and groups engaged posts per person (`DeduplicatedCommenter.commented_posts`).
4. **Stage 4 — AI Analysis (`src/stage4_ai_analysis.py`)**: Concurrently processes uncached commenters (`ThreadPoolExecutor`, `ANALYSIS_BATCH_SIZE=12`, `ANALYSIS_MAX_WORKERS=3`) using a compact integer-indexed Pydantic schema (`CompactBatchAnalysisResponse`) across **Groq** (`openai/gpt-oss-120b` → `openai/gpt-oss-20b` → `qwen/qwen3.8-27b`) with automatic **Gemini Flash-Lite** fallback (`gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`). Preserves resolved batch items even if an omitted-item retry fails.
5. **Stage 5 — Hybrid Semantic Ranking (`src/stage5_ranking.py`)**: Embeds factual candidate evidence (role, organization, location when listed, headline, and comment snippets—excluding Stage 4 indicators and `"Not publicly listed"` boilerplate) in a single batch (`EMBEDDING_BATCH_SIZE=100`) using `gemini-embedding-001` (768-d, L2-normalized) against `data/target_persona.txt`, calibrating raw cosine similarity from `[0.62, 0.88]` to `[0, 100]` alongside LLM fit and multi-post engagement bonus.
6. **Stage 6 — Results & Traceable Export (`src/stage6_export.py`)**: Generates interactive tables/inspector views, runtime breakdown metrics, Excel-safe UTF-8-BOM (`utf-8-sig`) CRM-ready CSV (`commented_post_urls`, `commented_post_authors`, `comment_snippets`), and full nested JSON exports.

---

## 2. Compliant Data Retrieval Approach & Production Path
### Why Direct LinkedIn API Search Is Not Used
LinkedIn does not offer a public REST API endpoint for arbitrary keyword-based post search or reading third-party post comment threads without explicit organization-admin OAuth scopes. Bypassing LinkedIn's authentication wall, cookies, or rate limits violates LinkedIn's User Agreement and project constraints.

### Implemented Compliant Paths
- **`live_api` mode**:
  - *Post Discovery*: Queries public Google search indices via **Serper.dev** (exact + broad queries in parallel), with automatic fallback to Apify's cookie-less `apify~google-search-scraper` actor and `?waitForFinish=60` long-polling (`src/apify_client.py`).
  - *Comment Extraction*: Uses the cookie-less `harvestapi~linkedin-post-comments` Apify actor (`scrapeReplies=false`) to retrieve publicly visible top-level comments per post without any LinkedIn session cookie or login credentials.
- **`supplied_urls` mode**: Accepts up to 5 user-curated LinkedIn post URLs directly and runs Stages 3–6 on those posts.
- **`test_dataset` mode**: Uses the clearly labelled offline fixture (`data/sample_dataset.json`) for deterministic demos without scraping costs.
- **Local TTL Caching (`src/cache.py`)**: Caches SERP results, extracted post comments, per-profile AI extraction, and static persona embeddings (disable anytime via `--no-cache` or the UI toggle).

### Path to Production
In production for EDXSO, Stage 2 and Stage 3 would connect to a licensed enterprise social-intelligence / B2B data provider (or official LinkedIn Community Management / Marketing Developer Partner APIs where authorized for partner-owned pages), paired with webhook-based CRM sync and automated PII retention expiry.

---

## 3. AI/ML Method & Hybrid Ranking Logic
Ranking relies on semantic understanding and LLM reasoning rather than exact keyword matching alone:

1. **Structured LLM Contextual Classification (Weight: 65%)**
   - Evaluates each commenter's headline, optional location hint, and comment snippets against EDXSO's K12 buyer/influencer persona (former principals, school owners, managing trustees, academic directors, multi-school consultants, edu-entrepreneurs, and decision-maker connectors).
   - Compact schema enforcement (`CompactBatchAnalysisResponse`) eliminates URL-echo token overhead and enforces `"Not publicly listed"` when role/org/location is absent.
   - Multi-provider thread-safe routing handles Groq free-tier 8,000 TPM limits (`gpt-oss-120b` → `gpt-oss-20b` → `qwen3.8-27b`) and Gemini `503`/`429` spikes (`gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`), blacklisting daily-exhausted models per run and bisecting malformed batches.

2. **Dense Embedding Semantic Similarity (Weight: 35%)**
   - `gemini-embedding-001` (with `gemini-embedding-2` fallback) encodes `data/target_persona.txt` and factual commenter evidence (excluding LLM indicator tags and placeholder strings) into 768-dimensional vectors using `task_type="SEMANTIC_SIMILARITY"`.
   - Cosine similarity on L2-normalized vectors is calibrated against dense-embedding anisotropy by mapping `[0.62, 0.88]` to `[0, 100]` via clipping, separating strong K12 matches from unrelated roles.

3. **Multi-Post Engagement Bonus (+0 to +10 points)**
   - Commenters engaging across multiple posts receive `+5.0` per additional post (capped at `+10.0`).

$$\text{Final Score} = \min\!\left(100,\; 0.35 \times S_{\text{embedding}} + 0.65 \times S_{\text{LLM}} + \min(10,\; 5 \times (\text{posts} - 1))\right)$$

---

## 4. Schemas & Data Governance
- **Core Schemas (`src/schemas.py`)**: `DiscoveredPost`, `RawComment`, `PostTrace`, `DeduplicatedCommenter`, `ProfileAnalysis`, `RankedInfluencer`, and `PipelineRunResult`.
- **Data Minimization**: Only outreach-relevant public fields are extracted and exported (`ALLOWED_OUTREACH_FIELDS` in `src/config.py`). Private contact scraping is omitted.
- **Retention & Consent**: Exports carry UTC timestamps (`generated_at_utc`) and follow a 30-day retention policy (`DATA_RETENTION_DAYS = 30`).

---

## 5. Known Limitations
1. **Google SERP vs. Logged-In LinkedIn Search**: `live_api` post discovery queries public Google SERP indices (`Serper.dev` / Apify Google Search) with rolling `after:YYYY-MM-DD` date filters rather than LinkedIn's authenticated internal search. Because Google's public index has crawl/indexing lag and lacks your logged-in network graph, follow/connection ranking, and private feed personalization, the 5 discovered posts can differ from what you see inside a logged-in LinkedIn session—especially for brand-specific queries (like `"EDXSO"`). Moreover, the workflow surfaces people who *commented* on public posts rather than standalone LinkedIn People directory matches.
   - **Workaround (`supplied_urls` / Paste URLs mode):** Whenever you see specific live posts inside your LinkedIn search results, paste up to 5 of those post URLs directly into **Paste URLs** mode (`--mode supplied_urls`) to run Stages 3–6 on those exact live discussions.
2. **Comment Extraction Latency Floor**: While Serper (`~1–3s`), Groq (`~2–6s`), and single-batch Gemini embeddings (`~2s`) complete in under ~10 seconds combined, Stage 3 (`harvestapi~linkedin-post-comments`) still queries public LinkedIn comment pages dynamically (`~6–28s` depending on post response time), so cold runs depend mainly on Stage 3 network latency.
3. **Headline-Only Location Availability**: In `short` Apify profile mode (`APIFY_PROFILE_SCRAPER_MODE=short`), location is extracted only when present in the headline/metadata (`Not publicly listed` otherwise).
