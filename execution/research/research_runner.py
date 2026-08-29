from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from execution.research.brief_builder import build_content_brief
from execution.research.collectors.approved_source_page_collector import ApprovedSourcePageCollector
from execution.research.collectors.base import SourceCollector
from execution.research.collectors.certification_org_collector import (
    BeyondCeliacCollector,
    CeliacDiseaseFoundationCollector,
    GFCOCollector,
)
from execution.research.collectors.openfda_food_collector import OpenFDAFoodEnforcementCollector
from execution.research.collectors.official_page_collectors import (
    FDARecallsPageCollector,
    USDAFSISRecallsCollector,
)
from execution.research.collectors.pubmed_collector import PubMedCollector
from execution.research.collectors.web_search_collector import BraveSearchCollector
from execution.research.models import ContentBrief, ResearchTask
from execution.research.platform_packager import package_for_platform
from execution.research.schema import ensure_research_schema
from execution.research.store import save_collected_sources, save_fact_from_source
from execution.research.source_manager import is_source_approved, propose_source
from execution.research.models import SourceDefinition
from execution.utils.logger import setup_logger

logger = setup_logger("research_runner")


def run_research(
    topic_title: str,
    lane: str | None = None,
    angle_type: str | None = None,
    platform: str = "blog",
    limit_per_task: int = 5,
    persist: bool = True,
) -> dict:
    """Build a brief, run available collectors, and persist sources/facts."""

    ensure_research_schema()
    brief = build_content_brief(
        topic_title=topic_title,
        lane=lane,
        angle_type=angle_type,
        platform=platform,
        persist=persist,
    )

    all_sources, pending_sources = collect_and_gate_sources(
        brief.source_plan, topic_title=topic_title, limit_per_task=limit_per_task, persist=persist
    )

    saved_sources = save_collected_sources(all_sources) if persist else 0
    saved_facts = 0
    if persist:
        for source in all_sources:
            if save_fact_from_source(source):
                saved_facts += 1

    return {
        "brief": _brief_to_dict(brief),
        "collected_count": len(all_sources),
        "saved_sources": saved_sources,
        "saved_facts": saved_facts,
        "sources": [asdict(source) for source in all_sources],
        "pending_sources": pending_sources,
        "platform_package": asdict(package_for_platform(brief, [asdict(source) for source in all_sources])),
    }


def collect_and_gate_sources(
    tasks: list[ResearchTask] | tuple[ResearchTask, ...],
    topic_title: str,
    limit_per_task: int = 5,
    persist: bool = True,
) -> tuple[list, list[dict]]:
    """Dispatch collectors for a set of research tasks and gate results through
    source approval. Shared by run_research (single-topic research) and
    lane_discovery (proactive multi-signal discovery for a whole lane) so both
    paths trust new sources identically.
    """

    all_sources = []
    pending_sources: list[dict] = []
    seen_source_urls: set[str] = set()
    seen_pending_urls: set[str] = set()
    for task in tasks:
        collectors = _collectors_for_task(task)
        if not collectors:
            logger.info(f"No collector implemented yet for source_type={task.source_type}")
            continue

        for collector in collectors:
            sources = collector.collect(task, topic_title=topic_title, limit=limit_per_task)
            for source in sources:
                url_key = source.url.split("?", 1)[0].rstrip("/")
                if source.status == "failed" or is_source_approved(_registry_base_url(source.url), source.lane):
                    if url_key in seen_source_urls:
                        continue
                    seen_source_urls.add(url_key)
                    all_sources.append(source)
                else:
                    if url_key in seen_pending_urls:
                        continue
                    seen_pending_urls.add(url_key)
                    if persist:
                        source_id = propose_source(
                            SourceDefinition(
                                name=source.title,
                                source_type=source.source_type,
                                base_url=_registry_base_url(source.url),
                                lane=source.lane,
                                credibility_score=source.credibility_score,
                                monitor_frequency="manual_review",
                                notes=f"Discovered while researching: {topic_title}",
                                enabled=False,
                                approval_status="pending_approval",
                                added_by="research_runner",
                            ),
                            added_by="research_runner",
                        )
                    else:
                        source_id = None
                    pending_sources.append({"source": asdict(source), "source_id": source_id})

    return all_sources, pending_sources


def _collectors_for_task(task: ResearchTask) -> list[SourceCollector]:
    if task.source_type == "official_api":
        return [OpenFDAFoodEnforcementCollector()]
    if task.source_type == "official_recall_page":
        return [FDARecallsPageCollector(), USDAFSISRecallsCollector()]
    if task.source_type == "certification_body":
        return [GFCOCollector()]
    if task.source_type == "gluten_free_organization":
        return [CeliacDiseaseFoundationCollector(), BeyondCeliacCollector()]
    if task.source_type == "medical_research":
        return [PubMedCollector()]
    if task.source_type == "web_search":
        return [BraveSearchCollector()]
    if task.source_type in {
        "brand_product_page",
        "retailer_product_page",
        "restaurant_allergen_page",
        "tool_product_page",
        "app_review_page",
        "trend_planning_tool",
    }:
        return [ApprovedSourcePageCollector(task.source_type)]
    return []


def _brief_to_dict(brief: ContentBrief) -> dict:
    return {
        "topic_title": brief.topic_title,
        "lane": brief.lane,
        "angle_type": brief.angle_type,
        "platform": brief.platform,
        "reader_problem": brief.reader_problem,
        "thesis": brief.thesis,
        "platform_sections": list(brief.platform_sections),
        "source_plan": [asdict(task) for task in brief.source_plan],
        "source_candidates": [asdict(source) for source in brief.source_candidates],
    }


def _registry_base_url(url: str) -> str:
    """Map concrete URLs back to approved source roots where possible."""

    if "open.fda.gov" in url or "api.fda.gov" in url:
        return "https://api.fda.gov/food/enforcement.json"
    if "fda.gov/safety/recalls-market-withdrawals-safety-alerts" in url:
        return "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts"
    if "fsis.usda.gov/recalls" in url:
        return "https://www.fsis.usda.gov/recalls"
    if "pubmed.ncbi.nlm.nih.gov" in url:
        return "https://pubmed.ncbi.nlm.nih.gov/"
    if "gfco.org" in url:
        return "https://gfco.org/"
    if "celiac.org" in url:
        return "https://celiac.org/"
    if "beyondceliac.org" in url:
        return "https://www.beyondceliac.org/"
    return url.split("?", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run source research for an EGF topic.")
    parser.add_argument("topic_title")
    parser.add_argument("--lane", default=None)
    parser.add_argument("--angle-type", default=None)
    parser.add_argument("--platform", default="blog")
    parser.add_argument("--limit-per-task", type=int, default=5)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    result = run_research(
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
