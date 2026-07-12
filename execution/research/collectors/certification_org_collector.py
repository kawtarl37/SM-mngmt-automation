from __future__ import annotations

import html
import re
from urllib.parse import quote_plus, urljoin

import requests

from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.utils.logger import setup_logger

logger = setup_logger("certification_org_collector")


class TrustedOrgPageCollector:
    """Search trusted gluten-free/celiac organization pages using their site search."""

    source_type = "gluten_free_organization"

    def __init__(self, name: str, base_url: str, credibility_score: float):
        self.name = name
        self.base_url = base_url.rstrip("/") + "/"
        self.credibility_score = credibility_score

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        search_url = urljoin(self.base_url, f"?s={quote_plus(topic_title)}")
        logger.info(f"Collecting trusted organization pages from {self.name}")
        try:
            response = requests.get(
                search_url,
                headers={"User-Agent": "EGF-Automation/1.0 research collector"},
                timeout=20,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Trusted organization collection failed for {self.name}: {e}")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=search_url,
                    title=f"{self.name} collection blocked or failed",
                    credibility_score=self.credibility_score,
                    status="failed",
                    notes=str(e),
                    snippet="Registered trusted organization source could not be fetched in this run.",
                )
            ]

        ranked = _rank_links(_extract_links(response.text, self.base_url), topic_title)
        return [
            CollectedSource(
                topic_title=topic_title,
                lane=task.lane,
                source_type=self.source_type,
                url=url,
                title=title,
                credibility_score=self.credibility_score,
                notes=f"Trusted organization search result from {self.name}.",
                snippet=title,
            )
            for title, url, _score in ranked[:limit]
        ]


class GFCOCollector(TrustedOrgPageCollector):
    source_type = "certification_body"

    def __init__(self):
        super().__init__("Gluten-Free Certification Organization", "https://gfco.org/", 0.88)
        self.source_type = "certification_body"


class CeliacDiseaseFoundationCollector(TrustedOrgPageCollector):
    def __init__(self):
        super().__init__("Celiac Disease Foundation", "https://celiac.org/", 0.88)


class BeyondCeliacCollector(TrustedOrgPageCollector):
    def __init__(self):
        super().__init__("Beyond Celiac", "https://www.beyondceliac.org/", 0.86)


def _extract_links(page_html: str, base_url: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    links = []
    seen = set()
    for href, raw_label in pattern.findall(page_html):
        label = _clean_html(raw_label)
        if len(label) < 8:
            continue
        url = urljoin(base_url, html.unescape(href))
        if not url.startswith(base_url):
            continue
        key = (label.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        links.append((label, url))
    return links


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _rank_links(links: list[tuple[str, str]], query: str) -> list[tuple[str, str, int]]:
    terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    ranked = []
    for title, url in links:
        score = sum(1 for term in terms if term in f"{title} {url}".lower())
        if score:
            ranked.append((title, url, score))
    ranked.sort(key=lambda item: item[2], reverse=True)
    return ranked

