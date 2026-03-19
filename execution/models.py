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
