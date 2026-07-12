from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests

from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.utils.logger import setup_logger

logger = setup_logger("official_page_collectors")


class OfficialRecallPageCollector:
    """Conservative collector for official recall listing pages."""

    source_type = "official_recall_page"

    def __init__(self, base_url: str, source_name: str, credibility_score: float):
        self.base_url = base_url
        self.source_name = source_name
        self.credibility_score = credibility_score

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        logger.info(f"Collecting official recall page links from {self.source_name}")
        try:
            response = requests.get(
                self.base_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36 EGF-Automation/1.0"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=20,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Official page collection failed for {self.source_name}: {e}")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=self.base_url,
                    title=f"{self.source_name} collection blocked or failed",
                    credibility_score=self.credibility_score,
                    status="failed",
                    notes=str(e),
                    snippet=(
                        "The source is registered and should be monitored, but this run could not fetch it. "
                        "Retry later or use a source-specific feed/API if available."
                    ),
                )
            ]

        links = _extract_links(response.text, self.base_url)
        ranked = _rank_links(links, f"{topic_title} {task.query}")
        sources = []
        for title, url, score in ranked[:limit]:
            display_title = _best_title(title, url)
            sources.append(
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=url,
                    title=display_title,
                    credibility_score=self.credibility_score,
                    notes=f"Official listing page link from {self.source_name}. Match score={score}.",
                    snippet=display_title,
                )
            )
        return sources


class FDARecallsPageCollector(OfficialRecallPageCollector):
    def __init__(self):
        super().__init__(
            base_url="https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts",
            source_name="FDA Recalls, Market Withdrawals, & Safety Alerts",
            credibility_score=0.98,
        )


class USDAFSISRecallsCollector(OfficialRecallPageCollector):
    def __init__(self):
        super().__init__(
            base_url="https://www.fsis.usda.gov/recalls",
            source_name="USDA FSIS Recalls & Public Health Alerts",
            credibility_score=0.95,
        )


def _extract_links(page_html: str, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    for href, raw_label in pattern.findall(page_html):
        label = _clean_html(raw_label)
        if not label or len(label) < 8:
            continue
        url = urljoin(base_url, html.unescape(href))
        if url.startswith("mailto:") or url.startswith("tel:"):
            continue
        links.append((label, url))
    return _dedupe_links(links)


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedupe_links(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = set()
    deduped = []
    for title, url in links:
        key = (title.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, url))
    return deduped


def _rank_links(links: list[tuple[str, str]], query: str) -> list[tuple[str, str, int]]:
    query_terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    important_terms = {"gluten", "wheat", "allergen", "undeclared", "label", "recall", "bread", "flour"}
    query_terms.update(important_terms)

    ranked = []
    for title, url in links:
        haystack = f"{title} {url}".lower()
        score = sum(1 for term in query_terms if term in haystack)
        if score > 0:
            ranked.append((title, url, score))
    ranked.sort(key=lambda item: item[2], reverse=True)
    return ranked


def _best_title(label: str, url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    slug_title = re.sub(r"[-_]+", " ", slug).strip().title()
    if len(slug_title) > len(label) + 12:
        return slug_title
    return label


if __name__ == "__main__":
    sample_task = ResearchTask(
        lane="laws_labeling",
        source_type="official_recall_page",
        query="undeclared wheat gluten allergen",
        priority=1,
        reason="Manual collector smoke test.",
    )
    for item in FDARecallsPageCollector().collect(sample_task, "undeclared wheat recalls", limit=3):
        print(item.title, item.url)
