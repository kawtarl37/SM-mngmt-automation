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
    
class IdeaGenerationResponse(BaseModel):
    """Schema for the full list of 20 ideas returned by the LLM."""
    ideas: List[IdeaGenerationItem]

class CaptionGenerationResponse(BaseModel):
    """Schema for the final Pin title and description from the LLM."""
    pin_title: str
    pin_description: str
    hashtags: List[str]
    alt_text: str


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
