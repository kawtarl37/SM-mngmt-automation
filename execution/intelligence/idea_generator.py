from datetime import datetime
from execution.config import PROMPTS_DIR, DAILY_IDEA_GENERATION_COUNT
from execution.db import get_connection
from execution.models import IdeaGenerationResponse
from execution.utils.llm_client import LLMClient
from execution.utils.logger import setup_logger
from execution.intelligence.trend_analyzer import get_top_trends
from execution.intelligence.duplication_checker import get_existing_recipes_formatted
from execution.editorial.memory import current_month_label, memory_prompt_block
from execution.editorial.schema import ensure_editorial_schema
from execution.editorial.taxonomy import classify_lane, lane_prompt_block

logger = setup_logger("idea_generator")

def generate_ideas() -> IdeaGenerationResponse | None:
    """Generate 20 ideas using the LLM based on trends and existing recipes."""
    logger.info("Starting idea generation...")
    
    # 1. Gather context
    trends = get_top_trends(limit=10)
    if not trends:
        logger.warning("No trending topics found. Will rely purely on general knowledge.")
        trends_text = "No current specific trends available."
    else:
        trends_text = "\n".join(f"- {t['title']} (relevance: {t['relevance']:.2f})" for t in trends)

    existing_titles = get_existing_recipes_formatted(limit=150)
    if not existing_titles:
        existing_titles = "No existing recipes."
        
    # 2. Load Prompts
    try:
        with open(PROMPTS_DIR / "brand_system_prompt.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
            
        with open(PROMPTS_DIR / "idea_generation.txt", "r", encoding="utf-8") as f:
            user_prompt_template = f.read()
    except Exception as e:
        logger.error(f"Failed to load prompt templates: {e}")
        return None
        
    user_prompt = user_prompt_template.format(
        current_month=current_month_label(),
        trending_topics=trends_text,
        existing_titles=existing_titles,
        recent_titles=memory_prompt_block(limit=80),
        editorial_lanes=lane_prompt_block(),
    )
    
    # 3. Call LLM
    client = LLMClient()
    try:
        response = client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=IdeaGenerationResponse,
            task_name="idea_generation"
        )
        
        # 4. Save to DB
        save_ideas_to_db(response)
        return response
        
    except Exception as e:
        logger.error(f"Error during idea generation: {e}")
        return None

def save_ideas_to_db(response: IdeaGenerationResponse):
    """Save the generated ideas to the content_ideas table."""
    ensure_editorial_schema()
    batch_date = datetime.now().strftime("%Y-%m-%d")
    inserted = 0
    
    with get_connection() as conn:
        cursor = conn.cursor()
        for idea in response.ideas:
            lane = idea.content_lane or classify_lane(f"{idea.title} {idea.description}")
            cursor.execute(
                """INSERT INTO content_ideas 
                   (title, content_type, description, content_lane, angle_type,
                    freshness_hook, source_hint, batch_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    idea.title,
                    idea.content_type,
                    idea.description,
                    lane,
                    idea.angle_type,
                    idea.freshness_hook,
                    idea.source_hint,
                    batch_date,
                )
            )
            inserted += 1
        conn.commit()
        
    logger.info(f"Saved {inserted} new ideas to DB.")

if __name__ == "__main__":
    generate_ideas()
