from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone

from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.models import PlatformDraftResponse
from execution.research.research_runner import run_research
from execution.research.schema import ensure_research_schema
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger

logger = setup_logger("draft_generator")


def generate_research_draft(
    topic_title: str,
    lane: str | None = None,
    angle_type: str | None = None,
    platform: str = "newsletter",
    limit_per_task: int = 5,
    persist: bool = True,
) -> dict:
    """Run research, generate a platform draft, and save it for review."""

    ensure_research_schema()
    research_result = run_research(
        topic_title=topic_title,
        lane=lane,
        angle_type=angle_type,
        platform=platform,
        limit_per_task=limit_per_task,
        persist=persist,
    )
    draft = _generate_draft_from_research(research_result)
    draft_id = save_content_draft(research_result, draft) if persist else None
    return {
        "draft_id": draft_id,
        "draft": draft.model_dump(),
        "research": research_result,
    }


def _generate_draft_from_research(research_result: dict) -> PlatformDraftResponse:
    system_prompt = (PROMPTS_DIR / "brand_system_prompt.txt").read_text(encoding="utf-8")
    prompt_template = (PROMPTS_DIR / "platform_draft_generation.txt").read_text(encoding="utf-8")
    brief = research_result["brief"]
    package = research_result["platform_package"]
    sources = research_result["sources"]

    user_prompt = prompt_template.format(
        platform=brief["platform"],
        topic_title=brief["topic_title"],
        lane=brief["lane"],
        angle_type=brief.get("angle_type") or "unspecified",
        brief_json=json.dumps(brief, indent=2),
        platform_package_json=json.dumps(package, indent=2),
        sources_json=json.dumps(sources, indent=2),
    )

    client = LLMClient()
    return client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=PlatformDraftResponse,
        task_name=f"{brief['platform']}_draft_generation",
    )


def save_content_draft(research_result: dict, draft: PlatformDraftResponse) -> int:
    """Persist a generated platform draft as pending review."""

    brief = research_result["brief"]
    source_urls = research_result.get("platform_package", {}).get("source_urls", [])
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO content_drafts
                (topic_title, lane, angle_type, platform, title, dek,
                 content_json, source_urls_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review')
            """,
            (
                brief["topic_title"],
                brief["lane"],
                brief.get("angle_type"),
                brief["platform"],
                draft.title,
                draft.dek,
                json.dumps(draft.model_dump()),
                json.dumps(source_urls),
            ),
        )
        draft_id = cursor.lastrowid
        conn.commit()
        return int(draft_id)


def list_content_drafts(status: str | None = None, platform: str | None = None) -> list[dict]:
    """List generated platform drafts for review."""

    ensure_research_schema()
    clauses = []
    params: list[object] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if platform:
        clauses.append("platform = ?")
        params.append(platform)

    query = "SELECT * FROM content_drafts"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def approve_content_draft(draft_id: int, approved_by: str = "user") -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE content_drafts
            SET status = 'approved', approved_at = ?, approved_by = ?
            WHERE draft_id = ?
            """,
            (now, approved_by, draft_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def reject_content_draft(draft_id: int, reason: str = "") -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE content_drafts
            SET status = 'rejected', rejection_reason = ?
            WHERE draft_id = ?
            """,
            (reason, draft_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a reviewable research-backed platform draft.")
    parser.add_argument("topic_title")
    parser.add_argument("--lane", default=None)
    parser.add_argument("--angle-type", default=None)
    parser.add_argument("--platform", default="newsletter")
    parser.add_argument("--limit-per-task", type=int, default=5)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    result = generate_research_draft(
        topic_title=args.topic_title,
        lane=args.lane,
        angle_type=args.angle_type,
        platform=args.platform,
        limit_per_task=args.limit_per_task,
        persist=not args.no_persist,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
