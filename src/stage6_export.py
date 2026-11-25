import csv
import io
import json
from pathlib import Path
from src.schemas import PipelineRunResult


def result_to_json_str(result: PipelineRunResult) -> str:
    """Serialize full pipeline result with nested post-to-commenter traceability."""
    return json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False)


def result_to_csv_str(result: PipelineRunResult) -> str:
    """Serialize ranked influencers to a CRM-ready CSV with post traceability columns."""
    buffer = io.StringIO()
    fieldnames = [
        "rank",
        "name",
        "profile_url",
        "current_role",
        "organization",
        "location",
        "school_ecosystem_indicators",
        "final_relevance_score",
        "llm_fit_score",
        "embedding_similarity",
        "engagement_bonus",
        "commented_post_count",
        "commented_post_urls",
        "commented_post_authors",
        "comment_snippets",
        "match_explanation",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    for inf in result.ranked_influencers:
        writer.writerow(
            {
                "rank": inf.rank,
                "name": inf.name,
                "profile_url": inf.profile_url,
                "current_role": inf.current_role,
                "organization": inf.organization,
                "location": inf.location,
                "school_ecosystem_indicators": "; ".join(inf.school_ecosystem_indicators),
                "final_relevance_score": inf.final_relevance_score,
                "llm_fit_score": inf.llm_fit_score,
                "embedding_similarity": inf.embedding_similarity,
                "engagement_bonus": inf.engagement_bonus,
                "commented_post_count": inf.commented_post_count,
                "commented_post_urls": "; ".join(t.post_url for t in inf.commented_posts),
                "commented_post_authors": "; ".join(t.post_author for t in inf.commented_posts),
                "comment_snippets": " | ".join(t.comment_snippet for t in inf.commented_posts),
                "match_explanation": inf.match_explanation,
            }
        )

    return buffer.getvalue()


def save_outputs(
    result: PipelineRunResult,
    output_dir: Path,
    file_prefix: str = "k12_b2b_sales_results",
) -> tuple[Path, Path]:
    """Write both JSON and CSV outputs to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{file_prefix}.json"
    csv_path = output_dir / f"{file_prefix}.csv"

    json_path.write_text(result_to_json_str(result), encoding="utf-8")
    csv_path.write_text(result_to_csv_str(result), encoding="utf-8-sig")
    return json_path, csv_path