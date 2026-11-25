import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUTS_DIR = ROOT_DIR / "outputs"
CACHE_DIR = ROOT_DIR / ".cache"
TARGET_PERSONA_PATH = DATA_DIR / "target_persona.txt"
SAMPLE_DATASET_PATH = DATA_DIR / "sample_dataset.json"

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
APIFY_API_TOKEN: str = os.getenv("APIFY_API_TOKEN", "")
SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

# Fast Groq LLM Models (used first when GROQ_API_KEY is configured)
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODELS: tuple[str, ...] = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
)
GROQ_TIMEOUT_SECS: float = float(os.getenv("GROQ_TIMEOUT_SECS", "30.0"))

# Gemini Models (overridable via .env; used for embeddings and LLM fallback)
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
LLM_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-embedding-001",
    "gemini-embedding-2",
)
EMBEDDING_DIMENSIONS: int = 768
EMBEDDING_BATCH_SIZE: int = 100
GEMINI_REQUEST_TIMEOUT_MS: int = int(os.getenv("GEMINI_REQUEST_TIMEOUT_MS", "45000"))

# Apify Actor IDs (Cookie-less public index fallback & comment retrieval)
APIFY_GOOGLE_SEARCH_ACTOR: str = "apify~google-search-scraper"
APIFY_LINKEDIN_COMMENTS_ACTOR: str = "harvestapi~linkedin-post-comments"
APIFY_PROFILE_SCRAPER_MODE: str = os.getenv("APIFY_PROFILE_SCRAPER_MODE", "short")
APIFY_POLL_TIMEOUT_SECS: int = int(os.getenv("APIFY_POLL_TIMEOUT_SECS", "240"))
APIFY_SCRAPE_REPLIES: bool = (
    os.getenv("APIFY_SCRAPE_REPLIES", "false").strip().lower() in ("1", "true", "yes")
)

# Pipeline Limits & Concurrency
DEFAULT_SEARCH_PHRASE: str = "K12 B2B Sales"
TARGET_POST_COUNT: int = 5
MAX_COMMENTS_PER_POST: int = int(os.getenv("MAX_COMMENTS_PER_POST", "40"))
ANALYSIS_BATCH_SIZE: int = int(os.getenv("ANALYSIS_BATCH_SIZE", "12"))
ANALYSIS_MAX_WORKERS: int = int(os.getenv("ANALYSIS_MAX_WORKERS", "3"))

# Local TTL Cache (accelerates repeat runs & cross-search profile reuse)
ENABLE_CACHE: bool = os.getenv("ENABLE_CACHE", "true").strip().lower() in ("1", "true", "yes")
CACHE_TTL_SECS: int = int(os.getenv("CACHE_TTL_SECS", "3600"))

# Hybrid Ranking Weights
WEIGHT_EMBEDDING: float = 0.35
WEIGHT_LLM: float = 0.65
ENGAGEMENT_BONUS_PER_EXTRA_POST: float = 5.0
MAX_ENGAGEMENT_BONUS: float = 10.0

# Data Minimization & Retention Governance
DATA_RETENTION_DAYS: int = 30
ALLOWED_OUTREACH_FIELDS: tuple[str, ...] = (
    "name",
    "profile_url",
    "current_role",
    "organization",
    "location",
    "school_ecosystem_indicators",
    "commented_posts",
)
