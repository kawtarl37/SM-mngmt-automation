from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests

from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.research.source_manager import list_approved_sources
from execution.utils.logger import setup_logger

logger = setup_logger("approved_source_page_collector")


SOURCE_TYPE_ALIASES = {
    "brand_product_page": ("brand_product_page",),
    "retailer_product_page": ("retailer_product_page",),
    "restaurant_allergen_page": ("restaurant_allergen_page",),
    "tool_product_page": ("tool_product_page", "retailer_product_page"),
    "app_review_page": ("app_review_page", "trend_planning_tool"),
    "trend_planning_tool": ("trend_planning_tool", "app_review_page"),
}


class ApprovedSourcePageCollector:
    """Collect approved priority pages for product, restaurant, app, and tool lanes."""

    def __init__(self, source_type: str):
        self.source_type = source_type

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        source_types = SOURCE_TYPE_ALIASES.get(task.source_type, (task.source_type,))
        approved_sources = list_approved_sources(
            lane=task.lane,
            source_types=source_types,
            priority_only=True,
        )
        if not approved_sources:
            logger.info(f"No approved priority sources for lane={task.lane}, source_type={task.source_type}")
            return []

        query_terms = _query_terms(f"{topic_title} {task.query}")
        results: list[CollectedSource] = []
        for source in approved_sources[: max(limit, 1)]:
            results.extend(self._collect_one(source, task, topic_title, query_terms))
            if len(results) >= limit:
                break
        return results[:limit]

    def _collect_one(
        self,
        source: dict,
        task: ResearchTask,
        topic_title: str,
        query_terms: set[str],
    ) -> list[CollectedSource]:
        url = source["base_url"]
        logger.info(f"Collecting approved source page: {source['name']} ({url})")
        try:
            response = requests.get(
                url,
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
            logger.error(f"Approved source page collection failed for {source['name']}: {e}")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=source["source_type"],
                    url=url,
                    title=f"{source['name']} collection blocked or failed",
                    credibility_score=source["credibility_score"],
                    status="failed",
                    notes=str(e),
                    snippet="Approved priority source could not be fetched in this run.",
                )
            ]

        title = _extract_title(response.text) or source["name"]
        description = _extract_meta_description(response.text)
        page_source = CollectedSource(
            topic_title=topic_title,
            lane=task.lane,
            source_type=source["source_type"],
            url=url,
            title=title,
            credibility_score=source["credibility_score"],
            notes=_notes_for_source(source),
            snippet=description or source.get("notes") or title,
        )

        link_sources = []
        for label, link_url, score in _rank_links(_extract_links(response.text, url), query_terms)[:3]:
            if link_url == url:
                continue
            link_sources.append(
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=source["source_type"],
                    url=link_url,
                    title=label,
                    credibility_score=source["credibility_score"],
                    notes=f"Relevant approved-source link from {source['name']}. Match score={score}.",
                    snippet=label,
                )
            )

        return [page_source] + link_sources


def _notes_for_source(source: dict) -> str:
    parts = []
    if source.get("content_angle"):
        parts.append(f"Angle: {source['content_angle']}")
    if source.get("best_home"):
        parts.append(f"Best home: {source['best_home']}")
    if source.get("fact_check_required"):
        parts.append("Fresh official fact-check required before publishing.")
    return " | ".join(parts) or source.get("notes") or ""


def _extract_title(page_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    return _clean_html(match.group(1)) if match else ""


def _extract_meta_description(page_html: str) -> str:
    patterns = (
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE)
        if match:
            return _clean_html(match.group(1))
    return ""


def _extract_links(page_html: str, base_url: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    links = []
    seen = set()
    for href, raw_label in pattern.findall(page_html):
        label = _clean_html(raw_label)
        if len(label) < 5:
            continue
        url = urljoin(base_url, html.unescape(href))
        if not url.startswith("http"):
            continue
        key = (label.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        links.append((label, url))
    return links


def _rank_links(links: list[tuple[str, str]], query_terms: set[str]) -> list[tuple[str, str, int]]:
    ranked = []
    useful_terms = query_terms | {
        "gluten",
        "allergen",
        "ingredient",
        "nutrition",
        "product",
        "menu",
        "recipe",
        "review",
        "store",
    }
    for label, url in links:
        haystack = f"{label} {url}".lower()
        score = sum(1 for term in useful_terms if term in haystack)
        if score:
            ranked.append((label, url, score))
    ranked.sort(key=lambda item: item[2], reverse=True)
    return ranked


def _query_terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2}


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
