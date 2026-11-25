# LinkedIn School Influencer Discovery Tool (EDXSO AI Intern Assignment)

An end-to-end 6-stage AI pipeline that discovers recent LinkedIn posts for a target search phrase (default: `"K12 B2B Sales"`), extracts and deduplicates commenters with full post-to-commenter traceability, enriches professional context via high-speed Groq/Gemini structured outputs, and ranks K12 school-ecosystem decision-makers via hybrid semantic embeddings + LLM scoring.

## Architecture (6 Stages)
1. **Phrase Input (`src/stage1_input.py`)**: Validates and normalizes the search phrase via Web UI or CLI.
2. **Post Discovery (`src/stage2_discovery.py`)**: Retrieves 5 recent LinkedIn posts via:
   - **`live_api`**: Fast concurrent Google SERP lookup via **Serper.dev** (`~1–3s`) with automatic fallback to cookie-less `apify~google-search-scraper`, decoding exact UTC dates (`YYYY-MM-DD`) from LinkedIn Snowflake activity IDs and ranking recent phrase-matching posts.
   - **`supplied_urls`**: User-supplied LinkedIn post URLs (up to 5).
   - **`test_dataset`**: Clearly labelled offline reference dataset (`data/sample_dataset.json`).
3. **Commenter Extraction & Deduplication (`src/stage3_extraction.py`)**: Fetches public top-level post comments (`scrapeReplies=false`) via cookie-less `harvestapi~linkedin-post-comments`, normalizes LinkedIn URLs, deduplicates commenters across posts, and preserves post-to-commenter traceability (`PostTrace`).
4. **AI Analysis (`src/stage4_ai_analysis.py`)**: Uses concurrent workers (`ThreadPoolExecutor`) with a token-efficient integer-ID schema (`CompactBatchAnalysisResponse`), **Groq** (`openai/gpt-oss-120b` → `openai/gpt-oss-20b` → `qwen/qwen3.8-27b`) and automatic **Gemini Flash-Lite** fallback (`gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`), per-profile TTL caching, and dead-model skipping.
5. **Hybrid Semantic Ranking (`src/stage5_ranking.py`)**: Single-batch (`batch_size=100`) `gemini-embedding-001` 768-d cosine similarity against cached `data/target_persona.txt` embeddings combined with LLM fit and multi-post engagement bonus.
6. **Results & Export (`src/stage6_export.py`, `app.py`, `src/cli.py`)**: Interactive Streamlit dashboard and CLI outputting CRM-ready CSV, full nested JSON exports in `outputs/`, and per-stage execution timings.

## Local Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add GEMINI_API_KEY, APIFY_API_TOKEN, SERPER_API_KEY, and GROQ_API_KEY to .env
```

## Running the Tool

### 1. CLI Mode
- **Live API mode** (Serper/Apify + Groq/Gemini):
  ```powershell
  python -m src.cli --phrase "K12 B2B Sales" --mode live_api
  ```
- **Force cold run bypassing local `.cache/`**:
  ```powershell
  python -m src.cli --phrase "K12 B2B Sales" --mode live_api --no-cache
  ```
- **Supplied URLs mode** (user-provided LinkedIn post URLs + Apify comments + AI):
  ```powershell
  python -m src.cli --phrase "K12 B2B Sales" --mode supplied_urls --urls "https://www.linkedin.com/posts/..."
  ```
- **Labelled Test Dataset mode** (offline post/comment fixture + live AI ranking):
  ```powershell
  python -m src.cli --phrase "K12 B2B Sales" --mode test_dataset
  ```

### 2. Next.js + TypeScript Web App (`frontend/` + `api.py`)
- **Terminal 1 — Start the Python API server (`http://127.0.0.1:8000`)**:
  ```powershell
  python api.py
  ```
- **Terminal 2 — Start the Next.js frontend (`http://localhost:3000`)**:
  ```powershell
  cd frontend
  npm install
  npm run dev
  ```

### 3. Streamlit Web UI (Alternative single-process UI)
```powershell
streamlit run app.py
```

### 4. Running Unit Tests
```powershell
pytest -v
```

## Configuration (`.env`)
| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Stage 5 semantic embeddings & Stage 4 fallback |
| `APIFY_API_TOKEN` | For `live_api` / `supplied_urls` | — | Stage 3 cookie-less comments & Stage 2 SERP fallback |
| `SERPER_API_KEY` | Recommended (`live_api`) | — | Fast (`~1–3s`) concurrent Stage 2 Google SERP discovery |
| `GROQ_API_KEY` | Recommended | — | High-speed concurrent Stage 4 structured profile extraction |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Primary Groq LLM (auto-rotates on 429 TPM / errors) |
| `LLM_MODEL` | No | `gemini-3.5-flash-lite` | Primary Gemini LLM fallback |
| `MAX_COMMENTS_PER_POST` | No | `40` | Max comments fetched per post |
| `ANALYSIS_BATCH_SIZE` | No | `12` | Profiles per concurrent LLM batch |
| `ANALYSIS_MAX_WORKERS` | No | `3` | Concurrent LLM batch workers |
| `ENABLE_CACHE` / `CACHE_TTL_SECS` | No | `true` / `3600` | Local TTL cache for repeat runs & profile reuse |

## Responsible Access & Data Governance
- **No unauthorized scraping or auth/CAPTCHA bypass**: Uses Serper public search / cookie-less Apify public actors (`harvestapi~linkedin-post-comments`, `apify~google-search-scraper`), user-supplied URLs, or the labelled reference dataset.
- **Data minimization**: Only outreach-relevant public metadata (`name`, `profile_url`, `current_role`, `organization`, `location`, `school_ecosystem_indicators`, `commented_posts`) is retained.
- **Retention**: Exports are intended for short-lived outreach triage (`DATA_RETENTION_DAYS = 30`).

See [docs/TECHNICAL_NOTE.md](docs/TECHNICAL_NOTE.md) for the full technical write-up on architecture, ranking methodology, schemas, and production path.
