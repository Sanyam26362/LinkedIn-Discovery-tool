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
        "src.stage2_discovery._search_apify_linkedin_posts",
        lambda phrase, token, limit=5: (_ for _ in ()).throw(
            RuntimeError("Apify LinkedIn Search temporarily unavailable")
        ),
    )
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


def test_load_supplied_posts_validates_urls(monkeypatch):
    from src import stage2_discovery

    with pytest.raises(ValueError):
        load_supplied_posts(["https://example.com/not-linkedin"], phrase="K12 B2B Sales")

    class FakeRedirectClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def head(self, url):
            return SimpleNamespace(
                status_code=200,
                url="https://www.linkedin.com/posts/k12-edtech-education-share-7505508295126990848-a87b/?utm_source=social_share_send",
            )

        def get(self, url):
            return SimpleNamespace(status_code=200, url=url, text="")

    monkeypatch.setattr(stage2_discovery.httpx, "Client", FakeRedirectClient)
    resolved_posts = load_supplied_posts(["https://lnkd.in/p/gmVGnCHM"], phrase="EDXSO")
    assert len(resolved_posts) == 1
    assert resolved_posts[0].post_id == "7505508295126990848"
    assert (
        resolved_posts[0].post_url
        == "https://www.linkedin.com/posts/k12-edtech-education-share-7505508295126990848-a87b"
    )
    assert resolved_posts[0].published_date == "2026-09-15"


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
    assert ranked[0].embedding_similarity == 100.0
    assert ranked[1].embedding_similarity == 0.0

    # Verify anisotropy calibration ([0.62, 0.88] -> [0, 100]) and zero LLM/placeholder text leakage
    captured_contents: list[list[str]] = []

    class CalibratedEmbedModels:
        def embed_content(self, model, contents, config):
            captured_contents.append(list(contents))
            vecs = [
                SimpleNamespace(values=[1.0, 0.0]),  # persona
                SimpleNamespace(values=[0.85, 0.52678]),  # cos = 0.85 -> (0.85 - 0.62)/0.26 = 88.46
                SimpleNamespace(values=[0.75, 0.66144]),  # cos = 0.75 -> (0.75 - 0.62)/0.26 = 50.00
            ]
            return SimpleNamespace(embeddings=vecs)

    monkeypatch.setattr(
        "src.stage5_ranking.genai.Client",
        lambda **kwargs: SimpleNamespace(models=CalibratedEmbedModels()),
    )
    analyses_with_unlisted = {
        **analyses,
        "https://www.linkedin.com/in/sdr-b": ProfileAnalysis(
            current_role="Not publicly listed",
            organization="Not publicly listed",
            location="Not publicly listed",
            school_ecosystem_indicators=[EcosystemIndicator.NOT_APPLICABLE],
            llm_fit_score=20.0,
            match_explanation="Non-K12 SaaS.",
        ),
    }
    calibrated_ranked = rank_commenters(
        commenters, analyses_with_unlisted, gemini_api_key="test-key", use_cache=False
    )
    assert abs(calibrated_ranked[0].embedding_similarity - 88.46) < 0.2
    assert abs(calibrated_ranked[1].embedding_similarity - 50.0) < 0.2
    assert all("General / Non-K12 Specific" not in t for t in captured_contents[0][1:])
    assert all("Not publicly listed" not in t for t in captured_contents[0][1:])

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

    # Verify lexical fallback when Gemini embeddings hit 429 quota limits
    class QuotaErrorEmbedModels:
        def embed_content(self, model, contents, config):
            raise RuntimeError("429 RESOURCE_EXHAUSTED: embed_content_free_tier_requests")

    monkeypatch.setattr(
        "src.stage5_ranking.genai.Client",
        lambda **kwargs: SimpleNamespace(models=QuotaErrorEmbedModels()),
    )
    quota_warnings: list[str] = []
    quota_ranked = rank_commenters(
        commenters,
        analyses,
        gemini_api_key="test-key",
        use_cache=False,
        warnings_out=quota_warnings,
    )
    assert len(quota_ranked) == 2
    assert quota_ranked[0].name == "Principal A"
    assert any("lexical persona similarity fallback" in w for w in quota_warnings)

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


def test_stage2_serper_recency_gl_and_single_word_dedup(monkeypatch):
    from src import stage2_discovery

    sent_payloads: list[dict] = []

    class FakeSerperClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            sent_payloads.append(dict(json))
            return SimpleNamespace(status_code=200, text="{}", json=lambda: {"organic": []})

    monkeypatch.setattr(stage2_discovery, "SERPER_GL", "IN")
    monkeypatch.setattr(stage2_discovery.httpx, "Client", FakeSerperClient)

    stage2_discovery._search_serper_pages("EDXSO", "serper-test")
    assert len(sent_payloads) == 2
    assert all(p["num"] == 10 and p["gl"] == "in" and "after:" in p["q"] for p in sent_payloads)
    assert all('"EDXSO"' in p["q"] for p in sent_payloads)

    sent_payloads.clear()
    stage2_discovery._search_serper_pages("K12 B2B Sales", "serper-test")
    assert len(sent_payloads) == 3
    assert all(p["num"] == 10 and p["gl"] == "in" and "after:" in p["q"] for p in sent_payloads)
    assert sum('"K12 B2B Sales"' in p["q"] for p in sent_payloads) == 2
    assert sum('"K12 B2B Sales"' not in p["q"] and "K12 B2B Sales" in p["q"] for p in sent_payloads) == 1


def test_stage2_explicit_date_parsing_avoids_now_fallback():
    serp_pages = [
        {
            "organic": [
                {
                    "link": "https://www.linkedin.com/pulse/old-edtech-article",
                    "title": "Old Author - Article",
                    "date": "Feb 12, 2021",
                    "snippet": "K12 B2B Sales overview.",
                },
                {
                    "link": "https://www.linkedin.com/pulse/unparseable-edtech-article",
                    "title": "Mystery Author - Article",
                    "date": "Sometime earlier",
                    "snippet": "K12 B2B Sales notes.",
                },
                {
                    "link": "https://www.linkedin.com/pulse/recent-edtech-article",
                    "title": "Recent Author - Article",
                    "date": "2 days ago",
                    "snippet": "K12 B2B Sales update.",
                },
            ]
        }
    ]
    posts = parse_serp_pages_to_posts(serp_pages, phrase="K12 B2B Sales", limit=5)
    assert [p.author_name for p in posts] == ["Recent Author", "Old Author", "Mystery Author"]


def test_stage2_quoted_company_search_and_fallback(monkeypatch):
    from src import stage2_discovery

    company_queries: list[str] = []

    class QuotedFirstClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json):
            company_queries.append(json["q"])
            if '"EDXSO"' in json["q"]:
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {
                        "organic": [
                            {
                                "title": "EDXSO | LinkedIn",
                                "link": "https://in.linkedin.com/company/edxso",
                                "snippet": "Complete K12 school partner company.",
                            }
                        ]
                    },
                )
            return SimpleNamespace(status_code=200, json=lambda: {"organic": []})

    monkeypatch.setattr(stage2_discovery.httpx, "Client", QuotedFirstClient)
    items = stage2_discovery._search_serper_companies("EDXSO", "serper-test")
    assert len(items) == 1
    assert company_queries == ['site:linkedin.com/company "EDXSO"']

    # Verify non-company links on quoted query trigger unquoted fallback & single-word brand filter
    company_queries.clear()

    class MixedAndFallbackClient(QuotedFirstClient):
        def post(self, url, json):
            company_queries.append(json["q"])
            if '"EDXSO"' in json["q"]:
                return SimpleNamespace(
                    status_code=200,
                    json=lambda: {
                        "organic": [
                            {
                                "title": "EDXSO Webinars",
                                "link": "https://www.youtube.com/playlist?list=123",
                                "snippet": "Not a company URL",
                            }
                        ]
                    },
                )
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "organic": [
                        {
                            "title": "EDXSO | LinkedIn",
                            "link": "https://in.linkedin.com/company/edxso",
                            "snippet": "Complete K12 school partner.",
                        },
                        {
                            "title": "Edexo | LinkedIn",
                            "link": "https://in.linkedin.com/company/edexo",
                            "snippet": "Higher education SaaS.",
                        },
                        {
                            "title": "Empire Life | LinkedIn",
                            "link": "https://www.linkedin.com/company/empire-life?_hsenc=_edxso_123",
                            "snippet": "Insurance provider.",
                        },
                    ]
                },
            )

    monkeypatch.setattr(stage2_discovery.httpx, "Client", MixedAndFallbackClient)
    brand_companies = discover_related_companies(
        phrase="EDXSO",
        ranked_influencers=[],
        serper_api_key="serper-test",
        use_cache=False,
        limit=5,
    )
    assert company_queries == [
        'site:linkedin.com/company "EDXSO"',
        "site:linkedin.com/company EDXSO",
    ]
    assert [c.name for c in brand_companies] == ["EDXSO"]

    company_queries.clear()

    class FallbackClient(QuotedFirstClient):
        def post(self, url, json):
            company_queries.append(json["q"])
            if '"NicheK12"' in json["q"]:
                return SimpleNamespace(status_code=200, json=lambda: {"organic": []})
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "organic": [
                        {
                            "title": "NicheK12 Solutions | LinkedIn",
                            "link": "https://www.linkedin.com/company/nichek12",
                            "snippet": "K12 advisory.",
                        }
                    ]
                },
            )

    monkeypatch.setattr(stage2_discovery.httpx, "Client", FallbackClient)
    fallback_items = stage2_discovery._search_serper_companies("NicheK12", "serper-test")
    assert len(fallback_items) == 1
    assert company_queries == [
        'site:linkedin.com/company "NicheK12"',
        "site:linkedin.com/company NicheK12",
    ]


def test_stage3_replies_and_unmatched_comment_warning(caplog):
    from src.stage3_extraction import extract_and_deduplicate_commenters_with_meta

    posts = [
        DiscoveredPost(
            post_id="7511044245424689152",
            post_url="https://www.linkedin.com/posts/amanda_k12-sales-activity-7511044245424689152-HL_B",
            author_name="Amanda",
            snippet="K12 sales",
        ),
        DiscoveredPost(
            post_id="7480879493239439360",
            post_url="https://www.linkedin.com/posts/atul_edxso-activity-7480879493239439360-EG9X",
            author_name="Atul",
            snippet="EDXSO",
        ),
    ]
    items = [
        {
            "type": "reply",
            "query": {"post": posts[0].post_url},
            "commentary": "Happy to connect with CBSE principals.",
            "actor": {
                "name": "Meera Nair",
                "linkedinUrl": "https://www.linkedin.com/in/meera-nair",
                "position": "School Advisor",
                "author": False,
                "type": "profile",
            },
        },
        {
            "type": "comment",
            "query": {"post": "https://www.linkedin.com/posts/other-activity-9999999999999999999-zzzz"},
            "commentary": "Unmatched post ID",
            "actor": {
                "name": "Ghost User",
                "linkedinUrl": "https://www.linkedin.com/in/ghost-user",
                "author": False,
                "type": "profile",
            },
        },
    ]

    without_replies, _ = parse_apify_comments(items, posts, include_replies=False)
    assert without_replies == []

    stats: dict[str, int] = {}
    with caplog.at_level("WARNING"):
        with_replies, _ = parse_apify_comments(
            items, posts, include_replies=True, stats_out=stats
        )
    assert len(with_replies) == 1
    assert with_replies[0].commenter_name == "Meera Nair"
    assert stats["unmatched_count"] == 1
    assert any("could not be matched" in rec.message for rec in caplog.records)

    # Also verify end-to-end Stage 3 warnings propagation via mocked Apify call
    import src.stage3_extraction as st3

    orig_run = st3.run_apify_actor_and_fetch_items
    st3.run_apify_actor_and_fetch_items = lambda **kwargs: items
    try:
        commenters, s3_warnings = extract_and_deduplicate_commenters_with_meta(
            posts, mode=DataSourceMode.LIVE_API, apify_token="apify-test", use_cache=False
        )
    finally:
        st3.run_apify_actor_and_fetch_items = orig_run

    assert len(commenters) == 0  # default APIFY_SCRAPE_REPLIES=False skipped the reply item
    assert any("could not be matched" in w for w in s3_warnings)


def test_stage4_partial_batch_preserves_resolved_when_missing_retry_fails(monkeypatch):
    call_count = {"n": 0}

    class PartialGroqClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Return only 1 of 2 items in the batch
                return SimpleNamespace(
                    status_code=200,
                    text="{}",
                    json=lambda: {
                        "choices": [
                            {
                                "message": {
                                    "content": CompactBatchAnalysisResponse(
                                        results=[
                                            CompactProfileAnalysisItem(
                                                id=1,
                                                role="School Trustee",
                                                org="Oakridge Trust",
                                                loc="Hyderabad",
                                                inds=[EcosystemIndicator.OWNER_TRUSTEE],
                                                score=91.0,
                                                why="Manages K12 school trust.",
                                            )
                                        ]
                                    ).model_dump_json()
                                }
                            }
                        ]
                    },
                )
            # Retry for omitted item #2 fails across candidates
            raise RuntimeError("Transient 503 on single retry")

        def close(self):
            pass

    monkeypatch.setattr("src.stage4_ai_analysis.httpx.Client", PartialGroqClient)
    commenters = [
        DeduplicatedCommenter(
            profile_url="https://www.linkedin.com/in/trustee-1",
            name="Trustee One",
            headline="Managing Trustee @ Oakridge Trust",
            commented_posts=[
                PostTrace(
                    post_url="https://www.linkedin.com/posts/1",
                    post_author="Author",
                    comment_snippet="Great initiative.",
                )
            ],
        ),
        DeduplicatedCommenter(
            profile_url="https://www.linkedin.com/in/omitted-2",
            name="Omitted Two",
            headline="Educator",
            commented_posts=[
                PostTrace(
                    post_url="https://www.linkedin.com/posts/1",
                    post_author="Author",
                    comment_snippet="Thanks!",
                )
            ],
        ),
    ]

    analyses, used_model, warnings = analyze_all_commenters_with_meta(
        commenters, gemini_api_key="", groq_api_key="gsk-test", use_cache=False
    )
    assert analyses["https://www.linkedin.com/in/trustee-1"].llm_fit_score == 91.0
    assert analyses["https://www.linkedin.com/in/omitted-2"].llm_fit_score == 25.0
    assert used_model == "openai/gpt-oss-120b"
    assert warnings == []


def test_stage6_save_outputs_writes_utf8_bom_csv(tmp_path):
    from src.stage6_export import save_outputs

    res = PipelineRunResult(
        search_phrase="K12 B2B Sales",
        source_mode=DataSourceMode.TEST_DATASET,
        total_posts=0,
        total_unique_commenters=1,
        posts=[],
        ranked_influencers=[
            RankedInfluencer(
                rank=1,
                name="Priya Sharma — Advisor",
                profile_url="https://www.linkedin.com/in/priya",
                current_role="K–12 Consultant",
                organization="EduTrust",
                location="Bengaluru",
                school_ecosystem_indicators=["School/Education Consultant"],
                embedding_similarity=80.0,
                llm_fit_score=90.0,
                engagement_bonus=0.0,
                final_relevance_score=86.5,
                match_explanation="Advises K–12 schools.",
                commented_post_count=1,
                commented_posts=[],
            )
        ],
    )
    json_path, csv_path = save_outputs(res, tmp_path, file_prefix="unicode_test")
    raw_csv = csv_path.read_bytes()
    raw_json = json_path.read_bytes()
    assert raw_csv.startswith(b"\xef\xbb\xbf")
    assert not raw_json.startswith(b"\xef\xbb\xbf")
    assert "Priya Sharma — Advisor" in raw_csv.decode("utf-8-sig")

    client = TestClient(api_app)
    resp = client.post("/api/export/csv", json=res.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf")


def test_parse_apify_linkedin_posts_dedups_and_prefers_commented():
    from src.stage2_discovery import _parse_apify_linkedin_posts

    items = [
        {
            "type": "comment",
            "linkedinUrl": "https://www.linkedin.com/in/ignored",
            "content": "Should skip non-post items",
        },
        {
            "id": "7501001001001001001",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/author1_post-activity-7501001001001001001-aa11",
            "author": {"name": "Author Zero Comments"},
            "postedAt": {"date": "2026-11-20T10:15:00.000Z"},
            "content": "First result alphabetically but has zero comments.",
            "engagement": {"id": "7501001001001001001", "likes": 12, "shares": 1},
        },
        {
            "id": "7501001001001001002",
            "entityId": "7501001001001001002",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/author2_post-activity-7501001001001001002-bb22?utm_source=test",
            "author": {"name": "Author Commented A"},
            "postedAt": {"date": "2026-11-18T08:00:00.000Z"},
            "content": "Post A with active discussion.",
            "engagement": {"id": "7501001001001001002", "likes": 30, "comments": 7},
        },
        {
            # Duplicate of the post above via shareLinkedinUrl
            "id": "7501001001001001002",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/author2_post-activity-7501001001001001002-bb22",
            "author": {"name": "Author Commented A"},
            "postedAt": {"date": "2026-11-18T08:00:00.000Z"},
            "content": "Duplicate post A.",
            "engagement": {"comments": 7},
        },
        {
            "id": "7501001001001001003",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/author3_post-activity-7501001001001001003-cc33",
            "author": {"name": "Author Commented B"},
            "postedAt": {"date": "2026-11-15T12:00:00.000Z"},
            "content": "Post B with 3 comments.",
            "engagement": {"comments": 3},
        },
        {
            "id": "7501001001001001004",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/author4_post-activity-7501001001001001004-dd44",
            "author": {"name": "Author No Comments 2"},
            "postedAt": {"date": "2026-11-14T12:00:00.000Z"},
            "content": "Backfill post 2.",
            "engagement": {"comments": 0},
        },
    ]

    parsed = _parse_apify_linkedin_posts(items, phrase="EDXSO", limit=3)
    assert len(parsed) == 3
    assert [p.author_name for p in parsed] == [
        "Author Commented A",
        "Author Commented B",
        "Author Zero Comments",
    ]
    assert parsed[0].published_date == "2026-11-18"
    assert parsed[0].post_url == "https://www.linkedin.com/posts/author2_post-activity-7501001001001001002-bb22"


def test_search_apify_linkedin_posts_retries_without_posted_limit_and_falls_back(monkeypatch):
    from src import stage2_discovery

    actor_calls: list[tuple[str, dict]] = []

    def fake_apify_runner(actor_id, payload, token, timeout_secs=240):
        actor_calls.append((actor_id, dict(payload)))
        if "postedLimit" in payload:
            return [
                {
                    "id": "7510000000000000001",
                    "type": "post",
                    "linkedinUrl": "https://www.linkedin.com/posts/edxso_recent-activity-7510000000000000001-xx11",
                    "author": {"name": "EDXSO"},
                    "postedAt": {"date": "2026-10-10T09:00:00Z"},
                    "content": "Recent EDXSO post.",
                    "engagement": {"comments": 2},
                }
            ]
        return [
            {
                "id": "7510000000000000001",
                "type": "post",
                "linkedinUrl": "https://www.linkedin.com/posts/edxso_recent-activity-7510000000000000001-xx11",
                "author": {"name": "EDXSO"},
                "postedAt": {"date": "2026-10-10T09:00:00Z"},
                "content": "Recent EDXSO post.",
                "engagement": {"comments": 2},
            },
            {
                "id": "7470000000000000002",
                "type": "post",
                "linkedinUrl": "https://www.linkedin.com/posts/edxso_older-activity-7470000000000000002-yy22",
                "author": {"name": "Atul Nischal"},
                "postedAt": {"date": "2026-06-05T09:00:00Z"},
                "content": "Older EDXSO post.",
                "engagement": {"comments": 5},
            },
        ]

    monkeypatch.setattr(stage2_discovery, "LINKEDIN_SEARCH_SORT_BY", "relevance")
    monkeypatch.setattr(stage2_discovery, "LINKEDIN_SEARCH_POSTED_LIMIT", "3months")
    monkeypatch.setattr(stage2_discovery, "run_apify_actor_and_fetch_items", fake_apify_runner)

    native_posts, provider, warnings = discover_posts_live_with_meta(
        "EDXSO",
        apify_token="apify-test",
        serper_api_key="",
        limit=2,
        use_cache=False,
    )
    assert provider == "Apify LinkedIn Search"
    assert warnings == []
    assert len(actor_calls) == 2
    assert actor_calls[0][0] == "harvestapi~linkedin-post-search"
    assert actor_calls[0][1] == {
        "searchQueries": ["EDXSO"],
        "sortBy": "relevance",
        "maxPosts": 25,
        "scrapeComments": False,
        "scrapeReactions": False,
        "postedLimit": "3months",
    }
    assert "postedLimit" not in actor_calls[1][1]
    assert [p.author_name for p in native_posts] == ["Atul Nischal", "EDXSO"]

    # Verify concurrent hybrid Apify + Serper merge filters off-topic noise and deduplicates
    monkeypatch.setattr(
        stage2_discovery,
        "_search_serper_pages",
        lambda phrase, key: [
            {
                "organic": [
                    {
                        "link": "https://www.linkedin.com/posts/atulnischal_edxso-activity-7480879493239439360-EG9X",
                        "title": "Atul Nischal on LinkedIn: EDXSO partner network",
                        "snippet": "EDXSO builds school partnerships.",
                    }
                ]
            }
        ],
    )
    hybrid_posts, hybrid_provider, hybrid_warnings = discover_posts_live_with_meta(
        "EDXSO",
        apify_token="apify-test",
        serper_api_key="serper-test",
        limit=3,
        use_cache=False,
    )
    assert hybrid_provider == "Apify + Serper.dev"
    assert hybrid_warnings == []
    assert len(hybrid_posts) == 3

    # Verify automatic fallback to Serper.dev on Apify 402 quota error
    monkeypatch.setattr(
        stage2_discovery,
        "_search_apify_linkedin_posts",
        lambda phrase, token, limit=5: (_ for _ in ()).throw(
            RuntimeError("Apify usage quota or credit limit reached (402)")
        ),
    )
    serper_posts, serper_provider, serper_warnings = discover_posts_live_with_meta(
        "EDXSO",
        apify_token="apify-test",
        serper_api_key="serper-test",
        limit=1,
        use_cache=False,
    )
    assert serper_provider == "Serper.dev"
    assert len(serper_posts) == 1
    assert any("fell back to Serper.dev" in w for w in serper_warnings)


def test_parse_apify_linkedin_posts_filters_noise_and_sorts_by_comment_count():
    from src.stage2_discovery import _parse_apify_linkedin_posts

    items = [
        {
            "id": "7528868454934917120",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/veryable_floor-activity-7528868454934917120-9p0k",
            "author": {"name": "Veryable"},
            "postedAt": {"date": "2026-11-18T08:00:00Z"},
            "content": "Same-day floor reinforcement for plant managers.",
            "engagement": {"comments": 12, "likes": 40},
        },
        {
            "id": "7505508295839981568",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/edxso_k12-activity-7505508295839981568--K-p",
            "author": {"name": "EDXSO"},
            "postedAt": {"date": "2026-09-15T08:00:00Z"},
            "content": "EDXSO is building a K-12 Partner Network.",
            "engagement": {"comments": 2, "likes": 5},
        },
        {
            "id": "7505288663103336448",
            "type": "post",
            "linkedinUrl": "https://www.linkedin.com/posts/anisha_edxso-activity-7505288663103336448-8BG9",
            "author": {"name": "Anisha Verma"},
            "postedAt": {"date": "2026-09-14T08:00:00Z"},
            "content": "EDXSO Partner Network for school leaders.",
            "engagement": {"comments": 9, "likes": 15},
        },
    ]
    parsed = _parse_apify_linkedin_posts(items, phrase="EDXSO", limit=5)
    assert [p.author_name for p in parsed] == ["Anisha Verma", "EDXSO"]


def test_pipeline_runs_similar_profiles_only_for_supplied_urls(monkeypatch):
    from src import pipeline

    sample_post = DiscoveredPost(
        post_id="7505288663103336448",
        post_url="https://www.linkedin.com/posts/anisha_edxso-activity-7505288663103336448-8BG9",
        author_name="Anisha Verma",
        snippet="EDXSO Partner Network",
        source_mode=DataSourceMode.LIVE_API,
    )
    sample_commenter = DeduplicatedCommenter(
        profile_url="https://www.linkedin.com/in/ganeshl",
        name="Ganesh L",
        headline="Founder @ Educational Advisory",
        commented_posts=[
            PostTrace(
                post_url=sample_post.post_url,
                post_author="Anisha Verma",
                comment_snippet="EDXSO PARTNER",
            )
        ],
    )
    sample_analysis = {
        sample_commenter.profile_url: ProfileAnalysis(
            current_role="Founder",
            organization="Educational Advisory",
            location="Bengaluru",
            school_ecosystem_indicators=[EcosystemIndicator.CONSULTANT_ADVISOR],
            llm_fit_score=85.0,
            match_explanation="Advises K12 schools.",
        )
    }
    sample_ranked = [
        RankedInfluencer(
            rank=1,
            name="Ganesh L",
            profile_url="https://www.linkedin.com/in/ganeshl",
            current_role="Founder",
            organization="Educational Advisory",
            location="Bengaluru",
            school_ecosystem_indicators=["School/Education Consultant"],
            embedding_similarity=85.0,
            llm_fit_score=85.0,
            engagement_bonus=0.0,
            final_relevance_score=85.0,
            match_explanation="Advises K12 schools.",
            commented_post_count=1,
            commented_posts=sample_commenter.commented_posts,
        )
    ]

    similar_calls = {"n": 0}

    def fake_discover_similar(**kwargs):
        similar_calls["n"] += 1
        return [], []

    monkeypatch.setattr(pipeline, "discover_posts_live_with_meta", lambda *a, **kw: ([sample_post], "Apify + Serper.dev", []))
    monkeypatch.setattr(pipeline, "discover_related_companies", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "extract_and_deduplicate_commenters_with_meta", lambda **kw: ([sample_commenter], []))
    monkeypatch.setattr(pipeline, "analyze_all_commenters_with_meta", lambda *a, **kw: (sample_analysis, "test-llm", []))
    monkeypatch.setattr(pipeline, "rank_commenters", lambda *a, **kw: sample_ranked)
    monkeypatch.setattr(pipeline, "discover_similar_profiles", fake_discover_similar)

    live_res = pipeline.run_pipeline(raw_phrase="EDXSO", mode=DataSourceMode.LIVE_API, use_cache=False)
    assert live_res.similar_profiles == []
    assert similar_calls["n"] == 0

    demo_res = pipeline.run_pipeline(raw_phrase="K12 B2B Sales", mode=DataSourceMode.TEST_DATASET, use_cache=False)
    assert demo_res.similar_profiles == []
    assert similar_calls["n"] == 0

    url_res = pipeline.run_pipeline(
        raw_phrase="EDXSO",
        mode=DataSourceMode.SUPPLIED_URLS,
        supplied_urls=[sample_post.post_url],
        use_cache=False,
    )
    assert url_res.source_mode == DataSourceMode.SUPPLIED_URLS
    assert similar_calls["n"] == 1


def test_discover_similar_profiles_and_api_endpoint(monkeypatch):
    from src import similar_profiles

    seed = RankedInfluencer(
        rank=1,
        name="Dr. Meenakshi Sundaram",
        profile_url="https://www.linkedin.com/in/meenakshi-sundaram-k12",
        current_role="Former Principal | K12 School Transformation Consultant",
        organization="Not publicly listed",
        location="Bengaluru",
        school_ecosystem_indicators=["Former Principal/Director", "School/Education Consultant"],
        embedding_similarity=90.0,
        llm_fit_score=92.0,
        engagement_bonus=5.0,
        final_relevance_score=95.0,
        match_explanation="Advises 25+ CBSE and IB schools.",
        commented_post_count=2,
        commented_posts=[],
    )

    queries = similar_profiles.build_lookalike_queries([seed], phrase="K12 B2B Sales", max_queries=4)
    assert len(queries) >= 1
    assert all("Not publicly listed" not in q for q, _ in queries)
    assert all(q.startswith("site:linkedin.com/in") for q, _ in queries)

    monkeypatch.setattr(
        similar_profiles,
        "_search_serper_profiles",
        lambda qs, key: [
            {
                "organic": [
                    {
                        # Should be excluded because this URL is already the seed commenter
                        "title": "Dr. Meenakshi Sundaram - Former Principal | LinkedIn",
                        "link": "https://www.linkedin.com/in/meenakshi-sundaram-k12/?trk=abc",
                        "snippet": "Same seed person",
                    },
                    {
                        "title": "Kavita Krishnan - Former Principal & CBSE Advisor | LinkedIn",
                        "link": "https://in.linkedin.com/in/kavita-krishnan-k12",
                        "snippet": "20 years as K12 Principal advising CBSE school trusts.",
                    },
                    {
                        "title": "Rohan Kumar - Cloud DevOps Engineer | LinkedIn",
                        "link": "https://www.linkedin.com/in/rohan-devops",
                        "snippet": "Kubernetes and AWS microservices.",
                    },
                ]
            }
            for _ in qs
        ],
    )

    class FakeLookalikeEmbed:
        def embed_content(self, model, contents, config):
            vecs = []
            for text in contents:
                if "Principal" in text or "Ideal" in text:
                    vecs.append(SimpleNamespace(values=[0.95, 0.05]))
                else:
                    vecs.append(SimpleNamespace(values=[0.1, 0.99]))
            return SimpleNamespace(embeddings=vecs)

    monkeypatch.setattr(
        similar_profiles.genai,
        "Client",
        lambda **kwargs: SimpleNamespace(models=FakeLookalikeEmbed()),
    )

    lookalikes, warnings = similar_profiles.discover_similar_profiles(
        phrase="K12 B2B Sales",
        seed_influencers=[seed],
        exclude_urls={seed.profile_url},
        serper_api_key="serper-test",
        gemini_api_key="gemini-test",
        use_cache=False,
        limit=5,
    )
    assert warnings == []
    assert [p.name for p in lookalikes] == ["Kavita Krishnan", "Rohan Kumar"]
    assert lookalikes[0].similarity_score > lookalikes[1].similarity_score
    assert lookalikes[0].matched_seed_name == "Dr. Meenakshi Sundaram"

    client = TestClient(api_app)
    resp = client.post(
        "/api/similar",
        json={
            "phrase": "K12 B2B Sales",
            "seed_influencers": [seed.model_dump(mode="json")],
            "exclude_urls": [seed.profile_url],
            "limit": 5,
            "use_cache": False,
            "serper_api_key": "serper-test",
            "gemini_api_key": "gemini-test",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["similar_profiles"]) == 2
    assert body["similar_profiles"][0]["name"] == "Kavita Krishnan"

    bad_resp = client.post("/api/similar", json={"phrase": "K12 B2B Sales", "seed_influencers": []})
    assert bad_resp.status_code == 400
