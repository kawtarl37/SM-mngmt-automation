from __future__ import annotations

from dataclasses import dataclass

from execution.editorial.memory import PublishedTopic, novelty_score
from execution.editorial.taxonomy import CONTENT_LANES, classify_lane, is_generic_topic


FRESHNESS_SIGNALS = (
    "new",
    "latest",
    "recent",
    "2026",
    "recall",
    "launched",
    "updated",
    "changed",
    "study",
    "research",
    "people are talking",
    "popular",
    "trend",
)

USEFULNESS_SIGNALS = (
    "how",
    "which",
    "what",
    "best",
    "compare",
    "checklist",
    "tips",
    "tool",
    "app",
    "restaurant",
    "label",
    "safe",
    "avoid",
)

ENTERTAINMENT_SIGNALS = (
    "vs",
    "actually",
    "worth",
    "survive",
    "drama",
    "mistake",
    "honest",
    "talking about",
    "we tried",
)


@dataclass(frozen=True)
class EditorialScore:
    lane: str
    freshness: float
    novelty: float
    usefulness: float
    entertainment: float
    lane_diversity: float
    total: float


class EditorialScorer:
    """Scores topic candidates for freshness, diversity, usefulness, and novelty."""

    def __init__(self, memory: list[PublishedTopic] | None = None):
        self.memory = memory

    def score(self, title: str, details: str = "", requested_lane: str | None = None) -> EditorialScore:
        text = f"{title} {details}".lower()
        lane = requested_lane or classify_lane(text)
        freshness = self._signal_score(text, FRESHNESS_SIGNALS)
        novelty = 0.0 if is_generic_topic(title) else novelty_score(title, self.memory)
        usefulness = self._signal_score(text, USEFULNESS_SIGNALS)
        entertainment = self._signal_score(text, ENTERTAINMENT_SIGNALS)
        lane_diversity = self._lane_diversity(lane)

        total = (
            freshness * 0.22
            + novelty * 0.28
            + usefulness * 0.22
            + entertainment * 0.14
            + lane_diversity * 0.14
        )
        return EditorialScore(
            lane=lane,
            freshness=freshness,
            novelty=novelty,
            usefulness=usefulness,
            entertainment=entertainment,
            lane_diversity=lane_diversity,
            total=total,
        )

    @staticmethod
    def _signal_score(text: str, signals: tuple[str, ...]) -> float:
        hits = sum(1 for signal in signals if signal in text)
        return min(hits / 3.0, 1.0)

    def _lane_diversity(self, lane: str) -> float:
        if not self.memory:
            return 1.0

        recent_titles = [item.title for item in self.memory[:40]]
        lane_hits = sum(1 for title in recent_titles if classify_lane(title) == lane)
        if lane_hits == 0:
            return 1.0
        return max(0.15, 1.0 - min(lane_hits / 12.0, 0.85))


def lane_rotation_prompt() -> str:
    """Tell the LLM how to distribute ideas across lanes."""

    labels = ", ".join(lane.label for lane in CONTENT_LANES)
    return (
        "Use a diverse lane mix. Do not let Recipes, Bread, Baking, or Beginner Basics dominate. "
        f"Available lanes: {labels}. At least 8 different lanes should appear when generating 20 ideas."
    )

