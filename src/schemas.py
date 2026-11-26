from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlparse, urlunparse
from pydantic import BaseModel, Field, field_validator


def normalize_linkedin_url(url: str) -> str:
    """Strip tracking query parameters and trailing slashes for reliable deduplication."""
    cleaned = url.strip()
    if not cleaned:
        return cleaned
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    normalized_path = parsed.path.rstrip("/")
    if "/in/" in normalized_path.lower():
        normalized_path = normalized_path.lower()
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), normalized_path, "", "", ""))


class DataSourceMode(str, Enum):
    LIVE_API = "live_api"
    SUPPLIED_URLS = "supplied_urls"
    TEST_DATASET = "test_dataset"


class EcosystemIndicator(str, Enum):
    CONSULTANT_ADVISOR = "School/Education Consultant"
    FORMER_PRINCIPAL_DIRECTOR = "Former Principal/Director"
    OWNER_TRUSTEE = "School Owner/Trustee"
    EDU_ENTREPRENEUR = "Edu-Entrepreneur"
    MULTI_SCHOOL_NETWORK = "Multi-School Network Professional"
    DECISION_MAKER_CONNECTOR = "Decision-Maker Connector"
    NOT_APPLICABLE = "General / Non-K12 Specific"


class DiscoveredPost(BaseModel):
    post_id: str = Field(..., description="Unique identifier or activity ID for the post")
    post_url: str = Field(..., description="Canonical LinkedIn post URL")
    author_name: str = Field(default="Unknown Author")
    published_date: str = Field(default="Recent")
    snippet: str = Field(..., description="Short excerpt containing or relating to the search phrase")
    source_mode: DataSourceMode = Field(default=DataSourceMode.LIVE_API)

    @field_validator("post_url")
    @classmethod
    def clean_post_url(cls, v: str) -> str:
        return normalize_linkedin_url(v)


class RelatedCompany(BaseModel):
    name: str
    company_url: str
    category: str = Field(default="K12 Ecosystem Organization")
    description: str = Field(default="")
    related_contacts: list[str] = Field(default_factory=list)
    source: str = Field(default="LinkedIn Company Index")


class RawComment(BaseModel):
    post_url: str
    commenter_name: str
    profile_url: str
    headline: str = Field(default="")
    comment_text: str = Field(default="")

    @field_validator("post_url", "profile_url")
    @classmethod
    def clean_urls(cls, v: str) -> str:
        return normalize_linkedin_url(v)


class PostTrace(BaseModel):
    post_url: str
    post_author: str
    comment_snippet: str


class DeduplicatedCommenter(BaseModel):
    profile_url: str = Field(..., description="Canonical LinkedIn profile URL (deduplication key)")
    name: str
    headline: str = Field(default="")
    location_hint: str = Field(default="")
    commented_posts: list[PostTrace] = Field(default_factory=list)

    @property
    def engagement_count(self) -> int:
        return len(self.commented_posts)


class ProfileAnalysis(BaseModel):
    """Structured output schema for individual profile analysis."""
    current_role: str = Field(
        default="Not publicly listed",
        description="Current job title extracted from headline/profile",
    )
    organization: str = Field(
        default="Not publicly listed",
        description="Current school, trust, consultancy, or company",
    )
    location: str = Field(
        default="Not publicly listed",
        description="City, state, or country if available; otherwise 'Not publicly listed'",
    )
    school_ecosystem_indicators: list[EcosystemIndicator] = Field(
        default_factory=list,
        description="Matching EDXSO K12 target categories based on professional context",
    )
    llm_fit_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="0-100 relevance score for EDXSO K12 school-network B2B outreach",
    )
    match_explanation: str = Field(
        ...,
        description="Concise 1-2 sentence explanation citing specific profile/comment evidence",
    )


class BatchProfileAnalysisItem(ProfileAnalysis):
    profile_url: str = Field(..., description="Exact profile_url provided in the input batch")


class BatchProfileAnalysisResponse(BaseModel):
    results: list[BatchProfileAnalysisItem]


class RankedInfluencer(BaseModel):
    rank: int
    name: str
    profile_url: str
    current_role: str
    organization: str
    location: str
    school_ecosystem_indicators: list[str]
    embedding_similarity: float = Field(..., ge=0.0, le=100.0)
    llm_fit_score: float = Field(..., ge=0.0, le=100.0)
    engagement_bonus: float = Field(..., ge=0.0, le=10.0)
    final_relevance_score: float = Field(..., ge=0.0, le=100.0)
    match_explanation: str
    commented_post_count: int
    commented_posts: list[PostTrace]


class SimilarProfile(BaseModel):
    rank: int
    name: str
    profile_url: str
    headline: str = Field(default="")
    current_role: str = Field(default="Not publicly listed")
    organization: str = Field(default="Not publicly listed")
    location: str = Field(default="Not publicly listed")
    snippet: str = Field(default="")
    matched_seed_name: str
    matched_seed_url: str
    matched_seed_role: str = Field(default="")
    similarity_score: float = Field(..., ge=0.0, le=100.0)
    seed_similarity: float = Field(default=0.0, ge=0.0, le=100.0)
    persona_similarity: float = Field(default=0.0, ge=0.0, le=100.0)
    match_reason: str = Field(default="")

    @field_validator("profile_url", "matched_seed_url")
    @classmethod
    def clean_urls(cls, v: str) -> str:
        return normalize_linkedin_url(v)


class PipelineRunResult(BaseModel):
    search_phrase: str
    generated_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_mode: DataSourceMode
    discovery_provider: str = Field(default="")
    llm_model_used: str = Field(default="")
    total_duration_secs: float = Field(default=0.0)
    stage_timings_secs: dict[str, float] = Field(default_factory=dict)
    total_posts: int
    total_unique_commenters: int
    posts: list[DiscoveredPost]
    ranked_influencers: list[RankedInfluencer]
    similar_profiles: list[SimilarProfile] = Field(default_factory=list)
    related_companies: list[RelatedCompany] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)