import re
import pandas as pd
import streamlit as st
from src.config import (
    APIFY_API_TOKEN,
    DATA_RETENTION_DAYS,
    DEFAULT_SEARCH_PHRASE,
    ENABLE_CACHE,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    SERPER_API_KEY,
)
from src.pipeline import run_pipeline
from src.schemas import DataSourceMode
from src.stage6_export import result_to_csv_str, result_to_json_str

st.set_page_config(
    page_title="EDXSO | LinkedIn School Influencer Discovery",
    page_icon="🎓",
    layout="wide",
)

st.title("🎓 LinkedIn School Influencer Discovery Tool")
st.caption(
    "Discover and rank K12 decision-makers, school trustees, principals, and education consultants engaging with relevant LinkedIn discussions."
)

with st.sidebar:
    st.header("1. Search & Source Configuration")
    phrase = st.text_input("Search Phrase", value=DEFAULT_SEARCH_PHRASE)

    mode_label = st.radio(
        "Data Retrieval Mode",
        options=[
            "Live API (Serper/Apify + Groq/Gemini)",
            "Supplied Post URLs (Apify Comments + Groq/Gemini)",
            "Labelled Test Dataset (Offline Demo)",
        ],
        index=0,
    )
    mode_map = {
        "Live API (Serper/Apify + Groq/Gemini)": DataSourceMode.LIVE_API,
        "Supplied Post URLs (Apify Comments + Groq/Gemini)": DataSourceMode.SUPPLIED_URLS,
        "Labelled Test Dataset (Offline Demo)": DataSourceMode.TEST_DATASET,
    }
    selected_mode = mode_map[mode_label]

    supplied_urls_text = ""
    if selected_mode == DataSourceMode.SUPPLIED_URLS:
        supplied_urls_text = st.text_area(
            "Paste up to 5 LinkedIn Post URLs (one per line)",
            height=130,
            placeholder="https://www.linkedin.com/posts/...",
        )

    use_cache = st.checkbox(
        "Use local TTL cache (sub-5s repeat runs)",
        value=ENABLE_CACHE,
        help="Caches SERP discovery, post comments, per-profile AI extraction, and target persona embeddings.",
    )

    st.divider()
    st.header("2. API Credentials")
    serper_key = st.text_input(
        "Serper API Key (Fast Discovery)",
        value=SERPER_API_KEY,
        type="password",
        help="Fast (~1-3s) Google SERP search for Stage 2; falls back to Apify SERP if omitted.",
    )
    groq_key = st.text_input(
        "Groq API Key (Fast AI Analysis)",
        value=GROQ_API_KEY,
        type="password",
        help="High-speed structured analysis for Stage 4; falls back to Gemini Flash-Lite if omitted.",
    )
    gemini_key = st.text_input(
        "Gemini API Key (Embeddings & Fallback)",
        value=GEMINI_API_KEY,
        type="password",
        help="Required for Stage 5 semantic embeddings and Stage 4 fallback.",
    )
    apify_token = st.text_input(
        "Apify API Token (Comments & SERP Fallback)",
        value=APIFY_API_TOKEN,
        type="password",
        help="Required for cookie-less comment extraction (Stage 3) and SERP fallback.",
    )

    run_clicked = st.button("Run 6-Stage Discovery Pipeline", type="primary", use_container_width=True)

    st.divider()
    with st.expander("Responsible Access & Data Governance"):
        st.caption(
            f"• **No auth/CAPTCHA bypass:** Uses Serper public search / cookie-less Apify actors, user-supplied URLs, or a clearly labelled reference test dataset.\n"
            f"• **Data minimization:** Stores only outreach-relevant public fields (name, profile URL, role, org, location, post trace).\n"
            f"• **Retention policy:** Exports should be purged or refreshed within **{DATA_RETENTION_DAYS} days** under applicable privacy rules."
        )

if run_clicked:
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(step: int, message: str) -> None:
        progress_bar.progress(int((step / 6) * 100))
        status_text.info(f"**Stage {step}/6:** {message}")

    try:
        urls_list = [u.strip() for u in supplied_urls_text.splitlines() if u.strip()]
        result = run_pipeline(
            raw_phrase=phrase,
            mode=selected_mode,
            supplied_urls=urls_list,
            gemini_api_key=gemini_key,
            apify_token=apify_token,
            serper_api_key=serper_key,
            groq_api_key=groq_key,
            use_cache=use_cache,
            on_progress=update_progress,
        )
        st.session_state["last_result"] = result
        status_text.success(f"Pipeline completed in {result.total_duration_secs:.2f}s.")
    except Exception as exc:
        status_text.error(f"Pipeline halted: {exc}")

if "last_result" in st.session_state:
    res = st.session_state["last_result"]

    if res.source_mode == DataSourceMode.TEST_DATASET:
        st.info(
            "**Clearly Labelled Test Dataset Mode:** Showing the offline EDXSO reference dataset (`data/sample_dataset.json`) processed live by AI analysis and semantic ranking."
        )

    for warning_msg in res.warnings:
        st.warning(warning_msg)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Search Phrase", res.search_phrase)
    m2.metric("Source Mode", res.source_mode.value)
    m3.metric("Discovered Posts", res.total_posts)
    m4.metric("Unique Commenters", res.total_unique_commenters)
    m5.metric("Total Runtime", f"{res.total_duration_secs:.2f}s")

    if res.stage_timings_secs:
        timing_parts = " | ".join(
            f"{k.replace('_', ' ').title()}: {v:.2f}s" for k, v in res.stage_timings_secs.items()
        )
        st.caption(
            f"**Engines:** Discovery = `{res.discovery_provider or 'N/A'}` · "
            f"LLM = `{res.llm_model_used or 'N/A'}` · **Breakdown:** {timing_parts}"
        )

    st.subheader("Stage 2: Discovered LinkedIn Posts")
    posts_df = pd.DataFrame(
        [
            {
                "Post #": idx,
                "Author": p.author_name,
                "Date": p.published_date,
                "Snippet": p.snippet,
                "Post URL": p.post_url,
            }
            for idx, p in enumerate(res.posts, start=1)
        ]
    )
    st.dataframe(
        posts_df,
        use_container_width=True,
        hide_index=True,
        column_config={"Post URL": st.column_config.LinkColumn("Post URL")},
    )

    st.subheader("Stages 3–5: Ranked School Ecosystem Influencers")
    all_indicators = sorted(
        {ind for inf in res.ranked_influencers for ind in inf.school_ecosystem_indicators}
    )
    chosen_indicators = st.multiselect(
        "Filter by School-Ecosystem Indicator",
        options=all_indicators,
        default=[],
    )

    filtered = [
        inf
        for inf in res.ranked_influencers
        if not chosen_indicators
        or any(ind in chosen_indicators for ind in inf.school_ecosystem_indicators)
    ]

    if filtered:
        ranked_df = pd.DataFrame(
            [
                {
                    "Rank": inf.rank,
                    "Name": inf.name,
                    "Relevance Score": inf.final_relevance_score,
                    "LLM Fit": inf.llm_fit_score,
                    "Semantic Sim": inf.embedding_similarity,
                    "Engagement Bonus": inf.engagement_bonus,
                    "Role": inf.current_role,
                    "Organization": inf.organization,
                    "Location": inf.location,
                    "Indicators": ", ".join(inf.school_ecosystem_indicators),
                    "Posts Commented": inf.commented_post_count,
                    "Profile URL": inf.profile_url,
                }
                for inf in filtered
            ]
        )
        st.dataframe(
            ranked_df,
            use_container_width=True,
            hide_index=True,
            column_config={"Profile URL": st.column_config.LinkColumn("Profile URL")},
        )

        st.markdown("### Detailed Match Explanations & Post-to-Commenter Traceability")
        for inf in filtered:
            with st.expander(
                f"#{inf.rank} — {inf.name} ({inf.final_relevance_score}/100) | {inf.current_role} @ {inf.organization}"
            ):
                st.write(f"**Profile:** {inf.profile_url}")
                st.write(f"**Location:** {inf.location}")
                st.write(f"**Ecosystem Indicators:** {', '.join(inf.school_ecosystem_indicators)}")
                st.write(
                    f"**Score Breakdown:** Final `{inf.final_relevance_score}/100` "
                    f"(LLM Fit `{inf.llm_fit_score}`, Semantic Similarity `{inf.embedding_similarity}`, "
                    f"Multi-Post Bonus `+{inf.engagement_bonus}`)"
                )
                st.write(f"**Why They Match:** {inf.match_explanation}")
                st.markdown("**Engaged Posts:**")
                for trace in inf.commented_posts:
                    st.markdown(
                        f"- [{trace.post_author}]({trace.post_url}) — *\"{trace.comment_snippet}\"*"
                    )
    else:
        st.warning("No commenters matched the selected filter or none were publicly available.")

    st.subheader("Stage 6: Export Traceable Results")
    file_slug = re.sub(r"[^a-z0-9]+", "_", res.search_phrase.lower()).strip("_") or "results"
    c1, c2 = st.columns(2)
    c1.download_button(
        label="Download Ranked Results (CSV)",
        data=result_to_csv_str(res),
        file_name=f"{file_slug}_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
    c2.download_button(
        label="Download Full Traceable Output (JSON)",
        data=result_to_json_str(res),
        file_name=f"{file_slug}_results.json",
        mime="application/json",
        use_container_width=True,
    )
