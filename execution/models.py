from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime

# =======================
# Internal Entity Models
# =======================

class RecipeModel(BaseModel):
    title: str
    cuisine: Optional[str] = None
    cooking_method: Optional[str] = None
    ingredients: List[str] = Field(default_factory=list)
    source: str = "generated"
    url: Optional[str] = None

class TrendTopicModel(BaseModel):
    source: str
    subreddit: Optional[str] = None
    title: str
    body: Optional[str] = None
    score: int = 0
    comment_count: int = 0
    relevance: float = 0.0

# =======================
# LLM Response Schemas
# =======================

class IdeaGenerationItem(BaseModel):
    """Schema for individual ideas returned by the LLM."""
    title: str
    content_type: str = Field(description="'recipe', 'tip', or 'education'")
    description: str
    target_keyword: str
    estimated_engagement: str = Field(description="'high', 'medium', or 'low'")
    content_lane: Optional[str] = Field(
        default=None,
        description="Editorial lane key, e.g. 'laws_labeling', 'product_watch', or 'comparison'",
    )
    angle_type: Optional[str] = Field(
        default=None,
        description="Editorial format, e.g. comparison, explainer, product_roundup, field_guide, review_test",
    )
    freshness_hook: Optional[str] = Field(
        default=None,
        description="Why this idea feels timely, specific, or newly useful right now",
    )
    source_hint: Optional[str] = Field(
        default=None,
        description="Likely source type to verify before writing, e.g. FDA, brand page, Reddit, Google News",
    )
    
class IdeaGenerationResponse(BaseModel):
    """Schema for the full list of 20 ideas returned by the LLM."""
    ideas: List[IdeaGenerationItem]

class CaptionGenerationResponse(BaseModel):
    """Schema for the final Pin title and description from the LLM."""
    pin_title: str
    pin_description: str
    hashtags: List[str]
    alt_text: str


class BlogTitleSuggestionResponse(BaseModel):
    """Schema for suggesting one replacement blog/trend title."""
    title: str = Field(description="One concise, SEO-friendly title for the approved trend.")


class BlogGenerationResponse(BaseModel):
    """Schema for the full blog content returned by the LLM.
    Each field maps to a placeholder in the locked HTML template."""
    main_title: str = Field(description="SEO-optimized article title for [MAIN_TITLE_DYNAMIC]")
    ebook_hero_title: str = Field(description="Promotional hero title for the free e-book, not the SEO title")
    intro_paragraph: str = Field(description="Short lead paragraph for [INTRO_PARAGRAPH]")
    intro_paragraph_1: str = Field(description="Introduction paragraph 1")
    intro_paragraph_2: str = Field(description="Introduction paragraph 2")
    intro_paragraph_3: str = Field(description="Introduction paragraph 3")
    section_1_title: str
    section_1_content: str = Field(description="HTML content for section 1 (can include <p>, <ul>, <li> tags)")
    section_2_title: str
    section_2_content: str = Field(description="HTML content for section 2, should relate to the Amazon product")
    section_3_title: str
    section_3_content: str = Field(description="HTML content for section 3")
    section_4_title: str
    section_4_content: str = Field(description="HTML content for section 4")
    section_5_title: str
    section_5_content: str = Field(description="HTML content for section 5")
    takeaway_1: str
    takeaway_2: str
    takeaway_3: str
    takeaway_4: str
    takeaway_5: str
    category: str = Field(description="Blog category, e.g. 'Gluten-Free Living', 'Recipes', 'Tips'")


class DraftSection(BaseModel):
    """One reusable section in a research-backed platform draft."""

    heading: str
    body: str = Field(description="Draft body for this section. Basic HTML is allowed for blog content only.")


class PlatformDraftResponse(BaseModel):
    """Structured draft generated from a research-backed content brief."""

    title: str = Field(description="Platform-appropriate title, subject line, pin title, or app card title.")
    dek: str = Field(description="One concise summary/subtitle for the draft.")
    sections: List[DraftSection] = Field(description="Ordered draft sections matching the requested platform.")
    call_to_action: str = Field(description="Reader next step or editorial CTA.")
    source_notes: List[str] = Field(description="Short notes naming which sources support important claims.")
    verification_notes: List[str] = Field(
        description="Any claims that need fresh official checking before publishing."
    )
    status_recommendation: str = Field(
        description="Recommended workflow status: 'ready_for_review', 'needs_more_sources', or 'do_not_publish_yet'."
    )


# =======================
# Recipe Generation Models (WP Recipe Maker)
# =======================

RECIPE_CATEGORIES = [
    "Bake / Make It Yourself",
    "Breakfasts That Fuel Your Day",
    "Comfort Food Classics (Made Gluten-Free)",
    "Desserts & Baked Treats",
    "Meal Prep & Freezer-Friendly Recipes",
    "Quick & Easy Weeknight Dinners",
]

DIFFICULTY_LEVELS = ["Easy", "Medium", "Hard"]


class RecipeIngredient(BaseModel):
    """A single ingredient with exact measurements."""
    amount: str = Field(description="Numeric or fractional amount, e.g. '1', '1/2', '2.5'")
    unit: str = Field(description="US measurement unit, e.g. 'cup', 'tbsp', 'oz', 'lb', or '' for count items")
    name: str = Field(description="Ingredient name, e.g. 'Bob\'s Red Mill GF 1-to-1 flour'")
    notes: str = Field(default="", description="Optional preparation note, e.g. 'diced', 'room temperature', 'certified GF'")


class RecipeInstruction(BaseModel):
    """A single numbered instruction step."""
    step_number: int
    text: str = Field(description="Clear, actionable instruction. ~2-4 sentences.")
    image_prompt: str = Field(description="Image-generation prompt for this step's photo. Describe the exact action visible in 'The Sunday Light Kitchen' setting.")


class RecipeGenerationResponse(BaseModel):
    """Full WP Recipe Maker-compatible recipe schema generated by LLM."""
    # Core identity
    title: str = Field(description="Recipe title. Catchy, SEO-optimized, includes 'gluten-free' or 'GF'. Max 70 chars.")
    category: str = Field(description=f"Exactly ONE of: {RECIPE_CATEGORIES}")
    tags: List[str] = Field(description="5-10 relevant tags, e.g. ['gluten-free dinner', 'rice noodles', 'Asian-inspired']")
    difficulty: str = Field(description="Exactly one of: Easy, Medium, Hard")

    # Summary & description
    description: str = Field(description="2-3 sentence recipe intro with brand voice (witty, relatable). Used as WP post excerpt.")
    substitutions: str = Field(description="HTML <ul> list of substitutions and variations: dairy-free swap, egg-free swap, lower-sugar option, and 1-2 fun add-ins. Each item as a <li>. Example: <ul><li><strong>Dairy-Free:</strong> Use coconut milk instead of milk.</li></ul>")
    notes: str = Field(description="Claire's gluten-free baking notes — technique tips, cross-contamination warnings, certified GF product callouts, storage tips. 3-5 sentences, written in Claire's voice.")
    tips: str = Field(description="2-3 practical tips for success, texture fixes, or visual cues. Written as plain sentences.")

    # Timing & servings
    prep_time: int = Field(description="Prep time in minutes")
    cook_time: int = Field(description="Cook/bake time in minutes")
    total_time: int = Field(description="Total time in minutes (prep + cook + any resting)")
    servings: int = Field(description="Number of servings (realistic for the recipe type)")
    servings_unit: str = Field(default="servings", description="Unit label, e.g. 'servings', 'muffins', 'cookies', 'slices'")
    kcal_per_serving: int = Field(description="Estimated calories per serving, rounded to the nearest whole kcal")

    # Ingredients
    ingredients: List[RecipeIngredient] = Field(description="Complete ingredient list with exact US measurements. All GF-safe.")

    # Instructions
    instructions: List[RecipeInstruction] = Field(description="Numbered steps. Min 4, max 10. Each step includes an image prompt for a step photo.")

    # Image prompts
    cover_image_prompt: str = Field(description="Image-generation prompt for the hero/cover image. Overhead or 45-degree beauty shot of the finished dish in 'The Sunday Light Kitchen'. Warm, natural lighting. Food-focused. Realistic GF textures. No text in image. Vertical 9:16 ratio composition.")
    pinterest_description: str = Field(description="160-char max Pinterest pin description. Mentions GF, the dish, a benefit, and a CTA. Brand voice.")

# =======================
# Trend Synthesis Models
# =======================

class TrendyTopicItem(BaseModel):
    title: str = Field(description="Catchy title of the trend (e.g. 'Air Fryer Gluten Contamination')")
    details: str = Field(description="A 3-5 sentence explanation of what people are discussing or what the study found, written in brand voice.")
    source: str = Field(description="Source of the trend, e.g. 'Reddit (r/celiac)' or 'PubMed (Nutrients)'")
    relevance_score: float = Field(description="Estimated relevance to EGF readers between 0.0 and 1.0")
    content_lane: Optional[str] = Field(
        default=None,
        description="Editorial lane key, e.g. laws_labeling, product_watch, comparison, restaurants_travel",
    )
    angle_type: Optional[str] = Field(
        default=None,
        description="Editorial format, e.g. comparison, explainer, product_roundup, field_guide, review_test",
    )
    freshness_hook: Optional[str] = Field(
        default=None,
        description="A short explanation of why this is timely or interesting now",
    )

class TrendyTopicResponse(BaseModel):
    topics: List[TrendyTopicItem]

