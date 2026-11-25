import csv
import io
import json
from types import SimpleNamespace
import pytest
from starlette.testclient import TestClient
from api import app as api_app
from src.schemas import (
    DataSourceMode,
    DeduplicatedCommenter,
    DiscoveredPost,
    EcosystemIndicator,
    PipelineRunResult,
    PostTrace,
    ProfileAnalysis,
    RankedInfluencer,
    normalize_linkedin_url,
)
from src.stage1_input import parse_search_phrase
from src.stage2_discovery import (
    decode_linkedin_post_timestamp,
    discover_posts_live_with_meta,
    discover_related_companies,
    load_supplied_posts,
    parse_serp_pages_to_posts,
)
from src.stage3_extraction import extract_and_deduplicate_commenters, parse_apify_comments
from src.stage4_ai_analysis import (
    CompactBatchAnalysisResponse,
    CompactProfileAnalysisItem,
    analyze_all_commenters_with_meta,
)
from src.stage5_ranking import rank_commenters
from src.stage6_export import result_to_csv_str, result_to_json_str


def test_url_normalization_strips_tracking_params_and_lowercases_profile():
    dirty = "https://www.linkedin.com/in/Meenakshi-Sundaram-K12/?miniProfileUrn=urn%3Ali%3Afs_miniProfile%3A123"
    assert normalize_linkedin_url(dirty) == "https://www.linkedin.com/in/meenakshi-sundaram-k12"


def test_parse_search_phrase_normalizes_whitespace():
    assert parse_search_phrase("  K12   B2B   Sales ") == "K12 B2B Sales"
    assert parse_search_phrase(None) == "K12 B2B Sales"


def test_stage2_decodes_snowflake_dates_authors_and_prioritizes_recency():
    serp_pages = [
        {
            "organicResults": [
                {
                    "url": "https://www.linkedin.com/posts/old-post_k12-b2b-sales-activity-7274760277265371136-3lpz",
                    "title": "White Force Group's Post",
                    "websiteTitle": "LinkedIn\xa0·\xa0White Force Group",
                    "description": "Experience in K12 B2B Sales.",
                    "displayedUrl": "1 year ago",
                },
                {
                    "url": "https://www.linkedin.com/posts/savvaslearning_k12-salesjobs-edtech-activity-7507061054666059776-jcQo",
                    "title": "Savvas Learning Company - k12 #salesjobs #edtech",
                    "websiteTitle": "LinkedIn\xa0·\xa0The community for ventures designed to scale rapidly | Read our rules before posting",
                    "description": "K12 B2B Sales role.",
                    "displayedUrl": "2 months ago",
                },
                {
                    "url": "https://www.linkedin.com/posts/amrit-sharma_k-12-b2b-sales-timeline-activity-7496909221683171328-UBuX",
                    "title": "K-12 B2B Buying Cycle | Amrit Sharma posted on LinkedIn",
                    "websiteTitle": "LinkedIn\xa0·\xa0Amrit Sharma",
                    "description": "Insights on K12 B2B Sales timeline.",
                    "displayedUrl": "3 months ago",
                },
                {
                    "url": "https://www.linkedin.com/in/not-a-post-profile",
                    "title": "Someone on LinkedIn",
                    "description": "K12 B2B Sales",
                },
            ]
        }
    ]
    posts = parse_serp_pages_to_posts(serp_pages, phrase="K12 B2B Sales", limit=5)
    assert len(posts) == 3
    assert posts[0].author_name == "Savvas Learning Company"
    assert posts[1].author_name == "Amrit Sharma"
    assert posts[1].published_date == "2026-08-22"
    assert posts[2].author_name == "White Force Group"
    assert decode_linkedin_post_timestamp(posts[2].post_url).strftime("%Y-%m-%d") == "2024-12-17"


def test_stage2_serper_format_parses_truncated_titles_and_falls_back_to_apify(monkeypatch):
    serper_pages = [
        {
            "organic": [
                {
                    "link": "https://www.linkedin.com/posts/brittanymiller53_most-b2b-sales-motions-dont-work-in-k-12-activity-7448036580788723712-Jlws",
                    "title": "K-12 Sales Motions Don't Work in Education | Brittany Miller, M.Ed. ...",
                    "snippet": "Most B2B sales motions don't work in K-12.",
                },
                {
                    "link": "https://www.linkedin.com/posts/michaeledwardspencer_how-to-sell-to-schools-as-vc-and-federal-activity-7302696131258421248-mVsn",
                    "title": "How to sell your K12 product globally with B2O | Michael E. Spencer posted ...",
                    "snippet": "International K12 B2B sales channel strategy.",
                },
            ]
        }
    ]
    posts = parse_serp_pages_to_posts(serper_pages, phrase="K12 B2B Sales", limit=5)
    assert len(posts) == 2
    assert posts[0].author_name == "Brittany Miller, M.Ed."
    assert posts[1].author_name == "Michael E. Spencer"

    monkeypatch.setattr(
        "src.stage2_discovery._search_serper_pages",
        lambda phrase, key: (_ for _ in ()).throw(RuntimeError("Serper HTTP 429")),
    )
    monkeypatch.setattr(
        "src.stage2_discovery._search_apify_serp_pages",
        lambda phrase, token: serper_pages,
    )
    fallback_posts, provider, warnings = discover_posts_live_with_meta(
        "K12 B2B Sales",
        apify_token="apify-test",
        serper_api_key="serper-test",
        use_cache=False,
    )
    assert len(fallback_posts) == 2
    assert provider == "Apify SERP"
    assert any("fell back to Apify" in w for w in warnings)


def test_load_supplied_posts_validates_urls():
    with pytest.raises(ValueError):
        load_supplied_posts(["https://example.com/not-linkedin"], phrase="K12 B2B Sales")


def test_sample_dataset_deduplicates_multi_post_commenters():
    posts = [
        DiscoveredPost(
            post_id="7321001001",
            post_url="https://www.linkedin.com/posts/arjun-mehta-edtech_k12-b2b-sales-school-partnerships-activity-7321001001-abcd",
            author_name="Arjun Mehta",
            snippet="K12 B2B Sales",
            source_mode=DataSourceMode.TEST_DATASET,
        ),
        DiscoveredPost(
            post_id="7321001002",
            post_url="https://www.linkedin.com/posts/kavita-nair-k12_k12-b2b-sales-edtech-leadership-activity-7321001002-efgh",
            author_name="Kavita Nair",
            snippet="K12 B2B Sales",
            source_mode=DataSourceMode.TEST_DATASET,
        ),
    ]
    commenters = extract_and_deduplicate_commenters(posts, mode=DataSourceMode.TEST_DATASET)
    meenakshi = next(c for c in commenters if "meenakshi" in c.profile_url)
    assert meenakshi.engagement_count == 2
    assert len(meenakshi.commented_posts) == 2


def test_parse_apify_comments_skips_author_and_company_and_matches_query_post():
    post = DiscoveredPost(
        post_id="7511044245424689152",
        post_url="https://www.linkedin.com/posts/amanda_k12-sales-activity-7511044245424689152-HL_B",
        author_name="Amanda",
        snippet="K12 sales",
    )
    items = [
        {
            "query": {"post": post.post_url},
            "commentary": "Thanks for sharing!",
            "actor": {
                "name": "Amanda",
                "linkedinUrl": "https://www.linkedin.com/in/amanda",
                "author": True,
                "type": "profile",
            },
        },
        {
            "query": {"post": post.post_url},
            "commentary": "Follow our page",
            "actor": {
                "name": "EduCorp",
                "linkedinUrl": "https://www.linkedin.com/company/educorp",
                "author": False,
                "type": "company",
            },
        },
        {
            "query": {"post": post.post_url},
            "commentary": "True for CBSE school trustees too.",
            "actor": {
                "name": "Dr. Rao",
                "linkedinUrl": "https://www.linkedin.com/in/Dr-Rao/?trk=123",
                "position": "Former Principal & School Advisor",
                "location": {"city": "Hyderabad", "country": "India"},
                "author": False,
                "type": "profile",
            },
        },
    ]
    comments, loc_hints = parse_apify_comments(items, [post])
    assert len(comments) == 1
    assert comments[0].profile_url == "https://www.linkedin.com/in/dr-rao"
    assert loc_hints["https://www.linkedin.com/in/dr-rao"] == "Hyderabad, India"


def test_stage4_groq_primary_and_gemini_503_fallback(monkeypatch):
    class FakeModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, model, contents, config):
            self.calls.append(model)
            if model == "gemini-3.5-flash-lite":
                raise RuntimeError("503 UNAVAILABLE")
            return SimpleNamespace(
                parsed=CompactBatchAnalysisResponse(
                    results=[
                        CompactProfileAnalysisItem(
                            id=1,
                            role="School Advisor",
                            org="",
                            loc="Hyderabad, India",
                            inds=[
                                EcosystemIndicator.CONSULTANT_ADVISOR,
                                EcosystemIndicator.CONSULTANT_ADVISOR,
                            ],
                            score=92.0,
                            why="Advises K12 school trustees.",
                        )
                    ]
                ),
                text="",
            )

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr("src.stage4_ai_analysis.genai.Client", lambda **kwargs: fake_client)

    commenters = [
        DeduplicatedCommenter(
            profile_url="https://www.linkedin.com/in/dr-rao",
            name="Dr. Rao",
            headline="Former Principal & School Advisor",
            location_hint="Hyderabad, India",
            commented_posts=[
                PostTrace(
                    post_url="https://www.linkedin.com/posts/test-activity-7511044245424689152-HL_B",
                    post_author="Amanda",
                    comment_snippet="True for CBSE school trustees too.",
                )
            ],
        )
    ]

    # Gemini fallback path (Groq explicitly empty)
    analyses, used_model, warnings = analyze_all_commenters_with_meta(
        commenters,
        gemini_api_key="test-key",
        groq_api_key="",
        use_cache=False,
    )
    assert used_model == "gemini-3.1-flash-lite"
    rao = analyses["https://www.linkedin.com/in/dr-rao"]
    assert rao.organization == "Not publicly listed"
    assert rao.school_ecosystem_indicators == [EcosystemIndicator.CONSULTANT_ADVISOR]
    assert rao.llm_fit_score == 92.0
    assert any("gemini-3.1-flash-lite" in w for w in warnings)

    # Groq primary path when Groq key is provided
    class FakeGroqResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": CompactBatchAnalysisResponse(
                                results=[
                                    CompactProfileAnalysisItem(
                                        id=1,
                                        role="Principal Advisor",
                                        org="Independent",
                                        loc="Hyderabad",
                                        inds=[EcosystemIndicator.CONSULTANT_ADVISOR],
                                        score=94.0,
                                        why="Advises CBSE school trustees.",
                                    )
                                ]
                            ).model_dump_json()
                        }
                    }
                ]
            }

    class FakeHttpxClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json):
            return FakeGroqResp()

        def close(self):
            pass

    monkeypatch.setattr("src.stage4_ai_analysis.httpx.Client", FakeHttpxClient)
    groq_analyses, groq_model, groq_warnings = analyze_all_commenters_with_meta(
        commenters,
        gemini_api_key="",
        groq_api_key="gsk-test",
        use_cache=False,
    )
    assert groq_model == "openai/gpt-oss-120b"
    assert groq_analyses["https://www.linkedin.com/in/dr-rao"].llm_fit_score == 94.0
    assert groq_warnings == []


def test_stage5_ranking_and_stage6_export(monkeypatch):
    class FakeEmbedModels:
        def embed_content(self, model, contents, config):
            vecs = []
            for idx, _ in enumerate(contents):
                if idx == 0:
                    vecs.append(SimpleNamespace(values=[1.0, 0.0]))
                elif idx == 1:
                    vecs.append(SimpleNamespace(values=[0.9, 0.1]))
                else:
                    vecs.append(SimpleNamespace(values=[0.2, 0.98]))
            return SimpleNamespace(embeddings=vecs)

    monkeypatch.setattr(
        "src.stage5_ranking.genai.Client",
        lambda **kwargs: SimpleNamespace(models=FakeEmbedModels()),
    )

    commenters = [
        DeduplicatedCommenter(
            profile_url="https://www.linkedin.com/in/principal-a",
            name="Principal A",
            headline="Former Principal advising 10 schools",
            commented_posts=[
                PostTrace(post_url="https://www.linkedin.com/posts/1", post_author="Author 1", comment_snippet="Great"),
                PostTrace(post_url="https://www.linkedin.com/posts/2", post_author="Author 2", comment_snippet="Agreed"),
            ],
        ),
        DeduplicatedCommenter(
            profile_url="https://www.linkedin.com/in/sdr-b",
            name="SDR B",
            headline="HR SaaS SDR",
            commented_posts=[
                PostTrace(post_url="https://www.linkedin.com/posts/1", post_author="Author 1", comment_snippet="Nice"),
            ],
        ),
    ]
    analyses = {
        "https://www.linkedin.com/in/principal-a": ProfileAnalysis(
            current_role="School Consultant",
            organization="Independent",
            location="Bengaluru",
            school_ecosystem_indicators=[EcosystemIndicator.CONSULTANT_ADVISOR],
            llm_fit_score=90.0,
            match_explanation="Advises 10 schools.",
        ),
        "https://www.linkedin.com/in/sdr-b": ProfileAnalysis(
            current_role="SDR",
            organization="HR SaaS",
            location="Gurugram",
            school_ecosystem_indicators=[EcosystemIndicator.NOT_APPLICABLE],
            llm_fit_score=20.0,
            match_explanation="Non-K12 SaaS.",
        ),
    }

    ranked = rank_commenters(commenters, analyses, gemini_api_key="test-key", use_cache=False)
    assert ranked[0].name == "Principal A"
    assert ranked[0].rank == 1
    assert ranked[0].engagement_bonus == 5.0

    # Verify single-item fallback when an embedding model collapses list inputs into 1 vector
    class CollapsingListEmbedModels:
        def embed_content(self, model, contents, config):
            if isinstance(contents, list):
                return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5, 0.5])])
            vec = [0.95, 0.05] if "Principal" in contents or "Ideal" in contents else [0.1, 0.99]
            return SimpleNamespace(embeddings=[SimpleNamespace(values=vec)])

    monkeypatch.setattr(
        "src.stage5_ranking.genai.Client",
        lambda **kwargs: SimpleNamespace(models=CollapsingListEmbedModels()),
    )
    ranked_fallback = rank_commenters(commenters, analyses, gemini_api_key="test-key", use_cache=False)
    assert len(ranked_fallback) == 2
    assert ranked_fallback[0].name == "Principal A"

    run_res = PipelineRunResult(
        search_phrase="K12 B2B Sales",
        source_mode=DataSourceMode.TEST_DATASET,
        total_posts=2,
        total_unique_commenters=2,
        posts=[],
        ranked_influencers=ranked,
    )
    csv_rows = list(csv.DictReader(io.StringIO(result_to_csv_str(run_res))))
    assert len(csv_rows) == 2
    assert "Author 1; Author 2" in csv_rows[0]["commented_post_authors"]
    parsed_json = json.loads(result_to_json_str(run_res))
    assert parsed_json["ranked_influencers"][0]["commented_post_count"] == 2


def test_starlette_api_endpoints_and_exports(monkeypatch):
    client = TestClient(api_app)
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    cfg_resp = client.get("/api/config")
    assert cfg_resp.status_code == 200
    cfg_data = cfg_resp.json()
    assert "credentials" in cfg_data
    assert cfg_data["data_retention_days"] == 30

    sample_run = PipelineRunResult(
        search_phrase="K12 B2B Sales",
        source_mode=DataSourceMode.TEST_DATASET,
        discovery_provider="Test Dataset",
        llm_model_used="test-model",
        total_duration_secs=1.2,
        stage_timings_secs={"stage1_input": 0.01},
        total_posts=1,
        total_unique_commenters=1,
        posts=[
            DiscoveredPost(
                post_id="7321001001",
                post_url="https://www.linkedin.com/posts/arjun_test-activity-7321001001-abcd",
                author_name="Arjun",
                published_date="2026-11-12",
                snippet="K12 B2B Sales",
                source_mode=DataSourceMode.TEST_DATASET,
            )
        ],
        ranked_influencers=[
            RankedInfluencer(
                rank=1,
                name="Principal A",
                profile_url="https://www.linkedin.com/in/principal-a",
                current_role="Principal",
                organization="School Group",
                location="Bengaluru",
                school_ecosystem_indicators=["Former Principal/Director"],
                embedding_similarity=85.0,
                llm_fit_score=90.0,
                engagement_bonus=0.0,
                final_relevance_score=88.25,
                match_explanation="Former school principal.",
                commented_post_count=1,
                commented_posts=[
                    PostTrace(
                        post_url="https://www.linkedin.com/posts/arjun_test-activity-7321001001-abcd",
                        post_author="Arjun",
                        comment_snippet="Great insight",
                    )
                ],
            )
        ],
    )

    monkeypatch.setattr("api.run_pipeline", lambda **kwargs: sample_run)
    monkeypatch.setattr("api.save_outputs", lambda *args, **kwargs: None)

    disc_resp = client.post(
        "/api/discover",
        json={"phrase": "K12 B2B Sales", "mode": "test_dataset", "use_cache": False},
    )
    assert disc_resp.status_code == 200
    assert disc_resp.json()["ranked_influencers"][0]["name"] == "Principal A"

    csv_resp = client.post("/api/export/csv", json=sample_run.model_dump(mode="json"))
    assert csv_resp.status_code == 200
    assert "Principal A" in csv_resp.text

    json_resp = client.post("/api/export/json", json=sample_run.model_dump(mode="json"))
    assert json_resp.status_code == 200
    assert json_resp.json()["total_unique_commenters"] == 1


def test_discover_related_companies_from_serper_and_contacts(monkeypatch):
    monkeypatch.setattr(
        "src.stage2_discovery._search_serper_companies",
        lambda phrase, key: [
            {
                "title": "FuelK12 | LinkedIn",
                "link": "https://www.linkedin.com/company/fuelk12/?trk=abc",
                "snippet": "Helps K12 education companies grow.",
            },
            {
                "title": "EDU Sales Consults | LinkedIn",
                "link": "https://www.linkedin.com/company/edu-sales-consults",
                "snippet": "K-12 sales advisory group.",
            },
        ],
    )
    ranked = [
        RankedInfluencer(
            rank=1,
            name="Anudeep Naik",
            profile_url="https://www.linkedin.com/in/anudeepnaik",
            current_role="Strategy Lead",
            organization="LEAD School",
            location="Bengaluru",
            school_ecosystem_indicators=["Multi-School Network Professional"],
            embedding_similarity=87.0,
            llm_fit_score=90.0,
            engagement_bonus=0.0,
            final_relevance_score=89.0,
            match_explanation="School network leader.",
            commented_post_count=1,
            commented_posts=[],
        )
    ]
    companies = discover_related_companies(
        phrase="K12 B2B Sales",
        ranked_influencers=ranked,
        serper_api_key="serper-test",
        use_cache=False,
        limit=5,
    )
    assert len(companies) == 3
    assert companies[0].name == "FuelK12"
    assert companies[0].company_url == "https://www.linkedin.com/company/fuelk12"
    assert companies[2].name == "LEAD School"
    assert "Anudeep Naik" in companies[2].related_contacts
