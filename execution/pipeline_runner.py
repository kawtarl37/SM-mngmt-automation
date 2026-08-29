"""Automated lane-rotation content engine.

Replaces the old Reddit/PubMed trend-scrape pipeline (reddit_scraper.py,
medical_articles_scraper.py, trend_analyzer.py, trend_synthesizer.py) and the
old broad idea pipeline (idea_generator.py, idea_scorer.py, pin_assembler.py).

Picks the least-recently-covered editorial lanes, runs live research-grounded
discovery for each (execution.editorial.lane_discovery), scores the
resulting ideas, and generates a full blog + pin + newsletter bundle for the
best idea per lane -- landing everything in the existing review queues
(pending_review / generated). Nothing publishes automatically.

This is the AUTOMATED mode. Manual, on-demand generation (Content Studio's
per-lane "Generate Lane Ideas" trigger, Editorial Lab's direct topic entry)
stays available alongside this and hits the same underlying machinery --
this module is just the "run it on its own" entrypoint, schedulable via
Windows Task Scheduler / cron since it's a plain script.
"""

from __future__ import annotations

import argparse
import sys

from execution.config import LANE_ROTATION_COUNT
from execution.editorial.content_asset_service import create_assets_from_idea
from execution.editorial.lane_discovery import discover_lane_topics
from execution.editorial.memory import get_recent_topic_memory
from execution.editorial.scoring import EditorialScorer
from execution.editorial.taxonomy import CONTENT_LANES, classify_lane
from execution.utils.logger import setup_logger

logger = setup_logger("pipeline_runner")


def _lanes_by_recency(memory) -> list[str]:
    """Return all lane keys ordered least-recently-covered first, using each
    memory item's classified lane as a proxy (recent titles don't carry an
    explicit lane column)."""

    last_seen: dict[str, str] = {}
    for item in memory:  # memory is sorted newest-first
        lane_key = classify_lane(item.title)
        last_seen.setdefault(lane_key, item.created_at or "")

    return sorted((lane.key for lane in CONTENT_LANES), key=lambda key: last_seen.get(key, ""))


def run_lane_rotation(count: int = LANE_ROTATION_COUNT) -> dict:
    """Cover `count` lanes this run: discover real signals, score the
    resulting ideas, generate a full asset bundle for the top idea per lane.
    Returns a summary dict with per-lane outcomes."""

    normalized_count = max(1, min(int(count), len(CONTENT_LANES)))
    memory = get_recent_topic_memory(limit=150)
    ordered_lanes = _lanes_by_recency(memory)[:normalized_count]
    logger.info(f"Lane rotation starting for lanes: {ordered_lanes}")

    scorer = EditorialScorer(memory=memory)
    results = []
    for lane_key in ordered_lanes:
        logger.info(f"Lane rotation: discovering topics for lane={lane_key}")
        try:
            discovery = discover_lane_topics(lane_key=lane_key, idea_count=3, persist=True)
        except Exception as e:
            logger.error(f"Lane rotation: discovery failed for lane={lane_key}: {e}", exc_info=True)
            results.append({"lane": lane_key, "status": "discovery_failed", "error": str(e)})
            continue

        ideas = discovery.get("ideas") or []
        if not ideas:
            logger.warning(f"Lane rotation: no ideas generated for lane={lane_key}")
            results.append({"lane": lane_key, "status": "no_ideas"})
            continue

        scored = [
            (scorer.score(idea["title"], idea.get("description", ""), requested_lane=lane_key).total, idea)
            for idea in ideas
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top_idea = scored[0][1]

        logger.info(f"Lane rotation: generating assets for lane={lane_key} idea_id={top_idea.get('idea_id')}")
        try:
            assets = create_assets_from_idea(
                int(top_idea["idea_id"]),
                assets=["blog", "pin", "newsletter"],
                sample=False,
                persist=True,
            )
            results.append(
                {
                    "lane": lane_key,
                    "status": "generated",
                    "idea_id": top_idea.get("idea_id"),
                    "assets": assets["assets"],
                }
            )
        except Exception as e:
            logger.error(f"Lane rotation: asset generation failed for lane={lane_key}: {e}", exc_info=True)
            results.append({"lane": lane_key, "status": "asset_generation_failed", "error": str(e)})

    lanes_covered = [r["lane"] for r in results if r["status"] == "generated"]
    logger.info(f"Lane rotation complete. Covered: {lanes_covered}")
    return {"lanes_covered": lanes_covered, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run automated lane-rotation content generation.")
    parser.add_argument("--count", type=int, default=LANE_ROTATION_COUNT, help="Number of lanes to cover this run.")
    args = parser.parse_args()

    try:
        result = run_lane_rotation(count=args.count)
        logger.info(f"✅ Lane rotation finished. Covered {len(result['lanes_covered'])} lane(s).")
    except Exception as e:
        logger.error(f"❌ Lane rotation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
