from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from execution.db import get_connection
from execution.research.schema import ensure_research_schema


SECTION_TO_LANE = {
    "Product Watch": "product_watch",
    "Bread Wars and Comparisons": "comparison",
    "Restaurant and Travel Buzz": "restaurants_travel",
    "Kitchen Gadget Lab": "gadgets_tools",
    "Apps and Digital Tools": "apps_digital",
    "Organization and Real Life Systems": "organization_life",
    "Recipe Experiments": "recipe_experiments",
}


LANE_SOURCE_TYPE = {
    "product_watch": "brand_product_page",
    "comparison": "brand_product_page",
    "restaurants_travel": "restaurant_allergen_page",
    "gadgets_tools": "tool_product_page",
    "apps_digital": "app_review_page",
    "organization_life": "tool_product_page",
    "recipe_experiments": "brand_product_page",
}


LANE_CREDIBILITY = {
    "product_watch": 0.76,
    "comparison": 0.74,
    "restaurants_travel": 0.84,
    "gadgets_tools": 0.68,
    "apps_digital": 0.66,
    "organization_life": 0.66,
    "recipe_experiments": 0.78,
}


@dataclass(frozen=True)
class PrioritySourceRow:
    section: str
    lane: str
    name: str
    url: str
    why_readers_care: str
    content_angle: str
    best_home: str
    fact_check_required: bool


def import_priority_sources(markdown_path: str | Path, approved_by: str = "user") -> int:
    """Import a Markdown priority-source list into source_registry."""

    ensure_research_schema()
    rows = parse_priority_source_markdown(Path(markdown_path).read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    upserted = 0

    with get_connection() as conn:
        cursor = conn.cursor()
        for row in rows:
            source_type = _source_type_for(row)
            cursor.execute(
                "SELECT source_id FROM source_registry WHERE base_url = ? AND lane = ?",
                (row.url, row.lane),
            )
            existing = cursor.fetchone()
            values = (
                row.name,
                source_type,
                row.url,
                row.lane,
                LANE_CREDIBILITY.get(row.lane, 0.65),
                _frequency_for(row.lane),
                row.why_readers_care,
                True,
                "approved",
                "user_priority_list",
                now,
                approved_by,
                row.content_angle,
                row.best_home,
                row.fact_check_required,
                "priority",
            )
            if existing:
                cursor.execute(
                    """
                    UPDATE source_registry
                    SET name = ?, source_type = ?, base_url = ?, lane = ?,
                        credibility_score = ?, monitor_frequency = ?, notes = ?,
                        enabled = ?, approval_status = ?, added_by = ?,
                        approved_at = COALESCE(approved_at, ?), approved_by = ?,
                        content_angle = ?, best_home = ?, fact_check_required = ?,
                        priority_tier = ?
                    WHERE source_id = ?
                    """,
                    values + (existing["source_id"],),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO source_registry
                        (name, source_type, base_url, lane, credibility_score,
                         monitor_frequency, notes, enabled, approval_status,
                         added_by, approved_at, approved_by, content_angle,
                         best_home, fact_check_required, priority_tier)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            upserted += 1

        cursor.execute(
            """
            UPDATE source_notifications
            SET status = 'resolved', resolved_at = ?
            WHERE source_id IN (
                SELECT source_id FROM source_registry
                WHERE priority_tier = 'priority' AND approval_status = 'approved'
            )
            AND status != 'resolved'
            """,
            (now,),
        )
        conn.commit()

    return upserted


def parse_priority_source_markdown(markdown: str) -> list[PrioritySourceRow]:
    rows: list[PrioritySourceRow] = []
    current_section: str | None = None

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            current_section = section if section in SECTION_TO_LANE else None
            continue

        if not current_section or not line.startswith("|"):
            continue
        if line.startswith("|---") or "Official website URL" in line:
            continue

        cells = _split_markdown_row(line)
        if len(cells) < 6:
            continue

        name = _clean_cell(cells[0])
        url = _extract_url(cells[1])
        if not name or not url:
            continue

        rows.append(
            PrioritySourceRow(
                section=current_section,
                lane=SECTION_TO_LANE[current_section],
                name=name,
                url=url,
                why_readers_care=_clean_cell(cells[2]),
                content_angle=_clean_cell(cells[3]),
                best_home=_clean_cell(cells[4]),
                fact_check_required=_fact_check_required(cells[5]),
            )
        )

    return rows


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _clean_cell(cell: str) -> str:
    cell = re.sub(r"`([^`]+)`", r"\1", cell)
    cell = re.sub(r"îˆ€cite.*?îˆ", "", cell)
    cell = re.sub(r"[\ue000-\uf8ff]cite.*?[\ue000-\uf8ff]", "", cell)
    cell = re.sub(r"[\ue000-\uf8ff][a-zA-Z0-9]+", "", cell)
    cell = re.sub(r"turn\d+(?:search|view)\d+", "", cell)
    cell = re.sub(r"[\ue000-\uf8ff]", "", cell)
    cell = cell.replace("â€œ", "\"").replace("â€", "\"").replace("â€™", "'")
    cell = cell.replace("â€”", "-").replace("â€“", "-")
    cell = re.sub(r"\s+", " ", cell).strip()
    return cell


def _extract_url(cell: str) -> str:
    cleaned = _clean_cell(cell)
    match = re.search(r"https?://[^\s`]+", cleaned)
    return match.group(0).rstrip(".,)") if match else ""


def _fact_check_required(cell: str) -> bool:
    cleaned = _clean_cell(cell).lower()
    return cleaned.startswith("yes") or "yes" in cleaned or "official" in cleaned


def _frequency_for(lane: str) -> str:
    if lane in {"product_watch", "restaurants_travel", "apps_digital"}:
        return "weekly"
    if lane in {"gadgets_tools", "organization_life"}:
        return "monthly"
    return "weekly"


def _source_type_for(row: PrioritySourceRow) -> str:
    if row.name.lower() in {"trader joe's", "aldi livegfree", "target", "walmart", "instacart"}:
        return "retailer_product_page"
    if row.lane == "apps_digital" and "trends" in row.name.lower():
        return "trend_planning_tool"
    return LANE_SOURCE_TYPE.get(row.lane, "brand_product_page")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import EGF priority sources from Markdown.")
    parser.add_argument("markdown_path")
    parser.add_argument("--approved-by", default="user")
    args = parser.parse_args()

    count = import_priority_sources(args.markdown_path, approved_by=args.approved_by)
    print(f"Imported {count} priority sources.")


if __name__ == "__main__":
    main()
