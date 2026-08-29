from __future__ import annotations

from urllib.parse import urlparse

import requests

from execution.config import BRAVE_SEARCH_API_KEY
from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.utils.logger import setup_logger

logger = setup_logger("web_search_collector")

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Domain-tier credibility heuristic. This only shapes prompt-level confidence
# framing (e.g. platform_packager's source_confidence bucketing) — it never
# bypasses the approval gate. A first-time domain still lands in
# source_notifications as pending_approval regardless of this score.
TIER_HIGH_SUFFIXES = (".gov", ".edu")
TIER_HIGH_DOMAINS = {
    "celiac.org",
    "beyondceliac.org",
    "gfco.org",
    "pubmed.ncbi.nlm.nih.gov",
}
TIER_MEDIUM_DOMAINS = {
    "apps.apple.com",
    "play.google.com",
    "target.com",
    "walmart.com",
    "instacart.com",
    "wholefoodsmarket.com",
    "traderjoes.com",
    "amazon.com",
}
CREDIBILITY_HIGH = 0.82
CREDIBILITY_MEDIUM = 0.65
CREDIBILITY_DEFAULT = 0.55


def _domain_credibility(url: str) -> float:
    host = (urlparse(url).netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if any(host.endswith(suffix) for suffix in TIER_HIGH_SUFFIXES) or host in TIER_HIGH_DOMAINS:
        return CREDIBILITY_HIGH
    if host in TIER_MEDIUM_DOMAINS:
        return CREDIBILITY_MEDIUM
    return CREDIBILITY_DEFAULT


class BraveSearchCollector:
    """Live web discovery via the Brave Web Search API.

    Fills the gap left by ApprovedSourcePageCollector, which can only fetch
    pages a human has already pre-approved: this collector can surface a
    brand-new brand/product/restaurant/app/tool page or news item for a topic
    that has no priority-list entry yet. Every result still passes through
    the same source_manager.is_source_approved / propose_source gate as
    every other collector, so a first-time domain still requires human
    approval before its facts are trusted.

    Chosen over Google Programmable Search because, as of 2026, Google's
    Custom Search JSON API is closed to new customers and its Programmable
    Search Engine product no longer offers whole-web search to new engines
    (capped to a fixed list of domains you specify at creation). Brave's Web
    Search API still does true open web search, no domain list required.
    """

    source_type = "web_search"

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        if not BRAVE_SEARCH_API_KEY:
            logger.warning("BRAVE_SEARCH_API_KEY not configured; skipping web_search collection.")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url="config://brave-search",
                    title="Brave Search API not configured",
                    credibility_score=0.0,
                    status="failed",
                    notes="Set BRAVE_SEARCH_API_KEY in .env to enable live web discovery.",
                    snippet="Web search collector skipped: missing API credentials.",
                )
            ]

        query = task.query or topic_title
        capped_limit = max(1, min(limit, 20))  # Brave returns at most 20 results per call
        try:
            response = requests.get(
                SEARCH_URL,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
                },
                params={
                    "q": query,
                    "count": capped_limit,
                },
                timeout=15,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Brave Search failed for query='{query}': {e}")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=f"https://search.brave.com/search?q={query}",
                    title="Web search collection blocked or failed",
                    credibility_score=0.0,
                    status="failed",
                    notes=str(e),
                    snippet="Live web search could not be completed in this run.",
                )
            ]

        items = (response.json().get("web") or {}).get("results") or []
        results: list[CollectedSource] = []
        for item in items[:capped_limit]:
            url = item.get("url") or ""
            if not url:
                continue
            results.append(
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=url,
                    title=item.get("title") or url,
                    credibility_score=_domain_credibility(url),
                    notes=f"Brave Search result for query: {query}",
                    snippet=item.get("description") or "",
                )
            )
        return results
