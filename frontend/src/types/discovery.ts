export type DataSourceMode = "live_api" | "supplied_urls" | "test_dataset";

export interface DiscoveredPost {
  post_id: string;
  post_url: string;
  author_name: string;
  published_date: string;
  snippet: string;
  source_mode: DataSourceMode;
}

export interface PostTrace {
  post_url: string;
  post_author: string;
  comment_snippet: string;
}

export interface RelatedCompany {
  name: string;
  company_url: string;
  category: string;
  description: string;
  related_contacts: string[];
  source: string;
}

export interface RankedInfluencer {
  rank: number;
  name: string;
  profile_url: string;
  current_role: string;
  organization: string;
  location: string;
  school_ecosystem_indicators: string[];
  embedding_similarity: number;
  llm_fit_score: number;
  engagement_bonus: number;
  final_relevance_score: number;
  match_explanation: string;
  commented_post_count: number;
  commented_posts: PostTrace[];
}

export interface PipelineRunResult {
  search_phrase: string;
  generated_at_utc: string;
  source_mode: DataSourceMode;
  discovery_provider: string;
  llm_model_used: string;
  total_duration_secs: number;
  stage_timings_secs: Record<string, number>;
  total_posts: number;
  total_unique_commenters: number;
  posts: DiscoveredPost[];
  ranked_influencers: RankedInfluencer[];
  related_companies: RelatedCompany[];
  warnings: string[];
}

export interface CredentialStatus {
  configured: boolean;
  preview: string;
}

export interface ApiConfigResponse {
  default_phrase: string;
  data_retention_days: number;
  defaults: {
    max_comments_per_post: number;
    use_cache: boolean;
  };
  credentials: {
    serper: CredentialStatus;
    groq: CredentialStatus;
    gemini: CredentialStatus;
    apify: CredentialStatus;
  };
}

export interface ProgressEvent {
  step: number;
  total_steps: number;
  message: string;
}

export interface DiscoveryRequestPayload {
  phrase: string;
  mode: DataSourceMode;
  supplied_urls: string[];
  use_cache: boolean;
  max_comments_per_post?: number;
  serper_api_key?: string;
  groq_api_key?: string;
  gemini_api_key?: string;
  apify_token?: string;
}
