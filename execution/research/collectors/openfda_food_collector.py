from __future__ import annotations

import re
from urllib.parse import urlencode

import requests

from execution.research.collectors.base import CollectedSource
from execution.research.models import ResearchTask
from execution.utils.logger import setup_logger

logger = setup_logger("openfda_food_collector")


class OpenFDAFoodEnforcementCollector:
    """Collect food enforcement records from the openFDA API."""

    source_type = "official_api"
    API_URL = "https://api.fda.gov/food/enforcement.json"
    CREDIBILITY = 0.95

    def collect(self, task: ResearchTask, topic_title: str, limit: int = 10) -> list[CollectedSource]:
        terms = _extract_search_terms(f"{topic_title} {task.query}")
        search = _build_openfda_search(terms)
        params = {"search": search, "limit": min(limit, 100), "sort": "report_date:desc"}

        logger.info(f"Collecting openFDA food enforcement records for: {topic_title}")
        try:
            response = requests.get(self.API_URL, params=params, timeout=20)
            if response.status_code == 404:
                logger.info("openFDA returned no matching records for primary query; trying fallback.")
                records = self._fallback_collect(limit=min(limit, 100))
            else:
                response.raise_for_status()
                records = response.json().get("results", [])
        except Exception as e:
            logger.error(f"openFDA collection failed: {e}")
            return []

        sources = []
        for record in records:
            recall_number = record.get("recall_number") or ""
            title = _build_title(record)
            snippet = _build_snippet(record)
            detail_url = _build_detail_url(recall_number, params)
            sources.append(
                CollectedSource(
                    topic_title=topic_title,
                    lane=task.lane,
                    source_type=self.source_type,
                    url=detail_url,
                    title=title,
                    credibility_score=self.CREDIBILITY,
                    notes="Structured openFDA food enforcement record.",
                    snippet=snippet,
                    published_at=_date_to_iso(record.get("report_date")),
                    external_id=recall_number or None,
                )
            )
        return sources

    def _fallback_collect(self, limit: int) -> list[dict]:
        fallback_search = (
            'reason_for_recall:"undeclared" OR reason_for_recall:"wheat" '
            'OR reason_for_recall:"allergen" OR product_description:"gluten"'
        )
        try:
            response = requests.get(
                self.API_URL,
                params={"search": fallback_search, "limit": limit, "sort": "report_date:desc"},
                timeout=20,
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            logger.error(f"openFDA fallback collection failed: {e}")
            return []


def _extract_search_terms(text: str) -> list[str]:
    """Extract food-safety search terms, with gluten/allergen terms always included."""

    candidates = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", text.lower())
    priority = [
        "gluten",
        "wheat",
        "allergen",
        "undeclared",
        "label",
        "labeling",
        "celiac",
        "bread",
        "flour",
        "pasta",
        "snack",
    ]
    terms = []
    for term in priority + candidates:
        clean = term.strip("-")
        if clean and clean not in terms:
            terms.append(clean)
        if len(terms) >= 8:
            break
    return terms or ["gluten", "wheat", "allergen"]


def _build_openfda_search(terms: list[str]) -> str:
    fields = ("reason_for_recall", "product_description", "code_info")
    clauses = []
    for term in terms:
        for field in fields:
            clauses.append(f'{field}:"{term}"')
    return "(" + " OR ".join(clauses) + ")"


def _build_title(record: dict) -> str:
    firm = record.get("recalling_firm") or "FDA food enforcement record"
    product = record.get("product_description") or "food product"
    return f"{firm}: {product[:120]}"


def _build_snippet(record: dict) -> str:
    parts = []
    for label, key in (
        ("Reason", "reason_for_recall"),
        ("Product", "product_description"),
        ("Distribution", "distribution_pattern"),
        ("Classification", "classification"),
        ("Status", "status"),
    ):
        value = record.get(key)
        if value:
            parts.append(f"{label}: {value}")
    return " | ".join(parts)


def _date_to_iso(value: str | None) -> str | None:
    if not value or len(value) != 8:
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _build_detail_url(recall_number: str, params: dict) -> str:
    if recall_number:
        query = urlencode({"search": f'recall_number:"{recall_number}"'})
    else:
        query = urlencode(params)
    return f"https://open.fda.gov/apis/food/enforcement/?{query}"


if __name__ == "__main__":
    sample_task = ResearchTask(
        lane="laws_labeling",
        source_type="official_api",
        query="undeclared wheat gluten allergen",
        priority=1,
        reason="Manual collector smoke test.",
    )
    results = OpenFDAFoodEnforcementCollector().collect(sample_task, "undeclared wheat recalls", limit=3)
    for item in results:
        print(item.title)
