from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import requests

from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.utils.logger import setup_logger

logger = setup_logger("pubmed_collector")


class PubMedCollector:
    """Collect PubMed article records for science/health lanes."""

    source_type = "medical_research"
    CREDIBILITY = 0.92
    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        query = _build_query(topic_title)
        logger.info(f"Collecting PubMed records for: {query}")
        try:
            pmids = self._search_pmids(query, limit)
            if not pmids:
                return []
            articles = self._fetch_articles(pmids)
        except Exception as e:
            logger.error(f"PubMed collection failed: {e}")
            return [
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url="https://pubmed.ncbi.nlm.nih.gov/",
                    title="PubMed collection blocked or failed",
                    credibility_score=self.CREDIBILITY,
                    status="failed",
                    notes=str(e),
                    snippet="PubMed is registered as a trusted science source, but this run could not fetch records.",
                )
            ]
        return [
            CollectedSource(
                topic_title=topic_title,
                lane=task.lane,
                source_type=self.source_type,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/",
                title=article["title"],
                credibility_score=self.CREDIBILITY,
                notes="PubMed article record.",
                snippet=article["abstract"],
                published_at=article["published_at"],
                external_id=article["pmid"],
            )
            for article in articles
        ]

    def _search_pmids(self, query: str, limit: int) -> list[str]:
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "sort": "pub_date",
            "retmax": min(limit, 20),
        }
        response = requests.get(self.ESEARCH_URL, params=params, timeout=20)
        response.raise_for_status()
        return response.json().get("esearchresult", {}).get("idlist", [])

    def _fetch_articles(self, pmids: list[str]) -> list[dict]:
        params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
        response = requests.get(self.EFETCH_URL, params=params, timeout=20)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        articles = []
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID") or ""
            title = "".join(article.find(".//ArticleTitle").itertext()).strip() if article.find(".//ArticleTitle") is not None else "Untitled PubMed article"
            abstract_parts = ["".join(node.itertext()).strip() for node in article.findall(".//AbstractText")]
            abstract = " ".join(part for part in abstract_parts if part)
            year = article.findtext(".//PubDate/Year") or article.findtext(".//ArticleDate/Year")
            month = article.findtext(".//PubDate/Month") or "01"
            day = article.findtext(".//PubDate/Day") or "01"
            articles.append(
                {
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract[:1200],
                    "published_at": _date_or_year(year, month, day),
                }
            )
        return articles


def _build_query(topic_title: str) -> str:
    return f'({topic_title}) AND (celiac OR "gluten-free" OR gluten OR wheat)'


def _date_or_year(year: str | None, month: str, day: str) -> str | None:
    if not year:
        return None
    month_lookup = {
        "Jan": "01",
        "Feb": "02",
        "Mar": "03",
        "Apr": "04",
        "May": "05",
        "Jun": "06",
        "Jul": "07",
        "Aug": "08",
        "Sep": "09",
        "Oct": "10",
        "Nov": "11",
        "Dec": "12",
    }
    month_value = month_lookup.get(month, month if month.isdigit() else "01")
    day_value = day if day.isdigit() else "01"
    return f"{year}-{month_value.zfill(2)}-{day_value.zfill(2)}"

