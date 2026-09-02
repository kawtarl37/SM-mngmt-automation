from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone

from execution.config import PROMPTS_DIR
from execution.db import get_connection
from execution.knowledge.service import log_knowledge_usage, retrieve_reusable_knowledge
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
    brief = research_result["brief"]
    knowledge_entries = retrieve_reusable_knowledge(
        topic_title=brief["topic_title"],
        lane=brief["lane"],
        limit=10,
        include_sentiment=True,
    )
    draft = _generate_draft_from_research(research_result, knowledge_entries)
    draft_id = save_content_draft(research_result, draft) if persist else None
    if persist and draft_id:
        for entry in knowledge_entries:
            log_knowledge_usage(
                entry_id=entry["entry_id"],
                asset_type="content_draft",
                asset_id=draft_id,
                topic_title=brief["topic_title"],
                platform=brief["platform"],
                notes="Supplied as reusable KB context during draft generation.",
            )
    return {
        "draft_id": draft_id,
        "draft": draft.model_dump(),
        "research": research_result,
        "knowledge_entries": knowledge_entries,
    }


def _generate_draft_from_research(
    research_result: dict,
    knowledge_entries: list[dict] | None = None,
) -> PlatformDraftResponse:
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
    if knowledge_entries:
        user_prompt += (
            "\n\nREUSABLE KNOWLEDGE DATABASE CONTEXT:\n"
            "Use these quality-gated entries only where relevant. Community sentiment entries may be used "
            "for reader pain points and framing, not as verified factual claims.\n"
            f"{json.dumps(_knowledge_prompt_payload(knowledge_entries), indent=2)}"
        )

    client = LLMClient()
    draft = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=PlatformDraftResponse,
        task_name=f"{brief['platform']}_draft_generation",
    )
    problems = _final_draft_problems(draft, brief["platform"])
    if not problems:
        return draft

    retry_prompt = (
        f"{user_prompt}\n\n"
        "The previous response was not acceptable for review because: "
        f"{'; '.join(problems)}.\n\n"
        "Regenerate the asset as complete final reader-facing copy. Do not return an outline, "
        "writing instructions, section prompts, placeholders, or notes telling an editor what to add."
    )
    retry = client.generate_structured(
        system_prompt=system_prompt,
        user_prompt=retry_prompt,
        response_format=PlatformDraftResponse,
        task_name=f"{brief['platform']}_draft_generation_retry",
    )
    retry_problems = _final_draft_problems(retry, brief["platform"])
    if retry_problems:
        raise RuntimeError(
            "Generated draft was not saved because it was not final reader-facing copy: "
            + "; ".join(retry_problems)
        )
    return retry


def _knowledge_prompt_payload(entries: list[dict]) -> list[dict]:
    return [
        {
            "entry_id": entry["entry_id"],
            "entry_type": entry["entry_type"],
            "entity": entry.get("entity_name"),
            "claim": entry["claim"],
            "summary": entry.get("summary"),
            "quality_score": entry.get("quality_score"),
            "source_type": entry.get("source_type"),
        }
        for entry in entries
    ]


def _final_draft_problems(draft: PlatformDraftResponse, platform: str) -> list[str]:
    """Return reasons a platform draft is not ready to enter review."""

    sections = draft.sections or []
    problems: list[str] = []
    if len(sections) < 3:
        problems.append("fewer than three content sections")

    body_text = "\n".join(
        [draft.title, draft.dek, draft.call_to_action]
        + [section.heading for section in sections]
        + [section.body for section in sections]
    )
    lower_text = body_text.lower()
    outline_markers = (
        "todo",
        "tbd",
        "placeholder",
        "outline",
        "section should",
        "this section should",
        "write a section",
        "write an intro",
        "write copy",
        "add details",
        "expand on",
        "fill in",
        "insert ",
        "prompt:",
        "[",
        "]",
    )
    found_markers = [marker for marker in outline_markers if marker in lower_text]
    if found_markers:
        problems.append("contains outline or placeholder language: " + ", ".join(found_markers[:4]))

    minimum_words = {
        "blog": 600,
        "newsletter": 120,
        "pinterest": 45,
        "app": 60,
    }.get(platform, 100)
    if len(body_text.split()) < minimum_words:
        problems.append(f"too short for a complete {platform} deliverable")

    empty_sections = [section.heading or f"section {index + 1}" for index, section in enumerate(sections) if not section.body.strip()]
    if empty_sections:
        problems.append("empty section bodies: " + ", ".join(empty_sections[:3]))

    return problems


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
