from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    """Defines how a research brief should be packaged for a publishing surface."""

    key: str
    label: str
    purpose: str
    required_sections: tuple[str, ...]
    style_notes: tuple[str, ...]


PLATFORMS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        key="blog",
        label="Blog",
        purpose="Long-form SEO and AI-search optimized article.",
        required_sections=(
            "specific_hook",
            "reader_problem",
            "verified_context",
            "practical_steps",
            "claire_take",
            "next_action",
        ),
        style_notes=(
            "Conversational and useful, with enough depth to rank and satisfy search intent.",
            "Include source-backed claims and avoid unsupported medical or legal advice.",
        ),
    ),
    PlatformSpec(
        key="newsletter",
        label="Newsletter",
        purpose="Shorter, relationship-driven editorial issue or section.",
        required_sections=(
            "subject_line",
            "opening_note",
            "top_takeaway",
            "quick_hits",
            "recommended_action",
        ),
        style_notes=(
            "More personal than the blog. Lead with the reader's lived frustration.",
            "Keep the value clear enough to skim over coffee.",
        ),
    ),
    PlatformSpec(
        key="pinterest",
        label="Pinterest",
        purpose="Discovery-oriented pin title, description, and visual concept.",
        required_sections=(
            "pin_title",
            "pin_description",
            "visual_concept",
            "destination_url_plan",
        ),
        style_notes=(
            "Curiosity plus clarity. Avoid clickbait.",
            "Make the visual promise concrete and useful.",
        ),
    ),
    PlatformSpec(
        key="app",
        label="Future App",
        purpose="Structured content card, searchable topic, or in-app recommendation.",
        required_sections=(
            "card_title",
            "summary",
            "source_confidence",
            "tags",
            "action_items",
        ),
        style_notes=(
            "Keep data structured and concise.",
            "Expose source confidence so the app can distinguish tips from verified alerts.",
        ),
    ),
)


PLATFORMS_BY_KEY = {platform.key: platform for platform in PLATFORMS}


def platform_prompt_block() -> str:
    """Return a compact description of supported output surfaces."""

    lines = []
    for platform in PLATFORMS:
        sections = ", ".join(platform.required_sections)
        lines.append(f"- {platform.label} (`{platform.key}`): {platform.purpose} Sections: {sections}.")
    return "\n".join(lines)

