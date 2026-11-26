# EDXSO · LinkedIn School Influencer Discovery Tool

An end-to-end 6-stage AI discovery tool that finds relevant LinkedIn discussions for any topic or brand (e.g., `"K12 B2B Sales"`, `"EDXSO"`), extracts and deduplicates post commenters with full post-to-commenter traceability, enriches profiles via high-speed Groq/Gemini structured analysis, and ranks K12 school-ecosystem decision-makers (principals, school owners/trustees, education consultants, and edu-entrepreneurs).

When you paste specific LinkedIn post URLs (including `lnkd.in/...` short links), it also discovers **Similar Profiles** (lookalike LinkedIn contacts) and displays them side-by-side with the post's commenters.

---

## Key Features

- **Guided 3-Step Web Workbench**:
  1. **Step 1 — Enter Name / Topic**: Type a topic, industry keyword, or company name and press `Enter`.
  2. **Step 2 — Paste URLs (Optional)**: Optionally paste up to 10 LinkedIn post URLs (`linkedin.com/posts/...`, `linkedin.com/feed/update/...`, `linkedin.com/pulse/...`, or `lnkd.in/...` short links) or leave empty, then press `Enter`.
  3. **Step 3 — Results**:
     - **Topic / Name Search (No URLs pasted)**: Shows **Matching Contacts** and **Source Posts** tabs.
     - **Pasted URL Search**: Shows a **2-column view** with **Commenter People** on the left and **Similar Profiles** on the right, plus a **Source Posts** tab.
- **Demo Data Mode**: Loads a built-in offline fixture ([data/sample_dataset.json](file:///d:/projects/LinkedIn%20Discovery/data/sample_dataset.json)) with 5 sample posts and 5 sample contacts and runs live AI ranking without scraping LinkedIn.
- **Hybrid Ranking**: Combines LLM structured profile scoring (65%) with Gemini semantic embeddings against [data/target_persona.txt](file:///d:/projects/LinkedIn%20Discovery/data/target_persona.txt) (35%, with automatic lexical fallback on quota throttling) plus a multi-post engagement bonus (up to +10).
- **CRM-Ready Exports**: Download ranked results as UTF-8 BOM CSV or full nested JSON from the UI or CLI.

---

## Prerequisites

Make sure the following are installed on your machine:

- **Python 3.11+** (`python --version`)
- **Node.js 18+** and **npm** (`node -v`, `npm -v`)
- **Git**

### API Keys Required

| Key | Required? | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Stage 5 semantic embeddings & Stage 4 LLM fallback |
| `APIFY_API_TOKEN` | **Yes** (for live/URL runs) | Stage 3 cookie-less comment extraction & Stage 2 LinkedIn post search |
| `SERPER_API_KEY` | **Recommended** | Fast Stage 2 Google SERP post discovery & Similar Profiles search |
| `GROQ_API_KEY` | **Recommended** | Fast concurrent Stage 4 structured LLM extraction (`openai/gpt-oss-120b`) |

> You can configure keys in `.env` or enter temporary runtime overrides directly in the Web UI under **API Keys**.

---

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Sanyam26362/LinkedIn-Discovery-tool.git
cd "LinkedIn Discovery"
```

### 2. Set Up the Python Backend

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

**macOS / Linux (Bash):**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in your API keys:
```env
GEMINI_API_KEY=your_gemini_api_key_here
APIFY_API_TOKEN=your_apify_api_token_here
SERPER_API_KEY=your_serper_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

### 3. Set Up the Next.js Frontend

```bash
cd frontend
npm install
```

*(Optional)* If your backend runs on a custom host/port instead of `http://127.0.0.1:8000`, copy `frontend/.env.example` to `frontend/.env.local` and update `NEXT_PUBLIC_API_URL`:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env.local
```

**macOS / Linux (Bash):**
```bash
cp .env.example .env.local
```

Return to the project root when finished:
```bash
cd ..
```

---

## Running the Application

### Option 1: Full Web App (Next.js Frontend + Starlette API)

Open **two terminals** at the project root:

**Terminal 1 — Start the Python API server (`http://127.0.0.1:8000`):**

Windows (PowerShell):
```powershell
.\.venv\Scripts\python.exe api.py
```

macOS / Linux:
```bash
.venv/bin/python api.py
```

**Terminal 2 — Start the Next.js frontend (`http://localhost:3000`):**
```bash
cd frontend
npm run dev
```

Open `http://localhost:3000` in your browser (if port 3000 is already in use, Next.js will print the active port, e.g. `http://localhost:3001`).

### Option 2: CLI Mode

Run the 6-stage pipeline directly from the terminal (outputs saved to `outputs/`):

- **Live Search (`live_api`)**:
  ```powershell
  .\.venv\Scripts\python.exe -m src.cli --phrase "K12 B2B Sales" --mode live_api
  ```
- **Pasted Post URLs (`supplied_urls`, includes Similar Profiles)**:
  ```powershell
  .\.venv\Scripts\python.exe -m src.cli --phrase "EDXSO" --mode supplied_urls --urls "https://lnkd.in/p/gmVGnCHM"
  ```
- **Offline Demo Data (`test_dataset`)**:
  ```powershell
  .\.venv\Scripts\python.exe -m src.cli --phrase "K12 B2B Sales" --mode test_dataset
  ```

### Option 3: Streamlit Prototype UI (Single-Process)

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

---

## Testing & Verification

Run the backend test suite:
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Run frontend linting and production build verification:
```bash
cd frontend
npm run lint
npm run build
```

---

## Environment Variables Reference (`.env`)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Stage 5 semantic embeddings & Stage 4 LLM fallback |
| `APIFY_API_TOKEN` | For live / URLs | — | Stage 3 cookie-less comments & Stage 2 LinkedIn post search |
| `SERPER_API_KEY` | Recommended | — | Stage 2 Google SERP discovery & Similar Profiles search |
| `GROQ_API_KEY` | Recommended | — | Fast concurrent Stage 4 structured LLM extraction |
| `TARGET_POST_COUNT` | No | `10` | Maximum posts discovered / processed per search |
| `MAX_COMMENTS_PER_POST` | No | `60` | Maximum comments fetched per post |
| `LINKEDIN_SEARCH_SORT_BY` | No | `relevance` | Apify post search ordering (`relevance` or `date`) |
| `LINKEDIN_SEARCH_POSTED_LIMIT` | No | `3months` | Initial Apify recency window (`week`, `month`, `3months`, `6months`, `year`, `any`) |
| `SERPER_GL` | No | `""` | Optional two-letter Google country code (e.g., `in`, `us`) |
| `CORS_ORIGINS` | No | `*` | Allowed frontend origins for `api.py` |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Primary Groq LLM (auto-rotates on rate limits/errors) |
| `LLM_MODEL` | No | `gemini-3.5-flash-lite` | Primary Gemini LLM fallback |
| `ANALYSIS_BATCH_SIZE` | No | `12` | Profiles per concurrent LLM batch |
| `ANALYSIS_MAX_WORKERS` | No | `3` | Concurrent LLM batch workers |
| `ENABLE_CACHE` | No | `false` | Enables local `.cache/` TTL reuse when `true` (`Fast cache` toggle starts unchecked) |
| `CACHE_TTL_SECS` | No | `3600` | Local cache expiration in seconds |

---

## Troubleshooting

- **"Backend API unreachable" in browser**: Make sure `api.py` is running on `http://127.0.0.1:8000` before running searches in the frontend.
- **PowerShell activation blocked (`Activate.ps1`)**: Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or invoke Python directly via `.\.venv\Scripts\python.exe`.
- **Short LinkedIn share links (`https://lnkd.in/...`)**: Supported directly in Step 2; the backend resolves the redirect to the canonical LinkedIn post URL automatically.
- **Gemini embedding 429 rate limits**: Stage 5 automatically falls back to lexical persona scoring and surfaces a notice so ranked results still complete.

---

## Deploying to Production (Render + Vercel)

Pre-configured with [render.yaml](file:///d:/projects/LinkedIn%20Discovery/render.yaml), [Dockerfile](file:///d:/projects/LinkedIn%20Discovery/Dockerfile), [Procfile](file:///d:/projects/LinkedIn%20Discovery/Procfile), and [frontend/.env.example](file:///d:/projects/LinkedIn%20Discovery/frontend/.env.example):

1. **Backend (Render)**: Create a Web Service using `render.yaml`, set `GEMINI_API_KEY`, `APIFY_API_TOKEN`, `SERPER_API_KEY`, and `GROQ_API_KEY`, and verify `/api/health`.
2. **Frontend (Vercel)**: Import the repo with **Root Directory** set to `frontend`, set `NEXT_PUBLIC_API_URL` to your Render backend URL, and restrict `CORS_ORIGINS` on Render to your Vercel domain.

---

## Responsible Access & Data Governance

- **No auth/CAPTCHA bypass**: Relies on cookie-less Apify public actors, public search indices via Serper, user-supplied post URLs, or the labelled offline fixture.
- **Data minimization & retention**: Retains outreach-relevant public metadata only (`ALLOWED_OUTREACH_FIELDS` in [src/config.py](file:///d:/projects/LinkedIn%20Discovery/src/config.py)) with a 30-day export retention policy (`DATA_RETENTION_DAYS = 30`).

See [docs/TECHNICAL_NOTE.md](file:///d:/projects/LinkedIn%20Discovery/docs/TECHNICAL_NOTE.md) for architecture and scoring methodology details.
